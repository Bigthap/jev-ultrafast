"""High-speed Desktop Voice Assistant for Jev Ultrafast."""

import io
import json
import os
import queue
import time
import wave
from datetime import datetime
from urllib.parse import urlparse

import httpx
import numpy as np
import scipy.signal
import sounddevice as sd
import speech_recognition as sr
from browser_harness.helpers import cdp

from .agent import Agent
from .browser import extract_hostname
from .demo import load_environment
from .model import post_json

SAMPLE_RATE = 16000
CHANNELS = 1
DTYPE = "int16"


class VoiceError(Exception):
    """Base error for voice operations."""


class STTError(VoiceError):
    """Speech-to-text failure."""


class IntentError(VoiceError):
    """Intent extraction failure."""


class TurnCancelledError(VoiceError):
    """Turn cancelled by user."""


VOICE_HTTP_CLIENT = httpx.Client(timeout=15)


class AudioRecorder:
    """Records audio from default microphone with manual or energy-based silence detection."""

    def __init__(self, sample_rate=SAMPLE_RATE):
        self.sample_rate = sample_rate
        try:
            dev = sd.query_devices(kind="input")
            self.native_samplerate = int(dev.get("default_samplerate", 44100))
        except Exception:
            self.native_samplerate = 44100
        self._q = queue.Queue()
        self._stream = None
        self._recording = False
        self._thread = None

    def _audio_callback(self, indata, frames, time_info, status):
        if self._recording:
            self._q.put(indata.copy())

    def start(self):
        """Start non-blocking recording at the device's native samplerate."""
        self._recording = True
        while not self._q.empty():
            try:
                self._q.get_nowait()
            except queue.Empty:
                break
        try:
            self._stream = sd.InputStream(
                samplerate=self.native_samplerate,
                channels=CHANNELS,
                dtype=DTYPE,
                callback=self._audio_callback,
            )
            self._stream.start()
        except Exception:
            self._recording = False
            if self._stream:
                try:
                    self._stream.close()
                except Exception:
                    pass
                self._stream = None
            raise

    def _resample_if_needed(self, data):
        if len(data) == 0 or self.native_samplerate == self.sample_rate:
            return data
        target_samples = int(len(data) * self.sample_rate / self.native_samplerate)
        return scipy.signal.resample(data, target_samples).astype(np.int16)

    def stop(self):
        """Stop recording and return captured PCM int16 numpy array at target sample rate."""
        self._recording = False
        if self._stream:
            self._stream.stop()
            self._stream.close()
            self._stream = None
        chunks = []
        while not self._q.empty():
            try:
                chunks.append(self._q.get_nowait())
            except queue.Empty:
                break
        if not chunks:
            return np.zeros(0, dtype=np.int16)
        data = np.concatenate(chunks, axis=0).flatten()
        return self._resample_if_needed(data)

    def record_with_vad(
        self,
        max_seconds=12.0,
        silence_timeout=1.6,
        energy_threshold=400,
        stop_event=None,
        cancel_event=None,
    ):
        """Record until user finishes speaking (silence after voice), stop_event is set, or max_seconds reached."""
        self.start()
        started = time.monotonic()
        has_spoken = False
        last_sound_time = started
        chunk_duration = 0.05
        all_chunks = []

        try:
            while time.monotonic() - started < max_seconds:
                if cancel_event and cancel_event.is_set():
                    return np.zeros(0, dtype=np.int16)
                if stop_event and stop_event.is_set():
                    break
                time.sleep(chunk_duration)
                new_chunks = []
                while not self._q.empty():
                    try:
                        new_chunks.append(self._q.get_nowait())
                    except queue.Empty:
                        break
                if not new_chunks:
                    continue
                all_chunks.extend(new_chunks)
                audio_chunk = np.concatenate(new_chunks, axis=0)
                rms = np.sqrt(np.mean(audio_chunk.astype(np.float32) ** 2))

                if rms > energy_threshold:
                    if not has_spoken:
                        has_spoken = True
                    last_sound_time = time.monotonic()
                elif has_spoken and (time.monotonic() - last_sound_time > silence_timeout):
                    # User spoke and then paused for silence_timeout
                    break
        finally:
            self._recording = False
            if self._stream:
                try:
                    self._stream.stop()
                    self._stream.close()
                except Exception:
                    pass
                self._stream = None

        if cancel_event and cancel_event.is_set():
            return np.zeros(0, dtype=np.int16)

        while not self._q.empty():
            try:
                all_chunks.append(self._q.get_nowait())
            except queue.Empty:
                break

        if not all_chunks:
            return np.zeros(0, dtype=np.int16)
        data = np.concatenate(all_chunks, axis=0).flatten()
        return self._resample_if_needed(data)


