"""Responsive embedded and popup task primers, using a queue for UI delivery."""
from __future__ import annotations
import logging
import queue
import threading
import time
import tkinter as tk
from tkinter import ttk
from typing import Any
from owlthread.primer.engine import PrimerEngine,PrimerResult
from owlthread.gui.animations import Animator
from owlthread.gui.theme import BG, TEXT, MUTED, ACCENT, CARD, SURFACE, RoundedFrame, button

logger = logging.getLogger(__name__)


class PrimerPanel(tk.Frame):
    def __init__(self, master: tk.Misc, engine: PrimerEngine, initial_query: str = "") -> None:
        super().__init__(master,bg=BG)
        self.engine = engine
        self._results: queue.Queue[PrimerResult | Exception] = queue.Queue()
        self.busy = False
        self._worker: threading.Thread | None = None
        self._active_query = ""
        self._conversation_started = False
        self.query = tk.StringVar(value=initial_query)
        tk.Label(self,text="Ask OwlThread.",bg=BG,fg=TEXT,font=("Segoe UI",22,"bold"),anchor="w").pack(fill="x",pady=(0,6))
        tk.Label(self,text="Describe your task or ask a question. Find the decisions and details you have already saved.",wraplength=340,bg=BG,fg=MUTED,
                 justify="left",anchor="w",font=("Segoe UI",10)).pack(fill="x",pady=(0,20))
        input_frame = RoundedFrame(self,bg=CARD,padx=16,pady=12)
        input_frame.pack(fill="x")
        self.input = tk.Entry(input_frame,textvariable=self.query,bg=CARD,fg=TEXT,insertbackground=ACCENT,
                              relief="flat",font=("Segoe UI",12))
        self.input.pack(fill="x")
        self.input.bind("<Return>",lambda _:self.generate())
        self.button = button(self,"Find related context",self.generate,True)
        self.button.pack(fill="x",pady=(10,12))
        self.badge = tk.Label(self,text="Try: What did we decide about authentication?",wraplength=340,justify="left",bg=BG,fg=MUTED,anchor="w",font=("Segoe UI",9))
        self.badge.pack(fill="x",pady=(0,12))
        output_frame = RoundedFrame(self,bg=CARD,padx=16,pady=16)
        output_frame.pack(fill="both",expand=True)
        scroll = ttk.Scrollbar(output_frame)
        scroll.pack(side="right",fill="y")
        self.output = tk.Text(output_frame,wrap="word",bg=CARD,fg=TEXT,insertbackground=TEXT,relief="flat",
                              height=1,width=1,padx=0,pady=0,font=("Segoe UI",10),yscrollcommand=scroll.set)
        self.output.pack(fill="both",expand=True)
        scroll.configure(command=self.output.yview)
        self.output.insert("1.0","Your next task starts with context.\n\nAsk about a previous decision, or describe what you are building. Your related memories and captures will appear here.\n\nYou can ask in English or Hinglish. Type “done” to extract your latest captures.")
        self.output.configure(state="disabled")
        self.notice = tk.Label(self,text="Searches saved context · copies the result to your clipboard",wraplength=340,justify="left",bg=BG,fg=MUTED,anchor="w",font=("Segoe UI",9))
        self.notice.pack(side="bottom",fill="x",pady=(12,0))
        output_frame.pack_forget()
        output_frame.pack(fill="both",expand=True)
        self._poll_id = self.after(80,self._poll)
        self.bind("<Destroy>",self._destroyed)

    def _destroyed(self, event: tk.Event) -> None:
        if event.widget is self:
            self.after_cancel(self._poll_id)

    def generate(self) -> None:
        text = self.query.get().strip()
        if self.busy or not text:
            return
        self.busy = True
        self._active_query = text
        self.query.set("")
        self._append_message("You", text)
        self.button.configure(state="disabled",text="Compiling your context…")
        self.notice.configure(text="Searching your local memory…")
        def work() -> None:
            try:
                project_id = self.engine.db.get_or_create_project(self.engine.db.get_setting("active_project","General"))
                self._results.put(self.engine.generate_primer(text,project_id=project_id))
            except Exception as exc:
                logger.exception("Primer request failed")
                self._results.put(exc)
        self._worker = threading.Thread(target=work,daemon=True,name="OwlThread-Primer")
        self._worker.start()

    def _poll(self) -> None:
        try:
            value = self._results.get_nowait()
        except queue.Empty:
            pass
        else:
            self.busy = False
            self.button.configure(state="normal",text="Find related context")
            if isinstance(value,Exception):
                self._append_message("OwlThread", "I couldn't compile that context. Your saved memory was not changed.")
                self.notice.configure(text="Could not generate context. Please try again.",fg="#f59e0b")
            else:
                self._append_message("OwlThread", value.primer_text)
                raw_count = sum(entry.get("context_kind") == "capture" for entry in value.matched_entries)
                cache = "  ·  cached" if getattr(value,"cache_hit",False) else ""
                evidence = f"{len(value.matched_entries)-raw_count} memories"
                if raw_count:
                    evidence += f" + {raw_count} raw captures"
                self.badge.configure(text=f"{value.intent.replace('_',' ')}  ·  {evidence}{cache}  ·  {value.elapsed_sec:.1f}s",fg=ACCENT)
                self.notice.configure(text="✓ Copied to clipboard" if value.copied_to_clipboard else "Clipboard unavailable. Select the brief to copy.",fg="#62d6ad" if value.copied_to_clipboard else "#f59e0b")
        self._poll_id = self.after(80,self._poll)

    def _append_message(self, speaker: str, text: str) -> None:
        """Append a turn so the Primer surface behaves like a conversation."""
        self.output.configure(state="normal")
        if not self._conversation_started:
            self.output.delete("1.0","end")
            self._conversation_started = True
        elif self.output.get("1.0","end-1c").strip():
            self.output.insert("end","\n\n")
        self.output.tag_configure("speaker",foreground=ACCENT,font=("Segoe UI",10,"bold"),spacing1=10,spacing3=6)
        self.output.insert("end",f"{speaker}\n","speaker")
        self.output.insert("end",text.strip())
        self.output.configure(state="disabled")
        self.output.see("end")


