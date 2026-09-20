"""Floating Always-on-Top Desktop Voice Assistant GUI for Jev Ultrafast."""

import tkinter as tk
from tkinter import ttk

from .demo import load_environment
from .voice_controller import ControllerState, VoiceController


class VoiceApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Jev Ultrafast ⚡ Voice Assistant")
        self.root.geometry("450x550")
        self.root.minsize(380, 450)
        self.root.attributes("-topmost", True)
        self.root.configure(bg="#18181b")

        self.controller = VoiceController()
        self.controller.add_state_listener(self._on_controller_state)
        self.controller.add_step_listener(self._on_step)

        self._build_ui()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

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

        # Action Buttons Frame (Mic + Cancel)
        btn_frame = tk.Frame(content, bg="#18181b")
        btn_frame.pack(fill=tk.X, pady=(0, 10))

        self.mic_btn = tk.Button(
            btn_frame,
            text="🎙️  Click to Speak (กดเพื่อพูด)",
            font=("Segoe UI", 11, "bold"),
            bg="#10b981",
            fg="#ffffff",
            activebackground="#059669",
            activeforeground="#ffffff",
            relief=tk.FLAT,
            cursor="hand2",
            padx=12,
            pady=10,
            command=self.on_mic_click,
        )
        self.mic_btn.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 6))

        self.cancel_btn = tk.Button(
            btn_frame,
            text="❌ Cancel",
            font=("Segoe UI", 10, "bold"),
            bg="#3f3f46",
            fg="#d4d4d8",
            activebackground="#ef4444",
            activeforeground="#ffffff",
            relief=tk.FLAT,
            cursor="hand2",
            padx=12,
            pady=10,
            command=self.on_cancel_click,
        )
        self.cancel_btn.pack(side=tk.RIGHT)

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

    def on_mic_click(self):
        if self.controller.state == ControllerState.RECORDING:
            self.controller.finish_recording()
        else:
            started = self.controller.start_recording()
            if not started:
                self.set_status("Controller is busy. Please wait.", "#f59e0b")

    def on_cancel_click(self):
        cancelled = self.controller.cancel_task()
        if cancelled:
            self.add_log("🛑 Task cancelled by user.")

    def send_text_goal(self):
        text = self.entry.get().strip()
        if not text:
            return
        if self.controller.state not in (
            ControllerState.IDLE,
            ControllerState.SUCCEEDED,
            ControllerState.UNVERIFIED,
            ControllerState.BLOCKED,
            ControllerState.BUDGET_EXCEEDED,
            ControllerState.CANCELLED,
            ControllerState.ERROR,
        ):
            self.set_status("System is busy with another task.", "#f59e0b")
            return
        self.entry.delete(0, tk.END)
        self.set_speech(f"(Typed): {text}")
        self.controller.submit_text(text)

    def _on_controller_state(self, state: ControllerState, details=None):
        def update():
            details_dict = details or {}
            if state == ControllerState.RECORDING:
                self.mic_btn.config(
                    text="⏹️  Finish Recording (เสร็จสิ้น)",
                    bg="#ef4444",
                    activebackground="#dc2626",
                    state=tk.NORMAL,
                )
                self.cancel_btn.config(bg="#ef4444", fg="#ffffff")
                self.set_status("Listening... Click Finish or speak", "#ef4444")
            elif state == ControllerState.TRANSCRIBING:
                self.mic_btn.config(
                    text="🧠  Transcribing...",
                    bg="#f59e0b",
                    activebackground="#d97706",
                    state=tk.DISABLED,
                )
                self.set_status("Transcribing speech with Meta Muse...", "#f59e0b")
            elif state == ControllerState.RESOLVING_INTENT:
                transcript = details_dict.get("transcript")
                stt_ms = details_dict.get("stt_ms")
                if transcript:
                    ms_info = f" ({stt_ms}ms)" if stt_ms else ""
                    self.set_speech(f"{transcript}{ms_info}")
                self.set_status("Analyzing intent & active tab...", "#8b5cf6")
            elif state == ControllerState.EXECUTING:
                intent = details_dict.get("intent", {})
                atype = intent.get("action_type", "navigate")
                url = intent.get("url")
                goal = intent.get("goal", "")
                curr_url = details_dict.get("current_url")
                badge = "[⚡ IN-PAGE]" if atype == "in_page" else "[🌐 NAVIGATE]"
                tab_desc = f"Active Tab: {curr_url or 'Current Page'}" if atype == "in_page" else f"URL: {url}"
                self.set_goal(f"{badge} {tab_desc}\nGoal: {goal}")
                self.set_status(f"{badge} Executing on Chrome...", "#3b82f6")
                self.add_log(f"🎯 {badge} {goal}")
            elif state == ControllerState.SUCCEEDED:
                res = details_dict.get("result", {})
                steps = len(res.get("history", []))
                self.add_log(f"✅ Succeeded (Verified, {steps} steps)")
                self.set_status("Completed (Verified)! Click mic to speak", "#10b981")
                self._reset_buttons()
            elif state == ControllerState.UNVERIFIED:
                res = details_dict.get("result", {})
                steps = len(res.get("history", []))
                self.add_log(f"⚠️ Done (Unverified postcondition, {steps} steps)")
                self.set_status("Done (Unverified) — Click mic to speak", "#f59e0b")
                self._reset_buttons()
            elif state == ControllerState.BUDGET_EXCEEDED:
                res = details_dict.get("result", {})
                steps = len(res.get("history", []))
                self.add_log(f"⏳ Stopped: Budget exceeded ({steps} steps)")
                self.set_status("Stopped (Step budget reached)", "#f59e0b")
                self._reset_buttons()
            elif state == ControllerState.BLOCKED:
                self.add_log("🚫 Blocked: No actionable elements")
                self.set_status("Agent blocked — Try another command", "#ef4444")
                self._reset_buttons()
            elif state == ControllerState.CANCELLED:
                self.add_log("🛑 Turn cancelled.")
                self.set_status("Cancelled — Ready", "#a1a1aa")
                self._reset_buttons()
            elif state == ControllerState.ERROR:
                err = details_dict.get("error", "Unknown error")
                self.add_log(f"❌ Error: {err}")
                self.set_status(f"Error: {err[:35]}", "#ef4444")
                self._reset_buttons()

        self.root.after(0, update)

    def _reset_buttons(self):
        self.mic_btn.config(
            text="🎙️  Click to Speak (กดเพื่อพูด)",
            bg="#10b981",
            activebackground="#059669",
            state=tk.NORMAL,
        )
        self.cancel_btn.config(bg="#3f3f46", fg="#d4d4d8")

    def _on_step(self, step, state):
        def update():
            action = step.get("action", "")
            kind = step.get("kind", "").upper()
            prob = step.get("probability", 0.0)
            text = step.get("text")
            text_info = f" -> \"{text}\"" if text else ""
            self.add_log(f"⚡ [{kind}] {action}{text_info} (p={prob:.2f})")

        self.root.after(0, update)

    def _on_close(self):
        self.controller.shutdown(timeout=2.0)
        self.root.destroy()


def main():
    load_environment()
    root = tk.Tk()
    VoiceApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()