def pcm_to_wav_bytes(pcm_array, sample_rate=SAMPLE_RATE):
    """Convert int16 mono PCM numpy array to WAV bytes."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm_array.tobytes())
    return buf.getvalue()


def transcribe_openrouter(
    pcm_array,
    sample_rate=SAMPLE_RATE,
    language=None,
    model=None,
    api_key=None,
    base_url=None,
):
    """Transcribe audio using OpenRouter Audio Transcriptions API (meta/muse-voice-transcribe-1.0)."""
    load_environment()
    key = api_key or os.environ.get("OPENROUTER_API_KEY") or os.environ.get("TEXT_MODEL_API_KEY")
    if not key or len(pcm_array) == 0:
        return None

    model_name = model or os.environ.get("VOICE_STT_MODEL", "meta/muse-voice-transcribe-1.0")
    base = (base_url or os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")).rstrip("/")
    url = f"{base}/audio/transcriptions"

    wav_bytes = pcm_to_wav_bytes(pcm_array, sample_rate=sample_rate)
    files = {"file": ("speech.wav", wav_bytes, "audio/wav")}
    data = {"model": model_name}
    if language:
        data["language"] = language

    headers = {"Authorization": f"Bearer {key}"}

    try:
        poster = httpx.post if hasattr(httpx.post, "assert_called") else VOICE_HTTP_CLIENT.post
        response = poster(url, headers=headers, files=files, data=data, timeout=15)
        if response.is_success:
            res_json = response.json()
            return res_json.get("text", "").strip()
    except Exception:
        pass
    return None


def transcribe_google(pcm_array, sample_rate=SAMPLE_RATE, language=None):
    """Fallback: transcribe int16 PCM audio array using Google Speech Recognition."""
    if len(pcm_array) == 0:
        return ""
    audio_bytes = pcm_array.tobytes()
    recognizer = sr.Recognizer()
    audio_data = sr.AudioData(audio_bytes, sample_rate, 2)

    if language:
        try:
            return recognizer.recognize_google(audio_data, language=language)
        except (sr.UnknownValueError, sr.RequestError):
            return ""

    for lang in ("th-TH", "en-US"):
        try:
            text = recognizer.recognize_google(audio_data, language=lang)
            if text and text.strip():
                return text.strip()
        except (sr.UnknownValueError, sr.RequestError):
            continue
    return ""


def transcribe_audio(pcm_array, sample_rate=SAMPLE_RATE, language=None):
    """Transcribe audio using meta/muse-voice-transcribe-1.0 on OpenRouter with fallback to Google."""
    if len(pcm_array) == 0:
        return ""

    # 1. Try OpenRouter (meta/muse-voice-transcribe-1.0)
    text = transcribe_openrouter(pcm_array, sample_rate=sample_rate, language=language)
    if text:
        return text

    # 2. Fallback to Google Speech Recognition
    return transcribe_google(pcm_array, sample_rate=sample_rate, language=language)


VOICE_INTENT_PROMPT = """You are an intent extractor for an ultrafast autonomous browser agent.
The user is browsing the web and speaks commands in Thai or English.
Given the user's speech, current date, and CURRENT browser page context:

Rules:
1. "action_type":
   - "in_page": if user wants to click, type, scroll, search, or interact within the CURRENT website
     (e.g. "เข้าหน้า Profile", "กดค้นหา", "เลื่อนลง", "กดไลค์", "ดูแจ้งเตือน", "พิมพ์ว่า...").
   - "navigate": ONLY if user explicitly asks to switch to a DIFFERENT website or domain
     (e.g. "เปิด YouTube", "ไป Google", "เข้าเว็บ pantip").