class PrimerPopupUI(tk.Toplevel):
    def __init__(self, master: tk.Misc, engine: PrimerEngine, initial_query: str = "") -> None:
        super().__init__(master,bg=BG)
        self.overrideredirect(True)
        self.title("OwlThread — Task primer")
        self.attributes("-topmost",True)
        self.geometry(f"400x600+{(self.winfo_screenwidth()-400)//2}+{(self.winfo_screenheight()-600)//2}")
        bar = tk.Frame(self,bg=SURFACE,height=40)
        bar.pack(fill="x")
        title = tk.Label(bar,text="◉  OwlThread",bg=SURFACE,fg=TEXT,font=("Segoe UI",10,"bold"),padx=16,pady=10)
        title.pack(side="left")
        tk.Button(bar,text="✕",command=self.close,bg=SURFACE,fg=MUTED,relief="flat").pack(side="right",padx=8)
        self._drag = (0,0)
        title.bind("<Button-1>",self._drag_start)
        title.bind("<B1-Motion>",self._drag_move)
        self.panel = PrimerPanel(self,engine,initial_query)
        self.panel.pack(fill="both",expand=True,padx=20,pady=20)
        self.last_activity = time.monotonic()
        self.bind("<Key>",self._activity)
        self.bind("<Motion>",self._activity)
        self.bind("<Button>",self._activity)
        self.bind("<Escape>",lambda _:self.close())
        self._idle_id = self.after(1000,self._idle)
        self.bind("<Destroy>",self._destroyed)
        self.panel.input.focus_set()
        self.after_idle(self._focus)
        Animator.fade_in(self)

    def _focus(self) -> None:
        if self.winfo_exists():
            self.lift()
            self.panel.input.focus_force()

    def _drag_start(self, event: tk.Event) -> None:
        self._drag = (event.x_root-self.winfo_x(),event.y_root-self.winfo_y())

    def _drag_move(self, event: tk.Event) -> None:
        self.geometry(f"+{event.x_root-self._drag[0]}+{event.y_root-self._drag[1]}")

    def _activity(self, event: tk.Event | None = None) -> None:
        self.last_activity = time.monotonic()

    def _idle(self) -> None:
        if self.panel.busy:
            self.last_activity = time.monotonic()
        if time.monotonic()-self.last_activity>30:
            self.close()
        else:
            self._idle_id = self.after(1000,self._idle)

    def _destroyed(self, event: tk.Event) -> None:
        if event.widget is self:
            self.after_cancel(self._idle_id)

    def close(self) -> None:
        self.destroy()


def open_primer_popup(engine: PrimerEngine | None = None, initial_query: str = "") -> None:
    owns = engine is None
    engine = engine or PrimerEngine()
    root = tk.Tk()
    root.withdraw()
    popup = PrimerPopupUI(root,engine,initial_query)
    try:
        root.wait_window(popup)
        if popup.panel._worker:
            popup.panel._worker.join()
    finally:
        root.destroy()
        if owns:
            engine.db.close()
