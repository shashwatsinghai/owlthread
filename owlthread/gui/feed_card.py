"""CustomTkinter Memory Card widget for OwlThread Desktop Application.

Premium redesign: hover glow, relative timestamps, smooth selection transitions,
better typography, and refined visual hierarchy.
"""

import json
import time
import tkinter as tk
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional
import customtkinter as ctk

from owlthread.gui.animations import AnimationEngine

# ── Premium Dark Palette (Refined Depth Hierarchy) ──────────────────
COLOR_BG_BASE       = "#06080d"          # Deepest void
COLOR_CARD_BG       = "#0f1420"          # Card resting state
COLOR_CARD_HOVER    = "#151c2c"          # Card hover — subtle lift
COLOR_CARD_SELECTED = "#171530"          # Card selected — indigo tint
COLOR_BORDER        = "#182030"          # Subtle hairline border
COLOR_BORDER_HOVER  = "#2a3550"          # Border on hover — gentle reveal
COLOR_BORDER_SELECTED = "#6366f1"        # Selected — electric indigo glow
COLOR_TEXT_HIGH     = "#f1f5f9"          # Primary text — high contrast
COLOR_TEXT_MED      = "#8b9ab8"          # Secondary text — muted
COLOR_TEXT_LOW      = "#506080"          # Tertiary text — timestamps
COLOR_ACCENT_BAR   = "#6366f1"          # Default accent bar color

QUADRANT_STYLES = {
    "technical_architecture": {
        "pill_bg": "#1a1740",
        "pill_text": "#a5b4fc",
        "accent": "#6366f1",
        "label": "🏗️ Architecture",
    },
    "business_rules": {
        "pill_bg": "#0a3a2a",
        "pill_text": "#6ee7b7",
        "accent": "#10b981",
        "label": "💼 Business",
    },
    "settled_decisions": {
        "pill_bg": "#2a0a4a",
        "pill_text": "#d8b4fe",
        "accent": "#a855f7",
        "label": "🔒 Decision",
    },
    "open_questions": {
        "pill_bg": "#3a1a00",
        "pill_text": "#fde68a",
        "accent": "#f59e0b",
        "label": "❓ Question",
    },
}

DEFAULT_STYLE = {
    "pill_bg": "#1a2235",
    "pill_text": "#cbd5e1",
    "accent": "#22d3ee",
    "label": "📌 Context",
}

SOURCE_ICONS = {
    "browser": "🌐 Browser",
    "cursor": "💻 Cursor",
    "copilot": "🤖 Copilot",
    "clipboard": "📋 Clip",
    "cli": "⌨️ Terminal",
    "direct": "📝 Quick Dump",
}


def _relative_time(timestamp_str: str) -> str:
    """Convert ISO timestamp string to human-friendly relative time.

    Returns strings like: 'Just now', '2m ago', '1h ago', 'Yesterday', '3d ago'.
    """
    if not timestamp_str:
        return ""
    try:
        # Parse the timestamp (handle both formats)
        ts = timestamp_str.replace("T", " ")[:19]
        dt = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
        now = datetime.now()
        delta = now - dt
        seconds = int(delta.total_seconds())

        if seconds < 0:
            return "Just now"
        if seconds < 30:
            return "Just now"
        if seconds < 60:
            return f"{seconds}s ago"
        if seconds < 3600:
            mins = seconds // 60
            return f"{mins}m ago"
        if seconds < 86400:
            hours = seconds // 3600
            return f"{hours}h ago"
        if seconds < 172800:
            return "Yesterday"
        days = seconds // 86400
        if days < 30:
            return f"{days}d ago"
        if days < 365:
            months = days // 30
            return f"{months}mo ago"
        return f"{days // 365}y ago"
    except Exception:
        # Fallback: show raw truncated timestamp
        return timestamp_str[5:16].replace("T", " ") if len(timestamp_str) > 5 else timestamp_str


