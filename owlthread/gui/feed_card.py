"""Expandable memory card with clear source and history actions."""
from __future__ import annotations
import logging
import tkinter as tk
from datetime import datetime,timezone
from typing import Any,Callable
from owlthread.config import QUADRANT_COLORS
from owlthread.clipboard_io import copy_to_clipboard
from owlthread.gui.animations import Animator
logger = logging.getLogger(__name__)
CARD = "#222239"
TEXT = "#e2e8f0"
MUTED = "#a4abc2"


def _relative_time(timestamp_str: str) -> str:
    try:
        value = datetime.fromisoformat(timestamp_str.replace("Z","+00:00"))
        if not value.tzinfo:
            value = value.replace(tzinfo=timezone.utc)
        seconds = max(0,(datetime.now(timezone.utc)-value).total_seconds())
        if seconds<60:
            return "just now"
        if seconds<3600:
            return f"{int(seconds/60)}m ago"
        if seconds<86400:
            return f"{int(seconds/3600)}h ago"
        return f"{int(seconds/86400)}d ago"
    except (ValueError,TypeError):
        return "earlier"


class FeedCard(tk.Frame):
    def __init__(self, master: tk.Misc, entry: dict[str,Any],
                 on_action: Callable[[int,str],None] | None = None, **kwargs: Any) -> None:
        super().__init__(master,bg=CARD,highlightthickness=1,highlightbackground="#30314a",padx=18,pady=15,**kwargs)
        self.entry = entry
        self.on_action = on_action
        self.expanded = False
        quadrant = entry.get("quadrant") or "technical_architecture"
        top = tk.Frame(self,bg=CARD)
        top.pack(fill="x")
        tk.Label(top,text="●  "+quadrant.replace("_"," ").upper(),font=("Segoe UI",9,"bold"),
                 bg=CARD,fg=QUADRANT_COLORS.get(quadrant,MUTED)).pack(side="left")
        tk.Label(top,text=_relative_time(entry.get("created_at") or entry.get("timestamp") or ""),bg=CARD,fg=MUTED,font=("Segoe UI",9)).pack(side="right")
        self.summary = tk.Label(self,text=entry.get("summary") or (entry.get("raw_text") or "")[:180],bg=CARD,fg=TEXT,
                               font=("Segoe UI",12),anchor="w",justify="left",wraplength=780)
        self.summary.pack(fill="x",pady=(11,10))
        score = f"  ·  relevance {entry['score']:.2f}" if "score" in entry else ""
        self.meta = tk.Label(self,text=f"{entry.get('source_app','manual').replace('_',' ')}  ·  #{entry['id']}{score}    ↗ expand",
                            bg=CARD,fg=MUTED,font=("Segoe UI",9),anchor="w")
        self.meta.pack(fill="x")
        self.detail = tk.Text(self,bg="#19192d",fg=TEXT,insertbackground=TEXT,relief="flat",wrap="word",
                              height=8,font=("Consolas",10),padx=12,pady=12)
        self.detail.insert("1.0",entry.get("raw_text") or entry.get("summary") or "")
        self.detail.configure(state="disabled")
        menu = tk.Menu(self,tearoff=False,bg=CARD,fg=TEXT)
        menu.add_command(label="Copy memory",command=self.copy)
        menu.add_command(label="Archive",command=lambda:self.action("archive"))
        menu.add_command(label="Mark superseded",command=lambda:self.action("supersede"))
        for widget in (self,top,self.summary,self.meta,*top.winfo_children()):
            widget.bind("<Button-1>",self.toggle)
            widget.bind("<Button-3>",lambda event:menu.tk_popup(event.x_root,event.y_root))
        self.bind("<Configure>",lambda event:self.summary.configure(wraplength=max(140,event.width-40)))
        self.bind("<Enter>",lambda _:self.configure(highlightbackground="#63668d"))
        self.bind("<Leave>",lambda _:self.configure(highlightbackground="#30314a"))

    def toggle(self, event: tk.Event | None = None) -> None:
        self.expanded = not self.expanded
        if self.expanded:
            self.detail.pack(fill="x",pady=(10,0))
        else:
            self.detail.pack_forget()

    def copy(self) -> None:
        copied = copy_to_clipboard(self.entry.get("raw_text") or self.entry.get("summary") or "")
        self.meta.configure(text="Copied to clipboard" if copied else "Clipboard unavailable — expand and select text")
        Animator.pulse(self,CARD,"#2c3d43")

    def action(self, action: str) -> None:
        if self.on_action:
            self.on_action(self.entry["id"],action)


MemoryFeedCard = FeedCard
