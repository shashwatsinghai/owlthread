"""Tkinter-based popup window for OwlThread Query & Primer Engine."""

import logging
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Optional

from owlthread.primer.engine import PrimerEngine, PrimerResult, copy_to_clipboard

logger = logging.getLogger(__name__)

# Dark Theme Palette
COLOR_BG_DARK = "#0f172a"      # Slate 900
COLOR_CARD = "#1e293b"         # Slate 800
COLOR_CARD_BORDER = "#334155"  # Slate 700
COLOR_INPUT_BG = "#020617"     # Slate 950
COLOR_TEXT = "#f8fafc"         # Slate 50
COLOR_TEXT_MUTED = "#94a3b8"   # Slate 400
COLOR_PRIMARY = "#6366f1"      # Indigo 500
COLOR_PRIMARY_HOVER = "#4f46e5"  # Indigo 600
COLOR_ACCENT = "#38bdf8"       # Sky 400
COLOR_SUCCESS = "#22c55e"      # Green 500
COLOR_CHIP_BG = "#334155"      # Slate 700
COLOR_CHIP_HOVER = "#475569"   # Slate 600


class PrimerPopupWindow:
    """Popup window for stating tasks, triggering done/shipped flushes, and reviewing compiled primers."""

    def __init__(self, engine: Optional[PrimerEngine] = None, initial_query: str = ""):
        self.engine = engine or PrimerEngine()
        self.initial_query = initial_query
        self.root: Optional[tk.Tk] = None
        self._is_generating = False

    def show(self) -> None:
        """Create and display the popup dialog."""
        self.root = tk.Tk()
        self.root.title("OwlThread — Query & Primer Engine")
        self.root.geometry("740x660")
        self.root.minsize(600, 500)
        self.root.configure(bg=COLOR_BG_DARK)

        # Center on screen
        self.root.update_idletasks()
        width = 740
        height = 660
        x = (self.root.winfo_screenwidth() // 2) - (width // 2)
        y = (self.root.winfo_screenheight() // 2) - (height // 2)
        self.root.geometry(f"{width}x{height}+{x}+{y}")

        # Configure UI
        self._setup_ui()

        if self.initial_query:
            self.input_entry.insert(0, self.initial_query)
            self._trigger_generate()

        self.root.bind("<Escape>", lambda e: self.root.destroy())
        self.root.bind("<Return>", lambda e: self._on_enter_pressed(e))

        # Focus input entry
        self.input_entry.focus_set()
        self.root.mainloop()

    def _setup_ui(self) -> None:
        """Construct the widgets and layout."""
        # Top Header Frame
        header_frame = tk.Frame(self.root, bg=COLOR_BG_DARK, padx=20, pady=12)
        header_frame.pack(fill=tk.X)

        title_lbl = tk.Label(
            header_frame,
            text="🦉 OwlThread Context Primer",
            font=("Segoe UI", 15, "bold"),
            fg=COLOR_TEXT,
            bg=COLOR_BG_DARK,
        )
        title_lbl.pack(anchor=tk.W)

        subtitle_lbl = tk.Label(
            header_frame,
            text="State your task — OwlThread will compile relevant project context into your clipboard.",
            font=("Segoe UI", 9),
            fg=COLOR_TEXT_MUTED,
            bg=COLOR_BG_DARK,
        )
        subtitle_lbl.pack(anchor=tk.W, pady=(2, 0))

        # Main Content Card
        main_card = tk.Frame(
            self.root,
            bg=COLOR_CARD,
            padx=16,
            pady=14,
            highlightbackground=COLOR_CARD_BORDER,
            highlightthickness=1,
        )
        main_card.pack(fill=tk.BOTH, expand=True, padx=20, pady=(0, 15))

        # Input Row Label
        input_lbl = tk.Label(
            main_card,
            text="What are you about to work on?",
            font=("Segoe UI", 10, "bold"),
            fg=COLOR_TEXT,
            bg=COLOR_CARD,
        )
        input_lbl.pack(anchor=tk.W)

        # Input Box
        self.input_entry = tk.Entry(
            main_card,
            font=("Segoe UI", 11),
            bg=COLOR_INPUT_BG,
            fg=COLOR_TEXT,
            insertbackground=COLOR_TEXT,
            relief=tk.FLAT,
            highlightbackground=COLOR_CARD_BORDER,
            highlightcolor=COLOR_PRIMARY,
            highlightthickness=1,
        )
        self.input_entry.pack(fill=tk.X, pady=(6, 8), ipady=5)

        # Quick Suggestion Chips Frame
        chips_frame = tk.Frame(main_card, bg=COLOR_CARD)
        chips_frame.pack(fill=tk.X, pady=(0, 10))

        examples_lbl = tk.Label(
            chips_frame,
            text="Quick Actions / Examples:",
            font=("Segoe UI", 8),
            fg=COLOR_TEXT_MUTED,
            bg=COLOR_CARD,
        )
        examples_lbl.pack(side=tk.LEFT, padx=(0, 6))

        examples = [
            ("⚡ Stripe billing", "integrate Stripe billing"),
            ("💼 Investor idea", "I want to send this idea to an investor"),
            ("📊 Audit update", "audit new update"),
            ("🏁 Task Done (Flush)", "done"),
        ]

        for label_text, query_text in examples:
            btn = tk.Button(
                chips_frame,
                text=label_text,
                font=("Segoe UI", 8),
                bg=COLOR_CHIP_BG,
                fg=COLOR_TEXT,
                activebackground=COLOR_CHIP_HOVER,
                activeforeground=COLOR_TEXT,
                relief=tk.FLAT,
                padx=6,
                pady=2,
                cursor="hand2",
                command=lambda q=query_text: self._set_query_and_generate(q),
            )
            btn.pack(side=tk.LEFT, padx=3)

        # Options & Generate Bar
        action_bar = tk.Frame(main_card, bg=COLOR_CARD)
        action_bar.pack(fill=tk.X, pady=(0, 10))

        # Intent selector
        intent_lbl = tk.Label(
            action_bar,
            text="Intent:",
            font=("Segoe UI", 9),
            fg=COLOR_TEXT_MUTED,
            bg=COLOR_CARD,
        )
        intent_lbl.pack(side=tk.LEFT, padx=(0, 4))

        self.intent_var = tk.StringVar(value="auto (LLM classify)")
        intent_choices = [
            "auto (LLM classify)",
            "dev_task",
            "external_comms",
            "status_query",
            "other",
        ]
        self.intent_menu = ttk.OptionMenu(
            action_bar,
            self.intent_var,
            intent_choices[0],
            *intent_choices,
        )
        self.intent_menu.pack(side=tk.LEFT, padx=(0, 10))

        # Include history checkbox
        self.include_history_var = tk.BooleanVar(value=False)
        self.history_chk = tk.Checkbutton(
            action_bar,
            text="Include History",
            variable=self.include_history_var,
            font=("Segoe UI", 8),
            fg=COLOR_TEXT_MUTED,
            bg=COLOR_CARD,
            activebackground=COLOR_CARD,
            activeforeground=COLOR_TEXT,
            selectcolor=COLOR_INPUT_BG,
        )
        self.history_chk.pack(side=tk.LEFT, padx=(0, 10))

        # Generate Button
        self.generate_btn = tk.Button(
            action_bar,
            text="🚀 Generate Primer",
            font=("Segoe UI", 10, "bold"),
            bg=COLOR_PRIMARY,
            fg="#ffffff",
            activebackground=COLOR_PRIMARY_HOVER,
            activeforeground="#ffffff",
            relief=tk.FLAT,
            padx=14,
            pady=4,
            cursor="hand2",
            command=self._trigger_generate,
        )
        self.generate_btn.pack(side=tk.RIGHT)

        # Status / Feedback line
        self.status_lbl = tk.Label(
            main_card,
            text="Ready. Enter a task description or type 'done' above.",
            font=("Segoe UI", 9, "italic"),
            fg=COLOR_TEXT_MUTED,
            bg=COLOR_CARD,
        )
        self.status_lbl.pack(anchor=tk.W, pady=(0, 6))

        # Preview Section Label
        preview_lbl = tk.Label(
            main_card,
            text="Context Primer Preview (Auto-copied to clipboard):",
            font=("Segoe UI", 9, "bold"),
            fg=COLOR_TEXT,
            bg=COLOR_CARD,
        )
        preview_lbl.pack(anchor=tk.W, pady=(4, 4))

        # Output Text Box with Scrollbar
        output_frame = tk.Frame(main_card, bg=COLOR_INPUT_BG)
        output_frame.pack(fill=tk.BOTH, expand=True)

        scrollbar = tk.Scrollbar(output_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.output_text = tk.Text(
            output_frame,
            wrap=tk.WORD,
            font=("Consolas", 10),
            bg=COLOR_INPUT_BG,
            fg=COLOR_TEXT,
            insertbackground=COLOR_TEXT,
            relief=tk.FLAT,
            padx=10,
            pady=10,
            yscrollcommand=scrollbar.set,
        )
        self.output_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.config(command=self.output_text.yview)

        # Bottom Footer Buttons
        footer_frame = tk.Frame(self.root, bg=COLOR_BG_DARK, padx=20, pady=0)
        footer_frame.pack(fill=tk.X, pady=(0, 12))

        self.copy_btn = tk.Button(
            footer_frame,
            text="📋 Copy to Clipboard",
            font=("Segoe UI", 9),
            bg=COLOR_CHIP_BG,
            fg=COLOR_TEXT,
            activebackground=COLOR_CHIP_HOVER,
            activeforeground=COLOR_TEXT,
            relief=tk.FLAT,
            padx=10,
            pady=4,
            cursor="hand2",
            command=self._copy_output_to_clipboard,
        )
        self.copy_btn.pack(side=tk.LEFT)

        close_btn = tk.Button(
            footer_frame,
            text="Close (Esc)",
            font=("Segoe UI", 9),
            bg=COLOR_BG_DARK,
            fg=COLOR_TEXT_MUTED,
            activebackground=COLOR_CARD,
            activeforeground=COLOR_TEXT,
            relief=tk.FLAT,
            padx=10,
            pady=4,
            cursor="hand2",
            command=self.root.destroy,
        )
        close_btn.pack(side=tk.RIGHT)

    def _set_query_and_generate(self, query_text: str) -> None:
        """Set entry text from chip example and generate immediately."""
        self.input_entry.delete(0, tk.END)
        self.input_entry.insert(0, query_text)
        self._trigger_generate()

    def _on_enter_pressed(self, event) -> None:
        """Handle Enter key in input entry."""
        if self.root.focus_get() == self.input_entry:
            self._trigger_generate()

    def _trigger_generate(self) -> None:
        """Initiate primer compilation or task done flush on background thread."""
        query = self.input_entry.get().strip()
        if not query:
            self.status_lbl.config(
                text="⚠️ Please enter a task or query first.",
                fg="#f59e0b"
            )
            return

        if self._is_generating:
            return

        self._is_generating = True
        self.generate_btn.config(state=tk.DISABLED, text="⏳ Processing...")
        self.status_lbl.config(
            text="🔍 Processing request...",
            fg=COLOR_ACCENT
        )

        selected_intent = self.intent_var.get()
        intent_override = None if "auto" in selected_intent else selected_intent
        include_history = self.include_history_var.get()

        threading.Thread(
            target=self._run_generation_worker,
            args=(query, intent_override, include_history),
            daemon=True,
        ).start()

    def _run_generation_worker(self, query: str, intent_override: Optional[str], include_history: bool) -> None:
        """Background worker thread for PrimerEngine execution."""
        try:
            result = self.engine.generate_primer(
                user_request=query,
                intent_override=intent_override,
                include_history=include_history,
                auto_copy=True,
            )
            if self.root:
                self.root.after(0, self._on_generation_complete, result)
        except Exception as e:
            logger.exception("Error generating primer in UI worker: %s", e)
            if self.root:
                self.root.after(0, self._on_generation_error, str(e))

    def _on_generation_complete(self, result: PrimerResult) -> None:
        """Update UI with completed PrimerResult."""
        self._is_generating = False
        if not self.root:
            return

        self.generate_btn.config(state=tk.NORMAL, text="🚀 Generate Primer")

        # Update preview box
        self.output_text.delete("1.0", tk.END)
        self.output_text.insert(tk.END, result.primer_text)

        # Status text
        copy_status = "✅ Copied to clipboard!" if result.copied_to_clipboard else "📋 Ready."
        if result.is_flush_signal:
            summary = result.flush_summary or {}
            self.status_lbl.config(
                text=f"🏁 Buffer Flushed: {summary.get('batches_flushed', 0)} batches | Extracted: {summary.get('total_extracted', 0)} ({result.elapsed_sec:.2f}s)",
                fg=COLOR_SUCCESS
            )
        else:
            self.status_lbl.config(
                text=f"Intent: [{result.intent}] | Found {len(result.matched_entries)} active memories | {copy_status} ({result.elapsed_sec:.2f}s)",
                fg=COLOR_SUCCESS if result.copied_to_clipboard else COLOR_TEXT,
            )

    def _on_generation_error(self, err_msg: str) -> None:
        """Handle worker error."""
        self._is_generating = False
        if not self.root:
            return

        self.generate_btn.config(state=tk.NORMAL, text="🚀 Generate Primer")
        self.status_lbl.config(text=f"❌ Error: {err_msg}", fg="#ef4444")
        messagebox.showerror("OwlThread Primer Error", f"Failed to generate primer:\n{err_msg}")

    def _copy_output_to_clipboard(self) -> None:
        """Manual copy button handler."""
        text = self.output_text.get("1.0", tk.END).strip()
        if text:
            copy_to_clipboard(text)
            self.copy_btn.config(text="✅ Copied!")
            self.root.after(2000, lambda: self.copy_btn.config(text="📋 Copy to Clipboard"))


def open_primer_popup(engine: Optional[PrimerEngine] = None, initial_query: str = "") -> None:
    """Convenience launcher for Primer popup window."""
    popup = PrimerPopupWindow(engine=engine, initial_query=initial_query)
    popup.show()


if __name__ == "__main__":
    open_primer_popup()
