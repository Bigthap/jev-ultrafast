"""Centralized VoiceController and State Machine for Jev Ultrafast."""

import logging
import queue
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from .demo import load_environment
from .voice import (
    SESSION,
    AudioRecorder,
    ContinuousVoiceSession,
    parse_voice_intent,
    transcribe_audio,
)

logger = logging.getLogger(__name__)


class ControllerState(str, Enum):
    IDLE = "idle"
    RECORDING = "recording"
    TRANSCRIBING = "transcribing"
    RESOLVING_INTENT = "resolving_intent"
    EXECUTING = "executing"
    VERIFYING = "verifying"
    SUCCEEDED = "succeeded"
    UNVERIFIED = "unverified"
    BLOCKED = "blocked"
    BUDGET_EXCEEDED = "budget_exceeded"
    CANCELLED = "cancelled"
    ERROR = "error"


@dataclass
class TurnContext:
    turn_id: int
    started_at: float = field(default_factory=time.monotonic)
    stop_event: threading.Event = field(default_factory=threading.Event)
    cancel_event: threading.Event = field(default_factory=threading.Event)
    user_text: Optional[str] = None
    transcript: Optional[str] = None
    intent: Optional[Dict[str, Any]] = None
    result: Optional[Dict[str, Any]] = None


class VoiceController:
    """Coordinates audio capture, STT, intent parsing, and agent execution on a single worker."""

    def __init__(
        self,
        session: Optional[ContinuousVoiceSession] = None,
        recorder: Optional[AudioRecorder] = None,
    ):
        self.session = session or SESSION
        self.recorder = recorder or AudioRecorder()

        self.state = ControllerState.IDLE
        self._lock = threading.RLock()
        self._work_queue: queue.Queue = queue.Queue()
        self._worker_thread: Optional[threading.Thread] = None
        self._running = True

        self._turn_counter = 0
        self.current_turn: Optional[TurnContext] = None

        # Callbacks
        self.listeners: List[Callable[[ControllerState, Optional[Dict[str, Any]]], None]] = []
        self.step_listeners: List[Callable[[Dict[str, Any], Dict[str, Any]], None]] = []

        self._start_worker()

    def _start_worker(self):
        self._worker_thread = threading.Thread(target=self._worker_loop, daemon=True)
        self._worker_thread.start()

    def add_state_listener(self, callback: Callable[[ControllerState, Optional[Dict[str, Any]]], None]):
        self.listeners.append(callback)

    def add_step_listener(self, callback: Callable[[Dict[str, Any], Dict[str, Any]], None]):
        self.step_listeners.append(callback)

    def _set_state(self, new_state: ControllerState, details: Optional[Dict[str, Any]] = None):
        with self._lock:
            self.state = new_state
        for listener in self.listeners:
            try:
                listener(new_state, details)
            except Exception as e:
                logger.warning(f"Error in state listener: {e}")

    def _emit_step(self, step: Dict[str, Any], agent_state: Dict[str, Any]):
        for listener in self.step_listeners:
            try:
                listener(step, agent_state)
            except Exception as e:
                logger.warning(f"Error in step listener: {e}")

    def start_recording(self) -> bool:
        """Start audio recording turn. Returns True if recording was started, False if busy."""
        with self._lock:
            if self.state not in (
                ControllerState.IDLE,
                ControllerState.SUCCEEDED,
                ControllerState.UNVERIFIED,
                ControllerState.BLOCKED,
                ControllerState.BUDGET_EXCEEDED,
                ControllerState.CANCELLED,
                ControllerState.ERROR,
            ):
                return False

            self._turn_counter += 1
            turn = TurnContext(turn_id=self._turn_counter)
            self.current_turn = turn

        self._set_state(ControllerState.RECORDING, {"turn_id": turn.turn_id})
        self._work_queue.put(("record_and_execute", turn))
        return True

    def finish_recording(self) -> bool:
        """User finished speaking: stop recording and proceed to transcription and execution."""
        with self._lock:
            if self.state == ControllerState.RECORDING and self.current_turn:
                self.current_turn.stop_event.set()
                return True
        return False

    def cancel_task(self) -> bool:
        """Abort the current turn immediately, halting recording, STT, or browser execution."""
        turn_id = None
        with self._lock:
            if self.current_turn:
                self.current_turn.cancel_event.set()
                self.current_turn.stop_event.set()
                turn_id = self.current_turn.turn_id
        if turn_id is not None:
            self._set_state(ControllerState.CANCELLED, {"turn_id": turn_id})
            return True
        return False

    def submit_text(self, text: str) -> bool:
        """Submit a typed natural language goal directly."""
        text = text.strip()
        if not text:
            return False

        with self._lock:
            if self.state not in (
                ControllerState.IDLE,
                ControllerState.SUCCEEDED,
                ControllerState.UNVERIFIED,
                ControllerState.BLOCKED,
                ControllerState.BUDGET_EXCEEDED,
                ControllerState.CANCELLED,
                ControllerState.ERROR,
            ):
                return False

            self._turn_counter += 1
            turn = TurnContext(turn_id=self._turn_counter, user_text=text)
            self.current_turn = turn

        self._set_state(ControllerState.RESOLVING_INTENT, {"turn_id": turn.turn_id, "text": text})
        self._work_queue.put(("execute_text", turn))
        return True

    def _worker_loop(self):
        while self._running:
            try:
                task = self._work_queue.get(timeout=0.2)
            except queue.Empty:
                continue

            action, turn = task
            if action is None or not self._running:
                self._work_queue.task_done()
                break
            try:
                if action == "record_and_execute":
                    self._handle_recording_turn(turn)
                elif action == "execute_text":
                    self._handle_text_turn(turn)
            except Exception as e:
                logger.exception(f"Unhandled error in voice worker: {e}")
                self._set_state(ControllerState.ERROR, {"turn_id": turn.turn_id, "error": str(e)})
            finally:
                self._work_queue.task_done()

    def _handle_recording_turn(self, turn: TurnContext):
        # 1. Record audio
        try:
            audio = self.recorder.record_with_vad(
                max_seconds=12.0,
                silence_timeout=1.6,
                stop_event=turn.stop_event,
                cancel_event=turn.cancel_event,
            )
        except Exception as e:
            self._set_state(ControllerState.ERROR, {"turn_id": turn.turn_id, "error": f"Mic error: {e}"})
            return

        if turn.cancel_event.is_set():
            self._set_state(ControllerState.CANCELLED, {"turn_id": turn.turn_id})
            return

        if len(audio) == 0:
            self._set_state(ControllerState.ERROR, {"turn_id": turn.turn_id, "error": "No audio captured"})
            return

        # 2. STT Transcription
        self._set_state(ControllerState.TRANSCRIBING, {"turn_id": turn.turn_id})
        t0 = time.monotonic()
        transcript = transcribe_audio(audio)
        stt_ms = round((time.monotonic() - t0) * 1000)

        if turn.cancel_event.is_set():
            self._set_state(ControllerState.CANCELLED, {"turn_id": turn.turn_id})
            return

        if not transcript:
            self._set_state(ControllerState.ERROR, {"turn_id": turn.turn_id, "error": "Could not recognize speech"})
            return

        turn.transcript = transcript
        self._set_state(
            ControllerState.RESOLVING_INTENT,
            {"turn_id": turn.turn_id, "transcript": transcript, "stt_ms": stt_ms},
        )

        # 3. Intent & Agent Execution
        self._execute_agent_flow(turn, transcript)

    def _handle_text_turn(self, turn: TurnContext):
        if turn.cancel_event.is_set():
            self._set_state(ControllerState.CANCELLED, {"turn_id": turn.turn_id})
            return
        self._execute_agent_flow(turn, turn.user_text)

    def _execute_agent_flow(self, turn: TurnContext, prompt_text: str):
        load_environment()
        if turn.cancel_event.is_set():
            self._set_state(ControllerState.CANCELLED, {"turn_id": turn.turn_id})
            return

        info = self.session.get_current_info()
        current_url = info.get("url") if info else None
        current_title = info.get("title") if info else None

        # Resolve intent
        try:
            intent = parse_voice_intent(prompt_text, current_url=current_url, current_title=current_title)
        except Exception:
            intent = {"action_type": "in_page" if current_url else "navigate", "url": current_url, "goal": prompt_text}

        turn.intent = intent
        if turn.cancel_event.is_set():
            self._set_state(ControllerState.CANCELLED, {"turn_id": turn.turn_id})
            return

        self._set_state(
            ControllerState.EXECUTING,
            {
                "turn_id": turn.turn_id,
                "intent": intent,
                "current_url": current_url,
                "current_title": current_title,
            },
        )

        # Execute in browser
        res = self.session.process_command(
            prompt_text,
            intent=intent,
            on_step=lambda step, state: self._emit_step(step, state),
            cancel_event=turn.cancel_event,
            turn_id=turn.turn_id,
        )

        turn.result = res
        status_str = res.get("status", "error").lower()

        if status_str == "succeeded":
            final_state = ControllerState.SUCCEEDED
        elif status_str == "unverified":
            final_state = ControllerState.UNVERIFIED
        elif status_str == "budget_exceeded":
            final_state = ControllerState.BUDGET_EXCEEDED
        elif status_str == "blocked":
            final_state = ControllerState.BLOCKED
        elif status_str == "cancelled":
            final_state = ControllerState.CANCELLED
        else:
            final_state = ControllerState.ERROR

        self._set_state(final_state, {"turn_id": turn.turn_id, "result": res})

    def shutdown(self, timeout=3.0):
        """Cleanly cancel pending turns and stop the controller worker."""
        self.cancel_task()
        self._running = False
        self._work_queue.put((None, None))
        if self.session and getattr(self.session, "agent", None):
            try:
                self.session.agent.close()
            except Exception:
                pass
        if self._worker_thread and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=timeout)