class MemoryFeedCard(ctk.CTkFrame):
    """Premium memory card with smooth hover glow, relative timestamps, and refined typography.

    Designed for the master list in a split-pane layout. Features:
    - Smooth color transitions on hover/selection via AnimationEngine
    - Relative timestamps ('2m ago', '1h ago')
    - Refined accent bar with quadrant coloring
    - Cleaner text hierarchy
    """

    def __init__(
        self,
        master,
        entry: Dict[str, Any],
        on_select: Optional[Callable[[Dict[str, Any]], None]] = None,
        on_copy: Optional[Callable[[str], None]] = None,
        on_delete: Optional[Callable[[int], None]] = None,
        is_selected: bool = False,
        **kwargs
    ):
        self._is_selected = is_selected
        super().__init__(
            master,
            fg_color=COLOR_CARD_SELECTED if is_selected else COLOR_CARD_BG,
            corner_radius=10,
            border_width=1,
            border_color=COLOR_BORDER_SELECTED if is_selected else COLOR_BORDER,
            **kwargs
        )
        self.entry = entry
        self.on_select = on_select
        self.on_copy = on_copy
        self.on_delete = on_delete
        self._hovering = False
        self._build_ui()
        self._bind_click_events(self)

    @property
    def is_selected(self) -> bool:
        return self._is_selected

    @is_selected.setter
    def is_selected(self, value: bool):
        self._is_selected = value

    def _build_ui(self) -> None:
        entry_id = self.entry.get("id")
        raw_text = (self.entry.get("raw_text") or "").strip()
        summary = (self.entry.get("summary") or "").strip()
        source_app = (self.entry.get("source_app") or "browser").lower()
        quadrant = (self.entry.get("quadrant") or "").lower()
        timestamp = self.entry.get("timestamp") or ""
        project_name = self.entry.get("project_name") or "General"

        metadata = self.entry.get("source_metadata") or {}
        if isinstance(metadata, str):
            try:
                metadata = json.loads(metadata)
            except Exception:
                metadata = {}

        container_type = metadata.get("container_type") or metadata.get("type") or ""
        q_style = QUADRANT_STYLES.get(quadrant, DEFAULT_STYLE)

        # ── 1. Left Accent Bar ──────────────────────────────────────
        self.accent_bar = ctk.CTkFrame(
            self,
            width=3,
            corner_radius=2,
            fg_color=q_style["accent"],
        )
        self.accent_bar.pack(side="left", fill="y", padx=(6, 0), pady=8)

        # ── 2. Main Content Area ────────────────────────────────────
        self.main_box = ctk.CTkFrame(self, fg_color="transparent")
        self.main_box.pack(side="left", fill="both", expand=True, padx=(10, 10), pady=8)

        # ── Top Row: Badges + Timestamp ─────────────────────────────
        top_row = ctk.CTkFrame(self.main_box, fg_color="transparent")
        top_row.pack(fill="x", pady=(0, 4))

        # Quadrant Pill Badge
        ctk.CTkLabel(
            top_row,
            text=q_style["label"],
            font=("Segoe UI", 9, "bold"),
            text_color=q_style["pill_text"],
            fg_color=q_style["pill_bg"],
            corner_radius=5,
            padx=7,
            pady=1,
        ).pack(side="left", padx=(0, 5))

        # Source / Domain Badge
        src_label = SOURCE_ICONS.get(source_app, f"📌 {source_app.capitalize()}")
        if container_type == "user_message":
            src_label = "💬 Prompt"
        elif container_type == "assistant_response":
            src_label = "🤖 AI"
        elif container_type == "user_selection":
            src_label = "✨ Selection"
        elif container_type == "user_note":
            src_label = "📝 Note"
        elif container_type == "saved_address":
            src_label = "🔖 Saved"

        ctk.CTkLabel(
            top_row,
            text=f"{src_label} · {project_name[:14]}",
            font=("Segoe UI", 9),
            text_color=COLOR_TEXT_LOW,
            fg_color="#0a0e16",
            corner_radius=4,
            padx=6,
            pady=1,
        ).pack(side="left", padx=(0, 5))

        # Quick Delete Button (appears on far right)
        if self.on_delete and entry_id:
            del_btn = ctk.CTkButton(
                top_row,
                text="✕",
                width=18,
                height=18,
                font=("Segoe UI", 9, "bold"),
                fg_color="transparent",
                text_color=COLOR_TEXT_LOW,
                hover_color="#ef4444",
                corner_radius=4,
                command=lambda eid=entry_id: self.on_delete(int(eid)),
            )
            del_btn.pack(side="right")

        # Relative Timestamp
        rel_time = _relative_time(timestamp)
        ctk.CTkLabel(
            top_row,
            text=rel_time,
            font=("Segoe UI", 9),
            text_color=COLOR_TEXT_LOW,
        ).pack(side="right", padx=(0, 4))

        # ── Title Row: Summary Headline ─────────────────────────────
        title_text = summary if summary else (raw_text[:65] + "…" if len(raw_text) > 65 else raw_text)
        self.title_lbl = ctk.CTkLabel(
            self.main_box,
            text=title_text,
            font=("Segoe UI", 12, "bold"),
            text_color=COLOR_TEXT_HIGH,
            anchor="w",
            justify="left",
        )
        self.title_lbl.pack(fill="x", pady=(1, 2))

        # ── Snippet Row: Body Preview ───────────────────────────────
        snippet = raw_text.replace("\n", " ").strip()
        if len(snippet) > 90:
            snippet = snippet[:90] + "…"

        self.snippet_lbl = ctk.CTkLabel(
            self.main_box,
            text=snippet,
            font=("Segoe UI", 11),
            text_color=COLOR_TEXT_MED,
            anchor="w",
            justify="left",
        )
        self.snippet_lbl.pack(fill="x")

    def _bind_click_events(self, widget) -> None:
        """Bind click and hover events recursively across all child widgets."""
        if not isinstance(widget, ctk.CTkButton):
            widget.bind("<Button-1>", self._on_clicked)
            widget.bind("<Enter>", self._on_enter)
            widget.bind("<Leave>", self._on_leave)
        for child in widget.winfo_children():
            self._bind_click_events(child)

    def _on_clicked(self, event=None) -> None:
        if self.on_select:
            self.on_select(self.entry)

    def _on_enter(self, event=None) -> None:
        self._hovering = True
        if not self._is_selected:
            AnimationEngine.color_transition(
                self, "fg_color", COLOR_CARD_BG, COLOR_CARD_HOVER,
                duration_ms=120, steps=6
            )
            AnimationEngine.color_transition(
                self, "border_color", COLOR_BORDER, COLOR_BORDER_HOVER,
                duration_ms=120, steps=6
            )

    def _on_leave(self, event=None) -> None:
        self._hovering = False
        if not self._is_selected:
            AnimationEngine.color_transition(
                self, "fg_color", COLOR_CARD_HOVER, COLOR_CARD_BG,
                duration_ms=150, steps=8
            )
            AnimationEngine.color_transition(
                self, "border_color", COLOR_BORDER_HOVER, COLOR_BORDER,
                duration_ms=150, steps=8
            )

    def set_selected(self, selected: bool) -> None:
        """Toggle selected highlight state with smooth transition."""
        prev = self._is_selected
        self._is_selected = selected

        if selected and not prev:
            # Animate to selected state
            AnimationEngine.color_transition(
                self, "fg_color",
                COLOR_CARD_HOVER if self._hovering else COLOR_CARD_BG,
                COLOR_CARD_SELECTED,
                duration_ms=180, steps=8
            )
            AnimationEngine.color_transition(
                self, "border_color", COLOR_BORDER, COLOR_BORDER_SELECTED,
                duration_ms=180, steps=8
            )
        elif not selected and prev:
            # Animate to deselected state
            target_bg = COLOR_CARD_HOVER if self._hovering else COLOR_CARD_BG
            AnimationEngine.color_transition(
                self, "fg_color", COLOR_CARD_SELECTED, target_bg,
                duration_ms=180, steps=8
            )
            AnimationEngine.color_transition(
                self, "border_color", COLOR_BORDER_SELECTED, COLOR_BORDER,
                duration_ms=180, steps=8
            )
