"""High-speed Desktop Voice Assistant for Jev Ultrafast."""

import io
import json
import os
import queue
import time
import wave
from urllib.parse import urlparse

import httpx
import numpy as np
import scipy.signal
import sounddevice as sd
import speech_recognition as sr
from browser_harness.helpers import cdp

from .agent import Agent
from .demo import load_environment
from .model import post_json

SAMPLE_RATE = 16000
CHANNELS = 1
DTYPE = "int16"


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
            self._q.get_nowait()
        self._stream = sd.InputStream(
            samplerate=self.native_samplerate,
            channels=CHANNELS,
            dtype=DTYPE,
            callback=self._audio_callback,
        )
        self._stream.start()

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
            chunks.append(self._q.get_nowait())
        if not chunks:
            return np.zeros(0, dtype=np.int16)
        data = np.concatenate(chunks, axis=0).flatten()
        return self._resample_if_needed(data)

    def record_with_vad(self, max_seconds=12.0, silence_timeout=1.6, energy_threshold=400):
        """Record until user finishes speaking (silence after voice) or max_seconds reached."""
        self.start()
        started = time.time()
        has_spoken = False
        last_sound_time = started
        chunk_duration = 0.1
        all_chunks = []

        try:
            while time.time() - started < max_seconds:
                time.sleep(chunk_duration)
                new_chunks = []
                while not self._q.empty():
                    new_chunks.append(self._q.get_nowait())
                if not new_chunks:
                    continue
                all_chunks.extend(new_chunks)
                audio_chunk = np.concatenate(new_chunks, axis=0)
                rms = np.sqrt(np.mean(audio_chunk.astype(np.float32) ** 2))

                if rms > energy_threshold:
                    if not has_spoken:
                        has_spoken = True
                    last_sound_time = time.time()
                elif has_spoken and (time.time() - last_sound_time > silence_timeout):
                    # User spoke and then paused for silence_timeout
                    break
        finally:
            self._recording = False
            if self._stream:
                self._stream.stop()
                self._stream.close()
                self._stream = None

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
        response = httpx.post(url, headers=headers, files=files, data=data, timeout=15)
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
Given the user's speech and CURRENT browser page context:

Rules:
1. "action_type":
   - "in_page": if user wants to click, type, scroll, search, or navigate within the CURRENT website
     (e.g. "เข้าหน้า Profile", "กดค้นหา", "เลื่อนลง", "กดไลค์", "ดูแจ้งเตือน", "พิมพ์ว่า...").
   - "navigate": ONLY if user explicitly asks to switch to a DIFFERENT website or domain
     (e.g. "เปิด YouTube", "ไป Google Flights", "เข้าเว็บ pantip").
2. "url":
   - If action_type == "navigate": the new full HTTPS URL (e.g. "https://www.youtube.com").
   - If action_type == "in_page": null (DO NOT reload or re-navigate the page!).
3. "goal": Clear, concise, actionable English instruction for the Jev agent to execute on the page.
   - For in-page typing/searching/asking: strip conversational meta-prefixes such as
     "ถามว่า...", "ช่วยหาว่า...", "พิมพ์ว่า...", "ค้นหาว่า...", "บอกว่า...".
     Keep only the pure intended question or content (e.g. if speech is "ถามว่าวันนี้มีข่าวเอไออะไรใหม่ๆไหม",
     the goal should specify typing "วันนี้มีข่าว AI อะไรใหม่ๆ ไหม").
   - For in-page actions: describe what element to click, what field to fill, or where to scroll.
   - For flights: specify origin, destination, date (year 2026), and "Stop when flight options are visible."

