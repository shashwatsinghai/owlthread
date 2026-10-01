"""Expandable memory card with clear source and history actions."""
from __future__ import annotations
import logging
import json
import tkinter as tk
from datetime import datetime,timezone
from typing import Any,Callable
from owlthread.config import QUADRANT_COLORS
from owlthread.clipboard_io import copy_to_clipboard
from owlthread.gui.animations import Animator
from owlthread.gui.theme import CARD, TEXT, MUTED, BG, BORDER, ACCENT, RoundedFrame, button

logger = logging.getLogger(__name__)


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


class FeedCard(RoundedFrame):
    def __init__(self, master: tk.Misc, entry: dict[str,Any],
                 on_action: Callable[[int,str],None] | None = None, **kwargs: Any) -> None:
        super().__init__(master,bg=CARD,highlightthickness=1,highlightbackground=BORDER,padx=22,pady=20,**kwargs)
        self.entry = entry
        self.on_action = on_action
        self.expanded = False
        quadrant = entry.get("quadrant") or "technical_architecture"
        top = tk.Frame(self,bg=CARD)
        top.pack(fill="x")
        tk.Label(top,text="●  "+quadrant.replace("_"," ").title(),font=("Segoe UI",9,"bold"),
                 bg=CARD,fg=QUADRANT_COLORS.get(quadrant,MUTED)).pack(side="left")
        tk.Label(top,text=_relative_time(entry.get("created_at") or entry.get("timestamp") or ""),bg=CARD,fg=MUTED,font=("Segoe UI",9)).pack(side="right")
        self.summary = tk.Label(self,text=entry.get("summary") or (entry.get("raw_text") or "")[:180],bg=CARD,fg=TEXT,
                               font=("Segoe UI",12),anchor="w",justify="left",wraplength=780)
        self.summary.pack(fill="x",pady=(11,10))
        score = f"  ·  relevance {entry['score']:.2f}" if "score" in entry else ""
        self.meta = tk.Label(self,text=f"{entry.get('source_app','manual').replace('_',' ')}  ·  #{entry['id']}{score}",
                            bg=CARD,fg=MUTED,font=("Segoe UI",9),anchor="w")
        self.meta.pack(fill="x")
        actions = tk.Frame(self,bg=CARD)
        actions.pack(fill="x",pady=(12,0))
        self.toggle_button = button(actions,"Show details",self.toggle)
        self.toggle_button.pack(side="left")
        button(actions,"Copy",self.copy).pack(side="left",padx=6)
        if self.on_action:
            button(actions,"Archive",lambda:self.action("archive")).pack(side="right")
        self.detail = tk.Text(self,bg=BG,fg=TEXT,insertbackground=TEXT,relief="flat",wrap="word",
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
        self.bind("<Leave>",lambda _:self.configure(highlightbackground=BORDER))

    def toggle(self, event: tk.Event | None = None) -> None:
        self.expanded = not self.expanded
        self.toggle_button.configure(text="Hide details" if self.expanded else "Show details")
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


class CaptureCard(RoundedFrame):
    """Raw receipt with an explicit extraction state and selectable original text."""

    def __init__(self, master: tk.Misc, capture: dict[str,Any], **kwargs: Any) -> None:
        super().__init__(master,bg=CARD,padx=22,pady=20,highlightthickness=1,highlightbackground=BORDER,**kwargs)
        self.capture=capture
        self.expanded=False
        processed=bool(capture.get("processed"))
        status="Extracted" if processed else {
            "pending":"Waiting to extract", "failed":"Extraction failed",
            "retry":"Waiting to retry", "partial":"Partly extracted",
        }.get(capture.get("extraction_status"),str(capture.get("extraction_status") or "Waiting to extract").replace("_"," ").title())
        color="#62d6ad" if processed else "#f59e0b" if capture.get("extraction_status")=="failed" else "#a7a1ff"
        source=str(capture.get("source_app") or "manual").replace("_"," ")
        heading=tk.Frame(self,bg=CARD)
        heading.pack(fill="x")
        tk.Label(heading,text=f"Capture  ·  {status}",bg=CARD,fg=color,font=("Segoe UI",9,"bold"),anchor="w").pack(side="left")
        tk.Label(heading,text=_relative_time(capture.get("captured_at") or ""),bg=CARD,fg=MUTED,font=("Segoe UI",9)).pack(side="right")
        raw=capture.get("raw_text") or ""
        preview=" ".join(raw.split())
        if len(preview)>220: preview=preview[:217]+"…"
        self.preview=tk.Label(self,text=preview,bg=CARD,fg=TEXT,justify="left",anchor="w",wraplength=780,font=("Segoe UI",11))
        self.preview.pack(fill="x",pady=(8,6))
        metadata=f"{source} · #{capture['id']} · {len(raw):,} characters"
        if capture.get("attempts"): metadata+=f" · {capture['attempts']} extraction attempts"
        self.meta=tk.Label(self,text=metadata,bg=CARD,fg=MUTED,anchor="w",font=("Segoe UI",9))
        self.meta.pack(fill="x")
        try:
            source_metadata=json.loads(capture.get("source_metadata") or "{}")
        except (ValueError,TypeError):
            source_metadata={}
        if isinstance(source_metadata,dict):
            source_details="\n".join(str(source_metadata.get(key) or "") for key in ("title","url") if source_metadata.get(key))
            if source_details:
                self.source_details=tk.Label(self,text=source_details,bg=CARD,fg=MUTED,anchor="w",justify="left",font=("Segoe UI",9),wraplength=780)
                self.source_details.pack(fill="x",pady=(6,0))
        reason=capture.get("extraction_reason")
        if reason and not processed:
            self.reason=tk.Label(self,text=str(reason),bg=CARD,fg="#f59e0b",anchor="w",justify="left",font=("Segoe UI",9),wraplength=780)
            self.reason.pack(fill="x",pady=(6,0))
        self.toggle_button=button(self,"Show original text",self.toggle)
        self.toggle_button.pack(anchor="w",pady=(8,0))
        self.detail=tk.Text(self,bg=BG,fg=TEXT,wrap="word",height=8,relief="flat",font=("Consolas",10),padx=12,pady=12)
        self.detail.insert("1.0",raw)
        self.detail.configure(state="disabled")
        self.bind("<Configure>",self._resize)

    def _resize(self, event: tk.Event) -> None:
        self.preview.configure(wraplength=max(160,event.width-34))
        if hasattr(self,"reason"): self.reason.configure(wraplength=max(160,event.width-34))
        if hasattr(self,"source_details"): self.source_details.configure(wraplength=max(160,event.width-34))

    def toggle(self) -> None:
        self.expanded=not self.expanded
        self.toggle_button.configure(text="Hide original text" if self.expanded else "Show original text")
        if self.expanded:
            self.detail.pack(fill="x",pady=(10,0))
        else:
            self.detail.pack_forget()
