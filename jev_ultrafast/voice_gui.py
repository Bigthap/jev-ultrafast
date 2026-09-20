"""Floating Always-on-Top Desktop Voice Assistant GUI for Jev Ultrafast."""

import threading
import time
import tkinter as tk
from tkinter import ttk

from .demo import load_environment
from .voice import SESSION, AudioRecorder, transcribe_audio


class VoiceApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Jev Ultrafast ⚡ Voice Assistant")
        self.root.geometry("450x520")
        self.root.minsize(380, 420)
        self.root.attributes("-topmost", True)
        self.root.configure(bg="#18181b")

        self.session = SESSION
        self.recorder = AudioRecorder()
        self.is_recording = False
        self.is_busy = False
        self._stop_event = threading.Event()

        self._build_ui()

    def _build_ui(self):
        # Header Frame
        header = tk.Frame(self.root, bg="#27272a", height=44)
        header.pack(fill=tk.X, side=tk.TOP)

        title_lbl = tk.Label(
            header,
            text="⚡ JEV ULTRAFAST",
            font=("Segoe UI", 11, "bold"),
            fg="#67e8f9",
            bg="#27272a",
        )
        title_lbl.pack(side=tk.LEFT, padx=14, pady=10)

        pin_lbl = tk.Label(
            header,
            text="📌 ALWAYS ON TOP",
            font=("Segoe UI", 8, "bold"),
            fg="#a1a1aa",
            bg="#27272a",
        )
        pin_lbl.pack(side=tk.RIGHT, padx=14, pady=10)

        # Main Content Frame
        content = tk.Frame(self.root, bg="#18181b")
        content.pack(fill=tk.BOTH, expand=True, padx=16, pady=12)

        # Big Mic Button
        self.mic_btn = tk.Button(
            content,
            text="🎙️  Click to Speak (กดเพื่อพูด)",
            font=("Segoe UI", 12, "bold"),
            bg="#10b981",
            fg="#ffffff",
            activebackground="#059669",
            activeforeground="#ffffff",
            relief=tk.FLAT,
            cursor="hand2",
            padx=16,
            pady=12,
            command=self.toggle_mic,
        )
        self.mic_btn.pack(fill=tk.X, pady=(0, 10))

        # Status Pill
        status_frame = tk.Frame(content, bg="#18181b")
        status_frame.pack(fill=tk.X, pady=(0, 10))

        self.status_dot = tk.Label(status_frame, text="●", font=("Segoe UI", 12), fg="#10b981", bg="#18181b")
        self.status_dot.pack(side=tk.LEFT, padx=(2, 6))

        self.status_lbl = tk.Label(
            status_frame,
            text="Ready — Click microphone to speak",
            font=("Segoe UI", 9),
            fg="#a1a1aa",
            bg="#18181b",
        )
        self.status_lbl.pack(side=tk.LEFT)

        # Speech Card
        tk.Label(
            content,
            text="สิ่งที่พูด (Speech Transcription):",
            font=("Segoe UI", 9, "bold"),
            fg="#d4d4d8",
            bg="#18181b",
        ).pack(anchor=tk.W, pady=(4, 2))

        self.speech_text = tk.Text(
            content,
            height=2,
            font=("Segoe UI", 9),
            bg="#27272a",
            fg="#f4f4f5",
            insertbackground="#ffffff",
            relief=tk.FLAT,
            padx=8,
            pady=6,
            wrap=tk.WORD,
        )
        self.speech_text.pack(fill=tk.X, pady=(0, 8))
        self.speech_text.insert(tk.END, "ยังไม่มีคำสั่งเสียง...")
        self.speech_text.config(state=tk.DISABLED)

        # Target Goal Card
        tk.Label(
            content,
            text="เป้าหมาย & URL (Parsed Intent):",
            font=("Segoe UI", 9, "bold"),
            fg="#d4d4d8",
            bg="#18181b",
        ).pack(anchor=tk.W, pady=(4, 2))

        self.goal_text = tk.Text(
            content,
            height=2,
            font=("Segoe UI", 9),
            bg="#27272a",
            fg="#93c5fd",
            insertbackground="#ffffff",
            relief=tk.FLAT,
            padx=8,
            pady=6,
            wrap=tk.WORD,
        )
        self.goal_text.pack(fill=tk.X, pady=(0, 8))
        self.goal_text.insert(tk.END, "รอคำสั่ง...")
        self.goal_text.config(state=tk.DISABLED)

        # Live Action Log
        tk.Label(
            content,
            text="ความคืบหน้าเบราว์เซอร์ (Live Action Log):",
            font=("Segoe UI", 9, "bold"),
            fg="#d4d4d8",
            bg="#18181b",
        ).pack(anchor=tk.W, pady=(4, 2))

        log_frame = tk.Frame(content, bg="#27272a")
        log_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 8))

        self.log_list = tk.Listbox(
            log_frame,
            font=("Consolas", 9),
            bg="#27272a",
            fg="#e4e4e7",
            selectbackground="#3f3f46",
            relief=tk.FLAT,
            bd=0,
            highlightthickness=0,
        )
        scrollbar = ttk.Scrollbar(log_frame, orient=tk.VERTICAL, command=self.log_list.yview)
        self.log_list.configure(yscrollcommand=scrollbar.set)
        self.log_list.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=6, pady=6)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # Text Input Fallback
        input_frame = tk.Frame(content, bg="#18181b")
        input_frame.pack(fill=tk.X, side=tk.BOTTOM)

        self.entry = tk.Entry(
            input_frame,
            font=("Segoe UI", 9),
            bg="#27272a",
            fg="#ffffff",
            insertbackground="#ffffff",
            relief=tk.FLAT,
            bd=5,
        )
        self.entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 6))
        self.entry.bind("<Return>", lambda e: self.send_text_goal())

        send_btn = tk.Button(
            input_frame,
            text="Send ↵",
            font=("Segoe UI", 9, "bold"),
            bg="#6366f1",
            fg="#ffffff",
            activebackground="#4f46e5",
            activeforeground="#ffffff",
            relief=tk.FLAT,
            cursor="hand2",
            padx=12,
            pady=4,
            command=self.send_text_goal,
        )
        send_btn.pack(side=tk.RIGHT)

    def set_status(self, text, color="#10b981"):
        self.status_lbl.config(text=text)
        self.status_dot.config(fg=color)

    def set_speech(self, text):
        self.speech_text.config(state=tk.NORMAL)
        self.speech_text.delete("1.0", tk.END)
        self.speech_text.insert(tk.END, text)
        self.speech_text.config(state=tk.DISABLED)

    def set_goal(self, text):
        self.goal_text.config(state=tk.NORMAL)
        self.goal_text.delete("1.0", tk.END)
        self.goal_text.insert(tk.END, text)
        self.goal_text.config(state=tk.DISABLED)

    def add_log(self, message):
        self.log_list.insert(tk.END, message)
        self.log_list.see(tk.END)

    def toggle_mic(self):
        if self.is_busy:
            return

        if not self.is_recording:
            # Start recording
            self.is_recording = True
            self.mic_btn.config(
                text="⏹️  Recording... (Click to Finish)",
                bg="#ef4444",
                activebackground="#dc2626",
            )
            self.set_status("Listening... Speak now", "#ef4444")
            self._stop_event.clear()
            threading.Thread(target=self._record_worker, daemon=True).start()
        else:
            # Stop recording
            self.is_recording = False
            self.mic_btn.config(
                text="🧠  Processing...",
                bg="#f59e0b",
                activebackground="#d97706",
            )
            self.set_status("Stopping and processing speech...", "#f59e0b")
            self._stop_event.set()

    def _record_worker(self):
        audio = self.recorder.record_with_vad(max_seconds=12.0, silence_timeout=1.6)

        def on_done():
            self.mic_btn.config(
                text="🎙️  Click to Speak (กดเพื่อพูด)",
                bg="#10b981",
                activebackground="#059669",
            )
            self.is_recording = False

        self.root.after(0, on_done)

        if len(audio) == 0:
            self.root.after(0, lambda: self.set_status("No audio captured. Try again.", "#ef4444"))
            return

        self.root.after(0, lambda: self.set_status("Transcribing speech...", "#f59e0b"))
        t0 = time.perf_counter()
        transcript = transcribe_audio(audio)
        stt_ms = round((time.perf_counter() - t0) * 1000)

        if not transcript:
            self.root.after(0, lambda: self.set_status("Could not recognize speech.", "#ef4444"))
            self.root.after(0, lambda: self.set_speech("(No speech recognized)"))
            return

        self.root.after(0, lambda: self.set_speech(f"{transcript} ({stt_ms}ms)"))
        self._process_command(transcript)

    def send_text_goal(self):
        text = self.entry.get().strip()
        if not text or self.is_busy:
            return
        self.entry.delete(0, tk.END)
        self.set_speech(f"(Typed): {text}")
        threading.Thread(target=self._process_command, args=(text,), daemon=True).start()

    def _process_command(self, user_text):
        self.is_busy = True
        self.root.after(0, lambda: self.set_status("Analyzing intent & active tab...", "#8b5cf6"))

        try:
            def on_intent(intent, current_url, current_title):
                action_type = intent.get("action_type", "navigate")
                target_url = intent.get("url")
                goal = intent.get("goal", user_text)

                if action_type == "in_page":
                    badge = "[⚡ IN-PAGE]"
                    page_desc = f"Active Tab: {current_url or 'Current Page'}"
                else:
                    badge = "[🌐 NAVIGATE]"
                    page_desc = f"URL: {target_url}"

                self.root.after(0, lambda: self.set_goal(f"{badge} {page_desc}\nGoal: {goal}"))
                self.root.after(0, lambda: self.set_status(f"{badge} Executing on Chrome...", "#3b82f6"))
                self.root.after(0, lambda: self.add_log(f"🎯 {badge} {goal}"))

            def on_step(step, state):
                action = step.get("action", "")
                kind = step.get("kind", "").upper()
                prob = step.get("probability", 0.0)
                text = step.get("text")
                text_info = f" -> \"{text}\"" if text else ""
                log_line = f"⚡ [{kind}] {action}{text_info} (p={prob:.2f})"
                self.root.after(0, lambda: self.add_log(log_line))

            t0 = time.perf_counter()
            snapshot = self.session.process_command(
                user_text,
                on_intent=on_intent,
                on_step=on_step,
            )
            exec_sec = round(time.perf_counter() - t0, 1)

            status = snapshot.get("status", "done").upper()
            total_steps = len(snapshot.get("history", []))

            self.root.after(0, lambda: self.add_log(f"✅ Finished: {status} in {exec_sec}s ({total_steps} steps)"))
            self.root.after(0, lambda: self.set_status(f"Done! ({status}) — Click mic to speak again", "#10b981"))

        except Exception as e:
            err_msg = str(e)
            if "remote-debugging" in err_msg or "DevToolsActivePort" in err_msg or "didn't come up" in err_msg:
                self.root.after(0, lambda: self.add_log("⚠️ Chrome remote debugging not allowed!"))
                self.root.after(0, lambda: self.add_log("👉 Open chrome://inspect/#remote-debugging in Chrome"))
                self.root.after(0, lambda: self.set_status("Chrome not connected. See log.", "#ef4444"))
            else:
                self.root.after(0, lambda: self.add_log(f"❌ Error: {err_msg[:60]}..."))
                self.root.after(0, lambda: self.set_status(f"Error: {err_msg[:30]}", "#ef4444"))
        finally:
            self.is_busy = False


def main():
    load_environment()
    root = tk.Tk()
    VoiceApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