Return ONLY a valid JSON object matching:
{"action_type": "navigate" | "in_page", "url": "..." | null, "goal": "..."}"""


def parse_voice_intent(transcript, current_url=None, current_title=None):
    """Extract (action_type, url, goal) from user speech transcript using TEXT_MODEL."""
    load_environment()
    key = os.environ.get("TEXT_MODEL_API_KEY")
    base = os.environ.get("TEXT_MODEL_BASE_URL", "https://openrouter.ai/api/v1").rstrip("/")
    model = os.environ.get("TEXT_MODEL", "openai/gpt-5.6-luna")

    if not key:
        is_flights = any(w in transcript.lower() for w in ["flight", "ตั๋ว", "เครื่องบิน"])
        action_type = "navigate" if is_flights or not current_url else "in_page"
        default_url = "https://www.google.com/travel/flights?hl=en" if is_flights else "https://www.google.com"
        return {
            "action_type": action_type,
            "url": default_url if action_type == "navigate" else None,
            "goal": transcript,
        }

    reasoning = {"reasoning": {"enabled": False}} if os.environ.get("TEXT_MODEL_REASONING") == "none" else {}
    user_content = f"User speech: {transcript}"
    if current_url:
        user_content = f"Current URL: {current_url}\nCurrent Title: {current_title or ''}\n" + user_content

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
        # If model returned navigate but same domain, normalize to in_page
        if current_url and url:
            if urlparse(current_url).netloc.lower() == urlparse(url).netloc.lower():
                action_type = "in_page"
                url = None
        return {"action_type": action_type, "url": url, "goal": goal}
    except Exception:
        is_flights = any(w in transcript.lower() for w in ["flight", "ตั๋ว", "เครื่องบิน", "flights"])
        default_url = "https://www.google.com/travel/flights?hl=en" if is_flights else "https://www.google.com"
        return {"action_type": "navigate", "url": default_url, "goal": transcript}


class ContinuousVoiceSession:
    """Maintains a stateful continuous browser session across multiple voice turns."""

    def __init__(self):
        self.agent = None

    def get_current_info(self):
        if self.agent and self.agent.browser:
            info = self.agent.browser.get_current_info()
            if info and info.get("url"):
                return info
        try:
            targets = cdp("Target.getTargets").get("targetInfos", [])
            pages = [
                t for t in targets
                if t.get("type") == "page" and not t.get("url", "").startswith(("chrome://", "about:"))
            ]
            if pages:
                return {"url": pages[0].get("url"), "title": pages[0].get("title")}
        except Exception:
            pass
        return None

    def process_command(self, transcript, on_intent=None, on_step=None, max_steps=25):
        load_environment()
        info = self.get_current_info()
        current_url = info.get("url") if info else None
        current_title = info.get("title") if info else None

        intent = parse_voice_intent(transcript, current_url=current_url, current_title=current_title)
        action_type = intent.get("action_type", "navigate")
        target_url = intent.get("url")
        goal = intent.get("goal", transcript)

        if on_intent:
            try:
                on_intent(intent, current_url, current_title)
            except Exception:
                pass

        if self.agent and action_type == "in_page":
            try:
                # Continue on current page without reload
                self.agent.set_goal(goal)
                self.agent.browser.activate_tab()
            except Exception:
                target = target_url or current_url or "https://www.google.com"
                self.agent = Agent(target, goal, activate=True, keep_open=True, reuse_tab=True)
        elif self.agent and action_type == "navigate" and target_url:
            try:
                self.agent.navigate_to(target_url, goal=goal)
            except Exception:
                self.agent = Agent(target_url, goal, activate=True, keep_open=True, reuse_tab=True)
        else:
            initial_url = target_url or current_url or "https://www.google.com"
            self.agent = Agent(initial_url, goal, activate=True, keep_open=True, reuse_tab=True)

        step_count = 0
        while self.agent.state["status"] not in {"done", "blocked"} and step_count < max_steps:
            self.agent.command("tick")
            step_count += 1
            if self.agent.state["history"] and on_step:
                last_step = self.agent.state["history"][-1]
                on_step(last_step, self.agent.state)

        return {
            "status": self.agent.state["status"],
            "history": self.agent.state["history"],
            "action_type": action_type,
            "url": target_url or current_url,
            "goal": goal,
        }


# Global continuous session instance
SESSION = ContinuousVoiceSession()


def execute_voice_goal(url_or_command, goal=None, max_steps=25, on_step=None, on_intent=None):
    """Run Jev Ultrafast agent for the given voice command using the global session."""
    command = goal if goal else url_or_command
    return SESSION.process_command(command, on_intent=on_intent, on_step=on_step, max_steps=max_steps)