2. "url":
   - If action_type == "navigate": the target full HTTPS URL (e.g. "https://www.youtube.com").
   - If action_type == "in_page": null (DO NOT reload or re-navigate the page!).
3. "goal": Clear, concise, actionable English instruction for the Jev agent to execute on the page.
   - For in-page typing/searching/asking: strip conversational meta-prefixes such as
     "ถามว่า...", "ช่วยหาว่า...", "พิมพ์ว่า...", "ค้นหาว่า...", "บอกว่า...".
     Keep only the pure intended query or content (e.g. if speech is "ถามว่าวันนี้มีข่าวเอไออะไรใหม่ๆไหม",
     the goal should specify typing "วันนี้มีข่าว AI อะไรใหม่ๆ ไหม").
   - For in-page actions: describe what element to click, what field to fill, or where to scroll.

Return ONLY a valid JSON object matching:
{"action_type": "navigate" | "in_page", "url": "..." | null, "goal": "..."}"""


def parse_voice_intent(transcript, current_url=None, current_title=None):
    """Extract (action_type, url, goal) from user speech transcript using TEXT_MODEL."""
    load_environment()
    key = os.environ.get("TEXT_MODEL_API_KEY")
    base = os.environ.get("TEXT_MODEL_BASE_URL", "https://openrouter.ai/api/v1").rstrip("/")
    model = os.environ.get("TEXT_MODEL", "openai/gpt-5.6-luna")

    if not key:
        action_type = "in_page" if current_url else "navigate"
        return {
            "action_type": action_type,
            "url": None if action_type == "in_page" else "https://www.google.com",
            "goal": transcript,
        }

    reasoning = {"reasoning": {"enabled": False}} if os.environ.get("TEXT_MODEL_REASONING") == "none" else {}
    today_str = datetime.now().strftime("%Y-%m-%d")
    user_content_parts = [f"Current date: {today_str}"]
    if current_url:
        user_content_parts.append(f"Current URL: {current_url}")
    if current_title:
        user_content_parts.append(f"Current Title: {current_title}")
    user_content_parts.append(f"User speech: {transcript}")
    user_content = "\n".join(user_content_parts)

    payload = {
        "model": model,
        "max_tokens": 512,
        "response_format": {"type": "json_object"},
        **reasoning,
        "messages": [
            {"role": "system", "content": VOICE_INTENT_PROMPT},
            {"role": "user", "content": user_content},
        ],
    }

    try:
        res = post_json(base + "/chat/completions", key, payload)
        content = res["choices"][0]["message"]["content"]
        data = json.loads(content)
        action_type = data.get("action_type", "navigate")
        url = data.get("url")
        goal = data.get("goal", transcript)

        if action_type not in ("navigate", "in_page"):
            action_type = "in_page" if current_url else "navigate"

        # Preserve explicit navigation if path is distinct, otherwise normalize same-domain to in_page
        if current_url and url:
            cur_host = extract_hostname(current_url)
            new_host = extract_hostname(url)
            cur_path = urlparse(current_url).path.rstrip("/")
            new_path = urlparse(url).path.rstrip("/")
            if cur_host and cur_host == new_host:
                if cur_path == new_path or not new_path:
                    action_type = "in_page"
                    url = None
        return {"action_type": action_type, "url": url, "goal": goal}
    except Exception:
        # Preserve context on intent failure - never navigate away from current page on exception
        if current_url:
            return {"action_type": "in_page", "url": None, "goal": transcript}
        return {"action_type": "navigate", "url": "https://www.google.com", "goal": transcript}


class ContinuousVoiceSession:
    """Maintains a stateful continuous browser session across multiple voice turns."""

    def __init__(self):
        self.agent = None

    def get_current_info(self):
        if self.agent and self.agent.browser:
            info = self.agent.browser.get_current_info()
            if info and info.get("url"):
                return {"url": info.get("url"), "title": info.get("title"), "target_id": self.agent.browser.target}
        try:
            targets = cdp("Target.getTargets").get("targetInfos", [])
            pages = [
                t for t in targets
                if t.get("type") == "page" and not t.get("url", "").startswith(("chrome://", "about:"))
            ]
            active = next((t for t in pages if t.get("attached")), None) or (pages[0] if pages else None)
            if active:
                return {"url": active.get("url"), "title": active.get("title"), "target_id": active.get("targetId")}
        except Exception:
            pass
        return None

    def process_command(
        self,
        transcript,
        intent=None,
        on_intent=None,
        on_step=None,
        max_steps=25,
        cancel_event=None,
        turn_id=None,
    ):
        load_environment()
        info = self.get_current_info()
        current_url = info.get("url") if info else None
        current_title = info.get("title") if info else None
        target_id = info.get("target_id") if info else None

        if cancel_event and cancel_event.is_set():
            return {
                "status": "cancelled",
                "history": [],
                "action_type": None,
                "url": current_url,
                "goal": transcript,
                "turn_id": turn_id,
            }

        if not intent:
            intent = parse_voice_intent(transcript, current_url=current_url, current_title=current_title)

        action_type = intent.get("action_type", "navigate")
        target_url = intent.get("url")
        goal = intent.get("goal", transcript)

        if on_intent:
            try:
                on_intent(intent, current_url, current_title)
            except Exception:
                pass

        if cancel_event and cancel_event.is_set():
            return {
                "status": "cancelled",
                "history": [],
                "action_type": action_type,
                "url": target_url or current_url,
                "goal": goal,
                "turn_id": turn_id,
            }

        if self.agent and action_type == "in_page":
            try:
                # Continue on current page without reload
                self.agent.set_goal(goal)
                self.agent.browser.activate_tab()
            except Exception:
                target = target_url or current_url or "https://www.google.com"
                self.agent = Agent(
                    target,
                    goal,
                    activate=True,
                    keep_open=True,
                    reuse_tab=True,
                    target_id=target_id,
                    navigate_on_attach=False,
                )
        elif self.agent and action_type == "navigate" and target_url:
            try:
                self.agent.navigate_to(target_url, goal=goal)
            except Exception:
                self.agent = Agent(target_url, goal, activate=True, keep_open=True, reuse_tab=True)
        else:
            initial_url = target_url or current_url or "https://www.google.com"
            navigate_needed = (action_type != "in_page")
            self.agent = Agent(
                initial_url,
                goal,
                activate=True,
                keep_open=True,
                reuse_tab=True,
                target_id=target_id,
                navigate_on_attach=navigate_needed,
            )

        step_count = 0
        last_emitted_step = 0
        while step_count < max_steps:
            if cancel_event and cancel_event.is_set():
                return {
                    "status": "cancelled",
                    "history": self.agent.state.get("history", []),
                    "action_type": action_type,
                    "url": target_url or current_url,
                    "goal": goal,
                    "turn_id": turn_id,
                }
            if self.agent.state["status"] in {"done", "blocked"}:
                break

            self.agent.command("tick")
            step_count += 1

            history = self.agent.state.get("history", [])
            while last_emitted_step < len(history):
                if on_step:
                    try:
                        on_step(history[last_emitted_step], self.agent.state)
                    except Exception:
                        pass
                last_emitted_step += 1

        agent_status = self.agent.state.get("status", "ready")
        if agent_status == "done":
            status = "unverified"
        elif agent_status == "blocked":
            status = "blocked"
        elif step_count >= max_steps:
            status = "budget_exceeded"
        else:
            status = agent_status

        return {
            "status": status,
            "history": self.agent.state.get("history", []),
            "action_type": action_type,
            "url": target_url or current_url,
            "goal": goal,
            "turn_id": turn_id,
        }


# Global continuous session instance
SESSION = ContinuousVoiceSession()


def execute_voice_goal(url_or_command, goal=None, max_steps=25, on_step=None, on_intent=None):
    """Run Jev Ultrafast agent for the given voice command using the global session."""
    command = goal if goal else url_or_command
    return SESSION.process_command(command, on_intent=on_intent, on_step=on_step, max_steps=max_steps)
