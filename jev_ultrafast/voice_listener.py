"""Global Hotkey Listener for Jev Ultrafast Desktop Voice Assistant."""

import argparse
import time

from pynput import keyboard

from .demo import load_environment
from .voice import transcribe_audio
from .voice_controller import ControllerState, VoiceController

DEFAULT_HOTKEY = "<ctrl>+<shift>+<space>"


class VoiceAssistant:
    def __init__(self, hotkey=DEFAULT_HOTKEY, language=None):
        self.hotkey = hotkey
        self.language = language
        self.controller = VoiceController()
        self.controller.add_state_listener(self._on_state_change)
        self.controller.add_step_listener(self._on_step)
        self.recorder = self.controller.recorder

    def on_hotkey_pressed(self):
        """Called whenever the global hotkey is pressed."""
        if self.controller.state == ControllerState.RECORDING:
            print("\n⏹️  [FINISHING] Stopping recording and processing...", flush=True)
            self.controller.finish_recording()
        else:
            started = self.controller.start_recording()
            if not started:
                print("\n⚠️  [BUSY] Still executing previous task. Please wait...", flush=True)

    def _on_state_change(self, state: ControllerState, details=None):
        details = details or {}
        if state == ControllerState.RECORDING:
            print("\n" + "=" * 60, flush=True)
            print("🎙️  [LISTENING] Speak your command now...", flush=True)
            print(f"    (Press [{self.hotkey}] again to finish recording)", flush=True)
            print("=" * 60, flush=True)
        elif state == ControllerState.TRANSCRIBING:
            print("\n🧠  [TRANSCRIBING] Converting speech to text...", flush=True)
        elif state == ControllerState.RESOLVING_INTENT:
            transcript = details.get("transcript")
            stt_ms = details.get("stt_ms")
            ms_info = f" ({stt_ms}ms)" if stt_ms else ""
            if transcript:
                print(f"🗣️   User said{ms_info}: \"{transcript}\"", flush=True)
        elif state == ControllerState.EXECUTING:
            intent = details.get("intent", {})
            atype = intent.get("action_type", "navigate").upper()
            url = intent.get("url")
            goal = intent.get("goal", "")
            curr_url = details.get("current_url")
            if atype == "IN_PAGE":
                print(f"⚡  Mode: [IN-PAGE ACTION] on {curr_url or 'current tab'}", flush=True)
            else:
                print(f"🌐  Mode: [NAVIGATE] Target URL: {url}", flush=True)
            print(f"🎯  Agent Goal: {goal}", flush=True)
            print("\n🚀  [EXECUTING] Launching Jev Ultrafast on Chrome...", flush=True)
        elif state in (
            ControllerState.SUCCEEDED,
            ControllerState.UNVERIFIED,
            ControllerState.BUDGET_EXCEEDED,
            ControllerState.BLOCKED,
            ControllerState.CANCELLED,
            ControllerState.ERROR,
        ):
            res = details.get("result", {})
            history = res.get("history", [])
            steps = len(history)
            status_text = state.value.upper()
            print("\n" + "-" * 60, flush=True)
            print(f"✅  [COMPLETED] Status: {status_text} | Steps: {steps}", flush=True)
            print("-" * 60 + "\n", flush=True)
            print(f"🎙️  Ready for next command! Press [{self.hotkey}] to speak.\n", flush=True)

    def _on_step(self, step, state):
        action = step.get("action", "")
        kind = step.get("kind", "")
        prob = step.get("probability", 0.0)
        conf = step.get("confidence", 0.0)
        text = step.get("text")
        text_info = f" -> \"{text}\"" if text else ""
        print(f"  ⚡ [{kind.upper()}] {action}{text_info} (p={prob:.2f}, conf={conf:.2f})", flush=True)

    def test_microphone(self):
        """Quick 3-second recording test to check microphone levels."""
        print("\n🎤  Testing microphone... Speak now for 3 seconds!", flush=True)
        self.recorder.start()
        for i in range(3, 0, -1):
            print(f"   Recording... {i}s", flush=True)
            time.sleep(1)
        audio = self.recorder.stop()
        if len(audio) == 0:
            print("❌  Failed: No audio captured. Check Windows microphone permissions.", flush=True)
            return
        peak = max(abs(audio.min()), abs(audio.max()))
        print(f"✅  Captured {len(audio)} samples (~{len(audio)/16000:.1f}s), Peak amplitude: {peak}/32767", flush=True)
        print("🧠  Transcribing test speech...", flush=True)
        text = transcribe_audio(audio, language=self.language)
        if text:
            print(f"✅  Speech recognized: \"{text}\"", flush=True)
        else:
            print("ℹ️   No speech recognized (or voice was too quiet). Try speaking closer to the mic.", flush=True)

    def run_direct(self):
        """Run a single voice command directly from terminal without hotkey."""
        self.controller.start_recording()
        while self.controller.state not in (
            ControllerState.IDLE,
            ControllerState.SUCCEEDED,
            ControllerState.UNVERIFIED,
            ControllerState.BUDGET_EXCEEDED,
            ControllerState.BLOCKED,
            ControllerState.CANCELLED,
            ControllerState.ERROR,
        ):
            time.sleep(0.1)

    def listen_forever(self):
        """Listen for global hotkey and process commands."""
        print("=" * 65)
        print("   ⚡ Jev Ultrafast — Desktop Global Voice Assistant ⚡")
        print("=" * 65)
        print(f"🎙️   Global Hotkey : [ {self.hotkey} ]")
        print("🌐   Chrome Target : Dynamic (auto-detected from speech)")
        print("💡   Tip: Press the hotkey from ANY app/screen to speak.")
        print("❌   Press Ctrl+C in this terminal to exit.")
        print("=" * 65 + "\n")
        print(f"Ready! Press [{self.hotkey}] to start speaking...", flush=True)

        hotkey_dict = {self.hotkey: self.on_hotkey_pressed}
        with keyboard.GlobalHotKeys(hotkey_dict) as h:
            h.join()


def main():
    load_environment()
    parser = argparse.ArgumentParser(description="Jev Ultrafast Desktop Voice Assistant")
    parser.add_argument(
        "--hotkey",
        default=DEFAULT_HOTKEY,
        help=f"Global hotkey combination (default: {DEFAULT_HOTKEY})",
    )
    parser.add_argument(
        "--lang",
        default=None,
        help="Speech recognition language code (e.g. 'th-TH', 'en-US', default: auto-detect)",
    )
    parser.add_argument(
        "--test-mic",
        action="store_true",
        help="Test microphone recording and exit",
    )
    parser.add_argument(
        "--gui",
        action="store_true",
        help="Launch the Always-on-Top Floating GUI App",
    )
    parser.add_argument(
        "--direct",
        action="store_true",
        help="Record a command immediately without waiting for hotkey",
    )
    args = parser.parse_args()

    if args.gui:
        from .voice_gui import main as gui_main

        gui_main()
        return

    assistant = VoiceAssistant(hotkey=args.hotkey, language=args.lang)

    if args.test_mic:
        assistant.test_microphone()
        return

    if args.direct:
        assistant.run_direct()
        return

    try:
        assistant.listen_forever()
    except KeyboardInterrupt:
        print("\nExiting Voice Assistant. Goodbye!")


if __name__ == "__main__":
    main()
