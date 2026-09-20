"""Global Hotkey Listener for Jev Ultrafast Desktop Voice Assistant."""

import argparse
import threading
import time

from pynput import keyboard

from .demo import load_environment
from .voice import AudioRecorder, execute_voice_goal, transcribe_audio

DEFAULT_HOTKEY = "<ctrl>+<shift>+<space>"


class VoiceAssistant:
    def __init__(self, hotkey=DEFAULT_HOTKEY, language=None):
        self.hotkey = hotkey
        self.language = language
        self.recorder = AudioRecorder()
        self.is_recording = False
        self.is_busy = False
        self.lock = threading.Lock()
        self._stop_event = threading.Event()

    def on_hotkey_pressed(self):
        """Called whenever the global hotkey is pressed."""
        with self.lock:
            if self.is_busy:
                print("\n⚠️  [BUSY] Still executing previous task. Please wait...", flush=True)
                return

            if not self.is_recording:
                # Start recording
                self.is_recording = True
                threading.Thread(target=self._record_and_process, daemon=True).start()
            else:
                # User pressed hotkey to manually stop
                self.is_recording = False
                self._stop_event.set()

    def _record_and_process(self):
        self._stop_event.clear()
        print("\n" + "=" * 60, flush=True)
        print("🎙️  [LISTENING] Speak your command now...", flush=True)
        print("    (Will auto-stop after 1.5s silence, or press hotkey again)", flush=True)
        print("=" * 60, flush=True)

        # Record with VAD
        audio = self.recorder.record_with_vad(max_seconds=12.0, silence_timeout=1.6)
        self.is_recording = False

        if len(audio) == 0:
            print("❌  [AUDIO] No audio captured. Please try speaking again.", flush=True)
            return

        with self.lock:
            self.is_busy = True

        try:
            print("\n🧠  [TRANSCRIBING] Converting speech to text...", flush=True)
            t0 = time.perf_counter()
            transcript = transcribe_audio(audio, language=self.language)
            stt_ms = round((time.perf_counter() - t0) * 1000)

            if not transcript:
                print("❌  [STT] Could not understand speech. Please speak clearly into the mic.", flush=True)
                return

            print(f"🗣️   User said ({stt_ms}ms): \"{transcript}\"", flush=True)

            def on_intent(intent, current_url, current_title):
                atype = intent.get("action_type", "navigate").upper()
                url = intent.get("url")
                goal = intent.get("goal", transcript)
                if atype == "IN_PAGE":
                    print(f"⚡  Mode: [IN-PAGE ACTION] on {current_url or 'current tab'}", flush=True)
                else:
                    print(f"🌐  Mode: [NAVIGATE] Target URL: {url}", flush=True)
                print(f"🎯  Agent Goal: {goal}", flush=True)
                print("\n🚀  [EXECUTING] Launching Jev Ultrafast on Chrome...", flush=True)

            def on_step(step, state):
                action = step.get("action", "")
                kind = step.get("kind", "")
                prob = step.get("probability", 0.0)
                conf = step.get("confidence", 0.0)
                text = step.get("text")
                text_info = f" -> \"{text}\"" if text else ""
                print(f"  ⚡ [{kind.upper()}] {action}{text_info} (p={prob:.2f}, conf={conf:.2f})", flush=True)

            t2 = time.perf_counter()
            snapshot = execute_voice_goal(transcript, on_intent=on_intent, on_step=on_step)
            exec_sec = round(time.perf_counter() - t2, 1)

            status = snapshot.get("status", "unknown").upper()
            total_steps = len(snapshot.get("history", []))
            print("\n" + "-" * 60, flush=True)
            print(f"✅  [FINISHED] Status: {status} | Steps: {total_steps} | Execution: {exec_sec}s", flush=True)
            print("-" * 60 + "\n", flush=True)

        except RuntimeError as e:
            msg = str(e)
            if "remote-debugging" in msg or "DevToolsActivePort" in msg or "didn't come up" in msg:
                print("\n⚠️  [CHROME NOT CONNECTED]", flush=True)
                print("   Please enable Remote Debugging in Google Chrome:")
                print("   1. Open Chrome and navigate to: chrome://inspect/#remote-debugging")
                print("   2. Check 'Allow remote debugging for this browser instance'")
                print("   3. Click 'Allow' on Chrome's popup prompt\n", flush=True)
            else:
                print(f"\n❌  [ERROR] {e}", flush=True)
        except Exception as e:
            print(f"\n❌  [UNEXPECTED ERROR] {e}", flush=True)
        finally:
            with self.lock:
                self.is_busy = False
            print(f"🎙️  Ready for next command! Press [{self.hotkey}] to speak.\n", flush=True)

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
        self._record_and_process()

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
