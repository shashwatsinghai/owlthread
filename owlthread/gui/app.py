"""OwlThread Desktop Application (GUI).
Built with CustomTkinter for a modern, native Windows dark-mode experience.
Features:
- Real-time live feed with stats banner
- Source filter chips & search-as-you-type
- Quick Dump Box for instant note intake
- 4-Quadrant Knowledge Vault
- Task Query & Primer Engine
- 2-Way Site Access Manager (coordinates with browser extension)
- Wipe / Clear Database button
- Master Pause/Resume capture control
"""

import json
import logging
import threading
import time
import webbrowser
from typing import Any, Dict, List, Optional
import customtkinter as ctk
from tkinter import messagebox

from owlthread.capture.engine import CaptureEngine
from owlthread.config import DEFAULT_HTTP_PORT
from owlthread.db.database import Database
from owlthread.extraction.pipeline import ExtractionPipeline
from owlthread.gui.animations import AnimationEngine
from owlthread.gui.feed_card import MemoryFeedCard
from owlthread.primer.engine import PrimerEngine, copy_to_clipboard

logger = logging.getLogger(__name__)

# ── Premium Dark Palette — Refined Depth Hierarchy ──────────────────
# Background depth levels (5 layers of visual depth)
COLOR_BG_MAIN       = "#06080d"          # Deepest void — root window
COLOR_BG_SIDEBAR    = "#050810"          # Sidebar — slightly darker than main
COLOR_BG_CARD       = "#0f1420"          # Card / surface — raised one level
COLOR_BG_CARD_ALT   = "#151c2c"          # Elevated container / inputs
COLOR_BG_INSPECTOR  = "#0a0f18"          # Detail reader background
COLOR_BG_INPUT      = "#080c14"          # Input fields — subtle inset

# Border depth awareness
COLOR_BORDER        = "#182030"          # Hairline border — default
COLOR_BORDER_FOCUS  = "#6366f1"          # Focus ring — electric indigo
COLOR_BORDER_HOVER  = "#2a3550"          # Hover reveal border

# Brand colors (richer saturation)
COLOR_PRIMARY       = "#6366f1"          # Electric indigo — primary actions
COLOR_PRIMARY_HOVER = "#4f46e5"          # Indigo hover state
COLOR_PRIMARY_DIM   = "#4338ca"          # Indigo dimmed / pressed
COLOR_ACCENT        = "#22d3ee"          # Cyan accent — highlights
COLOR_SUCCESS       = "#22c55e"          # Emerald green — success
COLOR_WARNING       = "#eab308"          # Amber — warnings
COLOR_DANGER        = "#ef4444"          # Crimson red — destructive

# Text contrast hierarchy
COLOR_TEXT          = "#f1f5f9"          # High emphasis — headings
COLOR_TEXT_MUTED    = "#8b9ab8"          # Medium emphasis — body
COLOR_TEXT_SUBTLE   = "#506080"          # Low emphasis — timestamps, metadata

# ── Typography System ───────────────────────────────────────────────
FONT_HEADING     = ("Segoe UI", 16, "bold")
FONT_SUBHEADING  = ("Segoe UI", 14, "bold")
FONT_TITLE       = ("Segoe UI", 13, "bold")
FONT_BODY_BOLD   = ("Segoe UI", 12, "bold")
FONT_BODY        = ("Segoe UI", 12)
FONT_CAPTION     = ("Segoe UI", 11)
FONT_CAPTION_B   = ("Segoe UI", 11, "bold")
FONT_SMALL       = ("Segoe UI", 10)
FONT_SMALL_B     = ("Segoe UI", 10, "bold")
FONT_TINY        = ("Segoe UI", 9)
FONT_NAV         = ("Segoe UI", 12, "bold")
FONT_BRAND       = ("Segoe UI", 18, "bold")
FONT_STAT        = ("Segoe UI", 20, "bold")


class OwlThreadDesktopApp(ctk.CTk):
    """Main Windows Desktop Application for OwlThread."""

    def __init__(
        self,
        db: Optional[Database] = None,
        port: int = DEFAULT_HTTP_PORT,
        auto_start_engine: bool = True,
    ):
        super().__init__()

        self.db = db or Database()
        self.port = port
        self.auto_start_engine = auto_start_engine

        # Configure CustomTkinter window
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")
        self.title("OwlThread — Ambient Memory Command Center")
        self.geometry("1180x780")
        self.minsize(980, 660)
        self.configure(fg_color=COLOR_BG_MAIN)

        # Coordinate Engines
        self.pipeline = ExtractionPipeline(db=self.db)
        self.primer_engine = PrimerEngine(db=self.db, extraction_pipeline=self.pipeline)
        self.engine: Optional[CaptureEngine] = None

        # Reload persisted AI configuration
        self.pipeline.extractor.llm_client.reload_from_db(self.db)
        self.primer_engine.generator.llm_client.reload_from_db(self.db)

        # Filter & View State
        self.current_view = "live_feed"
        self.filter_project = "All Projects"
        self.filter_source = "all"
        self.search_query = ""
        self.selected_quadrant = "all"
        self.is_capture_paused = False
        self._search_debounce_timer = None
        self.selected_entry: Optional[Dict[str, Any]] = None
        self.feed_cards: List[MemoryFeedCard] = []
        self.vault_cards: List[MemoryFeedCard] = []
        self._key_visible = False

        # ── Performance: Diff-based refresh tracking ────────────────
        self._last_feed_ids: List[int] = []
        self._last_vault_ids: List[int] = []
        self._last_mem_count: int = -1
        self._last_domain_count: int = -1

        # ── Lazy view building — only build when first visited ──────
        self._built_views: set = set()

        # Build UI Layout (sidebar + content shell)
        self._build_layout()

        # ── Keyboard shortcuts for power users ──────────────────────
        self._bind_keyboard_shortcuts()

        # Initial Refresh
        self.refresh_feed()

        # ── Deferred engine start — UI renders first, engine starts after ──
        if self.auto_start_engine:
            self.after(100, self._init_capture_engine)

        self._schedule_periodic_poll()

    def _init_capture_engine(self) -> None:
        """Start local HTTP server & background connectors if not already running."""
        try:
            self.engine = CaptureEngine(
                db=self.db,
                http_port=self.port,
                enable_clipboard=True,
                enable_connectors=True,
                enable_http=True,
                pipeline=self.pipeline,
            )
            self.engine.start()
            self.engine.add_capture_callback(self._on_live_capture_received)
            if self.engine.http_listener_error:
                self.beacon_lbl.configure(
                    text=f"🔴 Port {self.port} In Use",
                    text_color=COLOR_DANGER
                )
            else:
                logger.info("OwlThread Capture Engine launched on port %d", self.port)
        except Exception as e:
            logger.warning("Could not bind CaptureEngine: %s", e)
            if hasattr(self, "beacon_lbl"):
                self.beacon_lbl.configure(
                    text=f"🔴 Port {self.port} Error",
                    text_color=COLOR_DANGER
                )

    def _on_live_capture_received(self, entry_data: Dict[str, Any]) -> None:
        """Callback invoked when a new capture arrives from browser extension."""
        self.after(0, lambda: self._handle_incoming_capture(entry_data))

    def _handle_incoming_capture(self, entry_data: Dict[str, Any]) -> None:
        """Update live feed and status indicator on UI thread."""
        src = entry_data.get("source_app") or "browser"
        self._flash_status_beacon(f"Captured from {src}!", COLOR_ACCENT)
        if self.current_view == "live_feed":
            self.refresh_feed()
        self._update_status_counts()

    # -------------------------------------------------------------
    # UI Layout & Sidebar Navigation
    # -------------------------------------------------------------
    def _build_layout(self) -> None:
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # 1. Left Sidebar
        self.sidebar = ctk.CTkFrame(
            self,
            width=250,
            corner_radius=0,
            fg_color=COLOR_BG_SIDEBAR,
            border_width=1,
            border_color=COLOR_BORDER,
        )
        self.sidebar.grid(row=0, column=0, sticky="nsew")
        self.sidebar.grid_propagate(False)
        self._build_sidebar_content()

        # 2. Right Content Area
        self.content_container = ctk.CTkFrame(self, fg_color="transparent")
        self.content_container.grid(row=0, column=1, sticky="nsew", padx=16, pady=16)
        self.content_container.grid_columnconfigure(0, weight=1)
        self.content_container.grid_rowconfigure(0, weight=1)

        # Create Views
        self.views: Dict[str, ctk.CTkFrame] = {}
        self._build_live_feed_view()
        self._build_quick_dump_view()
        self._build_vault_view()
        self._build_sites_view()
        self._build_primer_view()
        self._build_settings_view()

        # Display default view
        self.show_view("live_feed")

    def _build_sidebar_content(self) -> None:
        # Header / Brand
        header_frame = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        header_frame.pack(fill="x", padx=16, pady=(20, 16))

        ctk.CTkLabel(
            header_frame,
            text="🦉 OwlThread",
            font=FONT_BRAND,
            text_color=COLOR_TEXT,
            anchor="w",
        ).pack(fill="x")

        ctk.CTkLabel(
            header_frame,
            text="Ambient Memory Command Center",
            font=FONT_SMALL,
            text_color=COLOR_TEXT_SUBTLE,
            anchor="w",
        ).pack(fill="x")

        # ── Nav Buttons with Active Indicator ───────────────────────
        nav_frame = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        nav_frame.pack(fill="x", padx=8, pady=10)

        self.nav_buttons: Dict[str, ctk.CTkButton] = {}
        self.nav_indicators: Dict[str, ctk.CTkFrame] = {}

        nav_items = [
            ("live_feed",   "📡 Live Stream Feed",      "Ctrl+1"),
            ("quick_dump",  "📥 Quick Dump Box",        "Ctrl+2"),
            ("vault",       "🗂️ Knowledge Vault",       "Ctrl+3"),
            ("sites",       "🌐 Site Access Manager",   "Ctrl+4"),
            ("primer",      "⚡ Primer & Query",         "Ctrl+5"),
            ("settings",    "⚙️ Prompts & Settings",    "Ctrl+6"),
        ]

        for view_key, label, shortcut in nav_items:
            # Container for indicator + button
            row = ctk.CTkFrame(nav_frame, fg_color="transparent", height=38)
            row.pack(fill="x", pady=1)
            row.pack_propagate(False)

            # Active indicator bar (3px left strip)
            indicator = ctk.CTkFrame(row, width=3, corner_radius=2, fg_color="transparent")
            indicator.pack(side="left", fill="y", padx=(4, 0), pady=6)
            self.nav_indicators[view_key] = indicator

            btn = ctk.CTkButton(
                row,
                text=label,
                font=FONT_NAV,
                anchor="w",
                fg_color="transparent",
                text_color=COLOR_TEXT_MUTED,
                hover_color=COLOR_BG_CARD,
                height=34,
                corner_radius=8,
                command=lambda k=view_key: self.show_view(k),
            )
            btn.pack(side="left", fill="both", expand=True, padx=(4, 4))
            self.nav_buttons[view_key] = btn

        # ── Divider ────────────────────────────────────────────────
        ctk.CTkFrame(self.sidebar, height=1, fg_color=COLOR_BORDER).pack(fill="x", padx=16, pady=(6, 6))

        # ── Bottom Status Section ──────────────────────────────────
        status_frame = ctk.CTkFrame(
            self.sidebar,
            fg_color=COLOR_BG_CARD,
            border_width=1,
            border_color=COLOR_BORDER,
            corner_radius=10,
        )
        status_frame.pack(side="bottom", fill="x", padx=12, pady=16)

        # Server beacon status
        self.beacon_lbl = ctk.CTkLabel(
            status_frame,
            text=f"🟢 Server: 127.0.0.1:{self.port}",
            font=FONT_SMALL_B,
            text_color=COLOR_SUCCESS,
            anchor="w",
        )
        self.beacon_lbl.pack(fill="x", padx=10, pady=(8, 2))

        # Memory counts
        self.mem_count_lbl = ctk.CTkLabel(
            status_frame,
            text="Memories: 0 active",
            font=FONT_SMALL,
            text_color=COLOR_TEXT_MUTED,
            anchor="w",
        )
        self.mem_count_lbl.pack(fill="x", padx=10, pady=(0, 4))

        # AI Brain status
        self.sidebar_brain_lbl = ctk.CTkLabel(
            status_frame,
            text="🧠 Brain: Offline",
            font=FONT_SMALL_B,
            text_color=COLOR_ACCENT,
            anchor="w",
            cursor="hand2",
        )
        self.sidebar_brain_lbl.pack(fill="x", padx=10, pady=(0, 6))
        self.sidebar_brain_lbl.bind("<Button-1>", lambda e: self.show_view("settings"))

        # Master Pause / Resume Toggle
        self.pause_btn = ctk.CTkButton(
            status_frame,
            text="⏸️ Pause Capture",
            font=FONT_SMALL,
            height=26,
            fg_color="#1e2940",
            hover_color="#2a3a55",
            corner_radius=6,
            command=self._toggle_master_pause,
        )
        self.pause_btn.pack(fill="x", padx=8, pady=(0, 6))

        # Flush Buffers Button
        self.flush_btn = ctk.CTkButton(
            status_frame,
            text="🏁 Task Done / Flush",
            font=FONT_SMALL_B,
            height=28,
            fg_color=COLOR_PRIMARY,
            hover_color=COLOR_PRIMARY_HOVER,
            corner_radius=6,
            command=self._handle_flush_done,
        )
        self.flush_btn.pack(fill="x", padx=8, pady=(0, 8))

    def _toggle_master_pause(self) -> None:
        """Toggle global pause state and inform local server."""
        self.is_capture_paused = not self.is_capture_paused
        if self.engine and self.engine.http_listener and self.engine.http_listener._server:
            self.engine.http_listener._server.is_paused = self.is_capture_paused

        if self.is_capture_paused:
            self.pause_btn.configure(text="▶️ Resume Capture", fg_color=COLOR_WARNING)
            self.beacon_lbl.configure(text="⏸️ Capture Paused", text_color=COLOR_WARNING)
        else:
            self.pause_btn.configure(text="⏸️ Pause Capture", fg_color="#1e2940")
            self.beacon_lbl.configure(text=f"🟢 Server: 127.0.0.1:{self.port}", text_color=COLOR_SUCCESS)

    def _ensure_view_built(self, view_key: str) -> None:
        """Lazy-build a view on first access."""
        if view_key in self._built_views:
            return
        builders = {
            "quick_dump": self._build_quick_dump_view,
            "vault": self._build_vault_view,
            "sites": self._build_sites_view,
            "primer": self._build_primer_view,
            "settings": self._build_settings_view,
        }
        builder = builders.get(view_key)
        if builder:
            builder()
            self._built_views.add(view_key)

    def show_view(self, view_key: str) -> None:
        """Switch active view with animated nav indicators and lazy building."""
        self.current_view = view_key

        # Lazy-build view if not yet constructed
        self._ensure_view_built(view_key)

        # Update nav buttons with smooth indicator transitions
        for key, btn in self.nav_buttons.items():
            indicator = self.nav_indicators.get(key)
            if key == view_key:
                btn.configure(fg_color=COLOR_PRIMARY, text_color=COLOR_TEXT)
                if indicator:
                    AnimationEngine.color_transition(
                        indicator, "fg_color", COLOR_BG_SIDEBAR, COLOR_PRIMARY,
                        duration_ms=180, steps=8
                    )
            else:
                btn.configure(fg_color="transparent", text_color=COLOR_TEXT_MUTED)
                if indicator:
                    try:
                        indicator.configure(fg_color="transparent")
                    except Exception:
                        pass

        # Switch visible frame
        for key, frame in self.views.items():
            if key == view_key:
                frame.grid(row=0, column=0, sticky="nsew")
            else:
                frame.grid_forget()

        # Post-switch data loads
        if view_key in ("live_feed", "vault"):
            self.refresh_feed()
        elif view_key == "sites":
            self.refresh_sites_view()
        elif view_key == "settings":
            self._load_settings_into_inputs()

    # -------------------------------------------------------------
    # View 1: 📡 Split-Pane Live Stream Feed
    # -------------------------------------------------------------
    def _build_live_feed_view(self) -> None:
        frame = ctk.CTkFrame(self.content_container, fg_color="transparent")
        self.views["live_feed"] = frame
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(2, weight=1)

        # 1. Top Stats Banner with animated counters
        stats_banner = ctk.CTkFrame(frame, fg_color=COLOR_BG_CARD, corner_radius=10, border_width=1, border_color=COLOR_BORDER)
        stats_banner.grid(row=0, column=0, sticky="ew", pady=(0, 8))

        stat_col1 = ctk.CTkFrame(stats_banner, fg_color="transparent")
        stat_col1.pack(side="left", fill="both", expand=True, padx=16, pady=10)
        self.stat_mem_val = ctk.CTkLabel(stat_col1, text="0", font=FONT_STAT, text_color=COLOR_ACCENT)
        self.stat_mem_val.pack(anchor="w")
        ctk.CTkLabel(stat_col1, text="Active Memories", font=FONT_SMALL, text_color=COLOR_TEXT_MUTED).pack(anchor="w")

        # Separator
        ctk.CTkFrame(stats_banner, width=1, fg_color=COLOR_BORDER).pack(side="left", fill="y", pady=10)

        stat_col2 = ctk.CTkFrame(stats_banner, fg_color="transparent")
        stat_col2.pack(side="left", fill="both", expand=True, padx=16, pady=10)
        self.stat_domains_val = ctk.CTkLabel(stat_col2, text="0", font=FONT_STAT, text_color=COLOR_SUCCESS)
        self.stat_domains_val.pack(anchor="w")
        ctk.CTkLabel(stat_col2, text="Connected Domains", font=FONT_SMALL, text_color=COLOR_TEXT_MUTED).pack(anchor="w")

        # Separator
        ctk.CTkFrame(stats_banner, width=1, fg_color=COLOR_BORDER).pack(side="left", fill="y", pady=10)

        stat_col3 = ctk.CTkFrame(stats_banner, fg_color="transparent")
        stat_col3.pack(side="left", fill="both", expand=True, padx=16, pady=10)
        self.stat_status_val = ctk.CTkLabel(stat_col3, text="● Online", font=FONT_STAT, text_color=COLOR_SUCCESS)
        self.stat_status_val.pack(anchor="w")
        ctk.CTkLabel(stat_col3, text="Capture Daemon", font=FONT_SMALL, text_color=COLOR_TEXT_MUTED).pack(anchor="w")

        # 2. Control Bar (Instant Search + Filter Chips)
        ctrl_bar = ctk.CTkFrame(frame, fg_color=COLOR_BG_CARD, corner_radius=10, border_width=1, border_color=COLOR_BORDER)
        ctrl_bar.grid(row=1, column=0, sticky="ew", pady=(0, 8))

        ctrl_top = ctk.CTkFrame(ctrl_bar, fg_color="transparent")
        ctrl_top.pack(fill="x", padx=10, pady=(8, 6))

        self.feed_search_entry = ctk.CTkEntry(
            ctrl_top,
            placeholder_text="🔍 Search memories...",
            font=FONT_CAPTION,
            width=280,
            fg_color=COLOR_BG_INPUT,
            border_color=COLOR_BORDER,
            corner_radius=8,
        )
        self.feed_search_entry.pack(side="left", padx=(0, 8))
        self.feed_search_entry.bind("<KeyRelease>", self._on_search_key_release)

        self.project_menu = ctk.CTkOptionMenu(
            ctrl_top,
            values=["All Projects", "General"],
            font=FONT_CAPTION,
            fg_color="#1a2235",
            button_color=COLOR_PRIMARY,
            corner_radius=8,
            command=self._on_project_filter_changed,
        )
        self.project_menu.pack(side="left", padx=(0, 6))

        self.btn_new_project = ctk.CTkButton(
            ctrl_top,
            text="➕ Project",
            font=FONT_CAPTION_B,
            width=76,
            height=28,
            fg_color="#1a2235",
            hover_color="#2a3550",
            corner_radius=6,
            command=self._handle_create_project_dialog,
        )
        self.btn_new_project.pack(side="left", padx=(0, 8))

        refresh_btn = ctk.CTkButton(
            ctrl_top,
            text="🔄 Refresh",
            font=FONT_CAPTION,
            width=75,
            height=28,
            fg_color=COLOR_PRIMARY,
            hover_color=COLOR_PRIMARY_HOVER,
            corner_radius=6,
            command=self.refresh_feed,
        )
        refresh_btn.pack(side="right")

        # Source Filter Chips Row
        chips_row = ctk.CTkFrame(ctrl_bar, fg_color="transparent")
        chips_row.pack(fill="x", padx=10, pady=(0, 8))

        self.source_chip_buttons: Dict[str, ctk.CTkButton] = {}
        chips = [
            ("all", "All Sources"),
            ("browser", "🌐 Browser"),
            ("user_message", "💬 User Chat"),
            ("assistant_response", "🤖 AI Output"),
            ("user_selection", "✨ Highlight"),
            ("direct", "📝 Notes"),
            ("clipboard", "📋 Clipboard"),
        ]

        for s_key, label in chips:
            btn = ctk.CTkButton(
                chips_row,
                text=label,
                font=FONT_SMALL,
                height=24,
                fg_color="transparent",
                text_color=COLOR_TEXT_MUTED,
                hover_color="#1a2235",
                corner_radius=12,
                command=lambda k=s_key: self._select_source_filter(k),
            )
            btn.pack(side="left", padx=(0, 4))
            self.source_chip_buttons[s_key] = btn

        self.source_chip_buttons["all"].configure(fg_color=COLOR_PRIMARY, text_color="#ffffff")

        # 3. Split-Pane Container (Master List on Left, Detail Reader on Right)
        split_pane = ctk.CTkFrame(frame, fg_color="transparent")
        split_pane.grid(row=2, column=0, sticky="nsew")
        split_pane.grid_columnconfigure(0, weight=0, minsize=400)
        split_pane.grid_columnconfigure(1, weight=1)
        split_pane.grid_rowconfigure(0, weight=1)

        # Left Column: Feed Cards
        self.feed_scroll = ctk.CTkScrollableFrame(split_pane, width=410, fg_color="transparent")
        self.feed_scroll.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        self.feed_scroll.grid_columnconfigure(0, weight=1)

        # Right Column: Detail Inspector Card
        self.detail_frame = ctk.CTkFrame(split_pane, fg_color=COLOR_BG_CARD, corner_radius=10, border_width=1, border_color=COLOR_BORDER)
        self.detail_frame.grid(row=0, column=1, sticky="nsew")
        self._build_detail_inspector(self.detail_frame, "feed")

    def _build_detail_inspector(self, container: ctk.CTkFrame, prefix: str = "feed") -> None:
        """Construct the Right Detail Reader Pane.

        Uses prefix-based attr naming (e.g., feed_detail_textbox, vault_detail_textbox)
        to prevent the bug where vault inspector overwrites feed inspector references.
        """
        container.grid_columnconfigure(0, weight=1)
        container.grid_rowconfigure(2, weight=1)

        # Top Meta Bar
        top_bar = ctk.CTkFrame(container, fg_color="transparent")
        top_bar.grid(row=0, column=0, sticky="ew", padx=16, pady=(14, 6))
        setattr(self, f"{prefix}_detail_top_bar", top_bar)

        quad_pill = ctk.CTkLabel(
            top_bar,
            text="📌 Context",
            font=FONT_CAPTION_B,
            text_color="#a5b4fc",
            fg_color="#1a1740",
            corner_radius=6,
            padx=8,
            pady=2,
        )
        quad_pill.pack(side="left", padx=(0, 8))
        setattr(self, f"{prefix}_detail_quad_pill", quad_pill)

        src_badge = ctk.CTkLabel(
            top_bar,
            text="🌐 browser",
            font=FONT_SMALL,
            text_color=COLOR_TEXT_MUTED,
            fg_color=COLOR_BG_MAIN,
            corner_radius=5,
            padx=8,
            pady=2,
        )
        src_badge.pack(side="left", padx=(0, 8))
        setattr(self, f"{prefix}_detail_src_badge", src_badge)

        time_lbl = ctk.CTkLabel(
            top_bar,
            text="",
            font=FONT_SMALL,
            text_color=COLOR_TEXT_SUBTLE,
        )
        time_lbl.pack(side="right")
        setattr(self, f"{prefix}_detail_time_lbl", time_lbl)

        # Action Buttons Row
        action_bar = ctk.CTkFrame(container, fg_color="transparent")
        action_bar.grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 10))
        setattr(self, f"{prefix}_detail_action_bar", action_bar)

        btn_copy = ctk.CTkButton(
            action_bar,
            text="📋 Copy Context",
            font=FONT_CAPTION_B,
            height=28,
            fg_color=COLOR_PRIMARY,
            hover_color=COLOR_PRIMARY_HOVER,
            corner_radius=6,
            command=self._handle_copy_selected_context,
        )
        btn_copy.pack(side="left", padx=(0, 6))
        setattr(self, f"{prefix}_btn_copy_context", btn_copy)

        btn_prime = ctk.CTkButton(
            action_bar,
            text="⚡ Prime Task",
            font=FONT_CAPTION,
            height=28,
            fg_color="#1a2235",
            hover_color="#2a3550",
            corner_radius=6,
            command=self._handle_prime_from_selected,
        )
        btn_prime.pack(side="left", padx=(0, 6))

        btn_url = ctk.CTkButton(
            action_bar,
            text="🌐 Open Site",
            font=FONT_CAPTION,
            height=28,
            fg_color="#1a2235",
            hover_color="#2a3550",
            corner_radius=6,
            command=self._handle_open_selected_url,
        )
        btn_url.pack(side="left", padx=(0, 6))
        setattr(self, f"{prefix}_btn_open_url", btn_url)

        btn_del = ctk.CTkButton(
            action_bar,
            text="🗑️ Delete",
            font=FONT_CAPTION,
            height=28,
            width=70,
            fg_color="#1a2235",
            hover_color="#ef4444",
            corner_radius=6,
            command=self._handle_delete_selected_entry,
        )
        btn_del.pack(side="right")

        # Context Reader Textbox
        textbox = ctk.CTkTextbox(
            container,
            font=FONT_BODY,
            fg_color=COLOR_BG_INSPECTOR,
            border_width=1,
            border_color=COLOR_BORDER,
            wrap="word",
            corner_radius=8,
        )
        textbox.grid(row=2, column=0, sticky="nsew", padx=16, pady=(0, 10))
        setattr(self, f"{prefix}_detail_textbox", textbox)

        # Bottom Meta Footer
        meta_box = ctk.CTkFrame(container, fg_color=COLOR_BG_MAIN, corner_radius=8, border_width=1, border_color=COLOR_BORDER)
        meta_box.grid(row=3, column=0, sticky="ew", padx=16, pady=(0, 14))
        setattr(self, f"{prefix}_detail_meta_box", meta_box)

        meta_lbl = ctk.CTkLabel(
            meta_box,
            text="Select any memory to view details.",
            font=FONT_SMALL,
            text_color=COLOR_TEXT_MUTED,
            anchor="w",
            padx=10,
            pady=6,
        )
        meta_lbl.pack(fill="x")
        setattr(self, f"{prefix}_detail_meta_lbl", meta_lbl)

        # Also set unprefixed aliases pointing to the currently active inspector
        # (for backward compatibility with action handlers)
        if prefix == "feed":
            self.detail_top_bar = top_bar
            self.detail_action_bar = action_bar
            self.detail_textbox = textbox
            self.detail_meta_box = meta_box
            self.detail_meta_lbl = meta_lbl
            self.detail_quad_pill = quad_pill
            self.detail_src_badge = src_badge
            self.detail_time_lbl = time_lbl
            self.btn_copy_context = btn_copy
            self.btn_open_url = btn_url

        # Set default empty state
        self._set_inspector_empty_state_for(prefix)

    def _get_inspector_widgets(self, prefix: str) -> dict:
        """Get all inspector widgets for a given prefix."""
        return {
            "top_bar": getattr(self, f"{prefix}_detail_top_bar", None),
            "action_bar": getattr(self, f"{prefix}_detail_action_bar", None),
            "textbox": getattr(self, f"{prefix}_detail_textbox", None),
            "meta_box": getattr(self, f"{prefix}_detail_meta_box", None),
            "meta_lbl": getattr(self, f"{prefix}_detail_meta_lbl", None),
            "quad_pill": getattr(self, f"{prefix}_detail_quad_pill", None),
            "src_badge": getattr(self, f"{prefix}_detail_src_badge", None),
            "time_lbl": getattr(self, f"{prefix}_detail_time_lbl", None),
            "btn_copy": getattr(self, f"{prefix}_btn_copy_context", None),
            "btn_url": getattr(self, f"{prefix}_btn_open_url", None),
        }

    def _set_active_inspector(self, prefix: str) -> None:
        """Point unprefixed aliases to the specified inspector's widgets."""
        w = self._get_inspector_widgets(prefix)
        self.detail_top_bar = w["top_bar"]
        self.detail_action_bar = w["action_bar"]
        self.detail_textbox = w["textbox"]
        self.detail_meta_box = w["meta_box"]
        self.detail_meta_lbl = w["meta_lbl"]
        self.detail_quad_pill = w["quad_pill"]
        self.detail_src_badge = w["src_badge"]
        self.detail_time_lbl = w["time_lbl"]
        self.btn_copy_context = w["btn_copy"]
        self.btn_open_url = w["btn_url"]

    def _set_inspector_empty_state_for(self, prefix: str) -> None:
        """Render empty placeholder for a specific inspector prefix."""
        w = self._get_inspector_widgets(prefix)
        if w["top_bar"]:
            w["top_bar"].grid_remove()
        if w["action_bar"]:
            w["action_bar"].grid_remove()
        if w["meta_box"]:
            w["meta_box"].grid_remove()
        if w["textbox"]:
            w["textbox"].delete("1.0", "end")
            empty_guide = (
                "\n\n\n"
                "          🦉  Select a Memory\n\n"
                "     Click any card on the left to inspect:\n\n"
                "     •  Full uncropped context & prompt history\n"
                "     •  Source URLs, tokens & timestamps\n"
                "     •  1-Click copy for Cursor, Claude & ChatGPT\n"
                "     •  Instant task priming with ⚡ Prime Task\n\n"
                "     💡  Cards appear in real-time as you\n"
                "         browse, code, and capture!\n"
            )
            w["textbox"].insert("end", empty_guide)

    def _set_inspector_empty_state(self) -> None:
        """Render empty placeholder in the currently active inspector."""
        prefix = "vault" if self.current_view == "vault" else "feed"
        self._set_inspector_empty_state_for(prefix)
        self.selected_entry = None

    def _show_detail_inspector(self, entry: Dict[str, Any]) -> None:
        """Display selected memory in the right detail pane."""
        # Ensure we're writing to the correct inspector (feed vs vault)
        prefix = "vault" if self.current_view == "vault" else "feed"
        self._set_active_inspector(prefix)

        self.selected_entry = entry
        self.detail_top_bar.grid()
        self.detail_action_bar.grid()
        self.detail_meta_box.grid()

        raw_text = entry.get("raw_text") or ""
        summary = entry.get("summary") or ""
        quadrant = (entry.get("quadrant") or "context").lower()
        source_app = entry.get("source_app") or "browser"
        timestamp = (entry.get("timestamp") or "")[:19].replace("T", " ")
        project_name = entry.get("project_name") or "General"
        eid = entry.get("id")

        metadata = entry.get("source_metadata") or {}
        if isinstance(metadata, str):
            try:
                metadata = json.loads(metadata)
            except Exception:
                metadata = {}

        # Update Top Bar
        quad_labels = {
            "technical_architecture": ("🏗️ Technical Architecture", "#1e1b4b", "#a5b4fc"),
            "business_rules": ("💼 Business Rules", "#064e3b", "#6ee7b7"),
            "settled_decisions": ("🔒 Settled Decisions", "#3b0764", "#d8b4fe"),
            "open_questions": ("❓ Open Questions", "#451a03", "#fde68a"),
        }
        q_label, q_bg, q_fg = quad_labels.get(quadrant, ("📌 General Context", "#1e293b", "#cbd5e1"))
        self.detail_quad_pill.configure(text=q_label, fg_color=q_bg, text_color=q_fg)
        self.detail_src_badge.configure(text=f"📁 {project_name} · {source_app}")
        self.detail_time_lbl.configure(text=timestamp)

        # Update URL button state
        url = metadata.get("url") or ""
        if url:
            self.btn_open_url.configure(state="normal", text="🌐 Open URL")
        else:
            self.btn_open_url.configure(state="disabled", text="🌐 No URL")

        # Update Content
        self.detail_textbox.delete("1.0", "end")
        if summary:
            self.detail_textbox.insert("end", f"SUMMARY: {summary}\n\n{'─' * 55}\n\n")
        self.detail_textbox.insert("end", raw_text)

        # Update Meta Footer
        word_count = len(raw_text.split())
        c_type = metadata.get("container_type") or metadata.get("type") or "standard"
        self.detail_meta_lbl.configure(
            text=f"Entry #{eid} | Type: {c_type} | Words: {word_count} | Domain: {project_name}"
        )

        # Update card selection visual states
        for card in self.feed_cards + self.vault_cards:
            card.set_selected(card.entry.get("id") == eid)

    def _handle_copy_selected_context(self) -> None:
        if not self.selected_entry:
            return
        raw_text = self.selected_entry.get("raw_text") or ""
        copy_to_clipboard(raw_text)
        self.btn_copy_context.configure(text="✓ Copied!", fg_color=COLOR_SUCCESS)
        self.after(1500, lambda: self.btn_copy_context.configure(text="📋 Copy Context", fg_color=COLOR_PRIMARY))

    def _handle_prime_from_selected(self) -> None:
        if not self.selected_entry:
            return
        summary = self.selected_entry.get("summary") or self.selected_entry.get("raw_text", "")[:60]
        self.show_view("primer")
        self.primer_query_entry.delete(0, "end")
        self.primer_query_entry.insert(0, summary)
        self._handle_generate_primer()

    def _handle_open_selected_url(self) -> None:
        if not self.selected_entry:
            return
        metadata = self.selected_entry.get("source_metadata") or {}
        if isinstance(metadata, str):
            try:
                metadata = json.loads(metadata)
            except Exception:
                metadata = {}
        url = metadata.get("url")
        if url:
            webbrowser.open(url)

    def _handle_delete_selected_entry(self) -> None:
        if not self.selected_entry:
            return
        eid = self.selected_entry.get("id")
        if eid:
            self._handle_delete_entry(int(eid))
            self._set_inspector_empty_state()

    def _on_search_key_release(self, event) -> None:
        """Debounce search-as-you-type to prevent UI stutter."""
        if self._search_debounce_timer:
            self.after_cancel(self._search_debounce_timer)
        self._search_debounce_timer = self.after(250, self.refresh_feed)

    def _select_source_filter(self, source_key: str) -> None:
        self.filter_source = source_key
        for k, btn in self.source_chip_buttons.items():
            if k == source_key:
                btn.configure(fg_color=COLOR_PRIMARY, text_color="#ffffff")
            else:
                btn.configure(fg_color="transparent", text_color=COLOR_TEXT_MUTED)
        self.refresh_feed()

    # -------------------------------------------------------------
    # View 2: 📥 Quick Dump Box
    # -------------------------------------------------------------
    def _build_quick_dump_view(self) -> None:
        frame = ctk.CTkFrame(self.content_container, fg_color="transparent")
        self.views["quick_dump"] = frame
        frame.grid_columnconfigure(0, weight=1)

        title_card = ctk.CTkFrame(frame, fg_color=COLOR_BG_CARD, corner_radius=10, border_width=1, border_color=COLOR_BORDER)
        title_card.pack(fill="x", pady=(0, 12), padx=4)

        ctk.CTkLabel(
            title_card,
            text="📥 Quick Memory Dump",
            font=FONT_HEADING,
            text_color=COLOR_TEXT,
            anchor="w",
        ).pack(fill="x", padx=16, pady=(14, 2))

        ctk.CTkLabel(
            title_card,
            text="Instantly paste thoughts, meeting notes, code snippets, or links. OwlThread will extract durable facts into memory quadrants.",
            font=FONT_CAPTION,
            text_color=COLOR_TEXT_MUTED,
            anchor="w",
        ).pack(fill="x", padx=16, pady=(0, 14))

        input_card = ctk.CTkFrame(frame, fg_color=COLOR_BG_CARD, corner_radius=10, border_width=1, border_color=COLOR_BORDER)
        input_card.pack(fill="both", expand=True, padx=4)

        proj_row = ctk.CTkFrame(input_card, fg_color="transparent")
        proj_row.pack(fill="x", padx=16, pady=(14, 8))

        ctk.CTkLabel(
            proj_row,
            text="Project Name:",
            font=FONT_CAPTION_B,
            text_color=COLOR_TEXT,
        ).pack(side="left", padx=(0, 8))

        self.dump_project_entry = ctk.CTkEntry(
            proj_row,
            placeholder_text="e.g. General, StripeBilling, AuthEngine",
            font=FONT_CAPTION,
            width=260,
            fg_color=COLOR_BG_INPUT,
            border_color=COLOR_BORDER,
            corner_radius=8,
        )
        self.dump_project_entry.pack(side="left")

        self.dump_textbox = ctk.CTkTextbox(
            input_card,
            font=FONT_BODY,
            fg_color=COLOR_BG_INPUT,
            border_width=1,
            border_color=COLOR_BORDER,
            corner_radius=8,
            wrap="word",
        )
        self.dump_textbox.pack(fill="both", expand=True, padx=16, pady=(0, 12))

        action_row = ctk.CTkFrame(input_card, fg_color="transparent")
        action_row.pack(fill="x", padx=16, pady=(0, 14))

        self.dump_status_lbl = ctk.CTkLabel(
            action_row,
            text="",
            font=FONT_CAPTION,
            text_color=COLOR_SUCCESS,
        )
        self.dump_status_lbl.pack(side="left")

        dump_submit_btn = ctk.CTkButton(
            action_row,
            text="⚡ Dump into Memory",
            font=FONT_TITLE,
            fg_color=COLOR_PRIMARY,
            hover_color=COLOR_PRIMARY_HOVER,
            corner_radius=8,
            height=34,
            command=self._handle_submit_quick_dump,
        )
        dump_submit_btn.pack(side="right")

    def _handle_submit_quick_dump(self) -> None:
        raw_text = self.dump_textbox.get("1.0", "end").strip()
        if not raw_text:
            self.dump_status_lbl.configure(text="⚠️ Please write or paste some text first.", text_color=COLOR_DANGER)
            return

        project_name = self.dump_project_entry.get().strip() or "General"
        self.dump_status_lbl.configure(text="Extracting durable knowledge...", text_color=COLOR_ACCENT)

        def _worker():
            try:
                extracted = self.pipeline.flush_and_extract_text_immediately(
                    raw_text=raw_text,
                    source_app="direct",
                    project_name=project_name,
                )
                self.after(0, lambda: self._on_quick_dump_success(len(extracted)))
            except Exception as e:
                logger.error("Error in quick dump: %s", e)
                self.after(0, lambda: self.dump_status_lbl.configure(text=f"❌ Error: {e}", text_color=COLOR_DANGER))

        threading.Thread(target=_worker, daemon=True).start()

    def _on_quick_dump_success(self, count: int) -> None:
        self.dump_textbox.delete("1.0", "end")
        self.dump_status_lbl.configure(
            text=f"✅ Dumped! Extracted {count} knowledge items.",
            text_color=COLOR_SUCCESS
        )
        self.refresh_feed()
        self._update_status_counts()

    # -------------------------------------------------------------
    # View 3: 🗂️ Knowledge Vault (4 Quadrants)
    # -------------------------------------------------------------
    def _build_vault_view(self) -> None:
        frame = ctk.CTkFrame(self.content_container, fg_color="transparent")
        self.views["vault"] = frame
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(1, weight=1)

        quad_bar = ctk.CTkFrame(frame, fg_color=COLOR_BG_CARD, corner_radius=10, border_width=1, border_color=COLOR_BORDER)
        quad_bar.grid(row=0, column=0, sticky="ew", pady=(0, 12))

        self.vault_buttons: Dict[str, ctk.CTkButton] = {}
        quadrants = [
            ("all", "All Vault"),
            ("technical_architecture", "🏗️ Architecture"),
            ("business_rules", "💼 Business Rules"),
            ("settled_decisions", "🔒 Decisions"),
            ("open_questions", "❓ Open Questions"),
        ]

        for q_key, label in quadrants:
            btn = ctk.CTkButton(
                quad_bar,
                text=label,
                font=FONT_CAPTION_B,
                fg_color="transparent",
                text_color=COLOR_TEXT_MUTED,
                hover_color="#1a2235",
                corner_radius=8,
                command=lambda k=q_key: self._select_vault_quadrant(k),
            )
            btn.pack(side="left", padx=6, pady=8)
            self.vault_buttons[q_key] = btn

        self.vault_buttons["all"].configure(fg_color=COLOR_PRIMARY, text_color="#ffffff")

        # Split Pane for Vault
        split_pane = ctk.CTkFrame(frame, fg_color="transparent")
        split_pane.grid(row=1, column=0, sticky="nsew")
        split_pane.grid_columnconfigure(0, weight=0, minsize=400)
        split_pane.grid_columnconfigure(1, weight=1)
        split_pane.grid_rowconfigure(0, weight=1)

        self.vault_scroll = ctk.CTkScrollableFrame(split_pane, width=410, fg_color="transparent")
        self.vault_scroll.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        self.vault_scroll.grid_columnconfigure(0, weight=1)

        self.vault_detail_frame = ctk.CTkFrame(split_pane, fg_color=COLOR_BG_CARD, corner_radius=10, border_width=1, border_color=COLOR_BORDER)
        self.vault_detail_frame.grid(row=0, column=1, sticky="nsew")
        self._build_detail_inspector(self.vault_detail_frame, "vault")

    def _select_vault_quadrant(self, quadrant_key: str) -> None:
        self.selected_quadrant = quadrant_key
        for key, btn in self.vault_buttons.items():
            if key == quadrant_key:
                btn.configure(fg_color=COLOR_PRIMARY, text_color=COLOR_TEXT)
            else:
                btn.configure(fg_color="transparent", text_color=COLOR_TEXT_MUTED)
        self.refresh_feed()

    # -------------------------------------------------------------
    # View 4: 🌐 Site Access Manager (2-Way Extension Coordination)
    # -------------------------------------------------------------
    def _build_sites_view(self) -> None:
        frame = ctk.CTkFrame(self.content_container, fg_color="transparent")
        self.views["sites"] = frame
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(1, weight=1)

        # Header Card
        hdr = ctk.CTkFrame(frame, fg_color=COLOR_BG_CARD, corner_radius=10, border_width=1, border_color=COLOR_BORDER)
        hdr.grid(row=0, column=0, sticky="ew", pady=(0, 10))

        ctk.CTkLabel(
            hdr,
            text="🌐 Site Access Manager (2-Way Extension Sync)",
            font=FONT_HEADING,
            text_color=COLOR_TEXT,
            anchor="w",
        ).pack(fill="x", padx=16, pady=(14, 2))

        ctk.CTkLabel(
            hdr,
            text="Manage which websites OwlThread reads from. Changes sync immediately with the browser extension!",
            font=FONT_CAPTION,
            text_color=COLOR_TEXT_MUTED,
            anchor="w",
        ).pack(fill="x", padx=16, pady=(0, 14))

        # Sites Scrollable List
        self.sites_scroll = ctk.CTkScrollableFrame(frame, fg_color="transparent")
        self.sites_scroll.grid(row=1, column=0, sticky="nsew")
        self.sites_scroll.grid_columnconfigure(0, weight=1)

    def refresh_sites_view(self) -> None:
        """Fetch all sites permissions from database settings and display with toggles."""
        for w in self.sites_scroll.winfo_children():
            w.destroy()

        sites_json = self.db.get_setting("site_permissions", "{}")
        try:
            sites_data = json.loads(sites_json) if sites_json else {}
        except Exception:
            sites_data = {}

        # Also pull distinct hostnames seen in memory_entries
        projects = self.db.list_projects()
        for p in projects:
            p_name = p.get("name", "")
            if "." in p_name and p_name not in sites_data:
                sites_data[p_name] = "allowed"

        if not sites_data:
            ctk.CTkLabel(
                self.sites_scroll,
                text="No sites registered yet. Visit any site with the browser extension to see it appear here!",
                font=FONT_BODY,
                text_color=COLOR_TEXT_MUTED,
                pady=40,
            ).pack()
            return

        for hostname, perm in sorted(sites_data.items()):
            row = ctk.CTkFrame(self.sites_scroll, fg_color=COLOR_BG_CARD, corner_radius=8, border_width=1, border_color=COLOR_BORDER)
            row.pack(fill="x", pady=4)

            is_allowed = (perm == "allowed")
            status_text = "🟢 Allowed" if is_allowed else "🔴 Blocked"
            status_color = COLOR_SUCCESS if is_allowed else COLOR_DANGER

            ctk.CTkLabel(
                row,
                text=f"🌐 {hostname}",
                font=FONT_TITLE,
                text_color=COLOR_TEXT,
            ).pack(side="left", padx=14, pady=10)

            ctk.CTkLabel(
                row,
                text=status_text,
                font=FONT_CAPTION_B,
                text_color=status_color,
            ).pack(side="left", padx=10)

            # Toggle button
            new_status = "blocked" if is_allowed else "allowed"
            toggle_text = "🚫 Block Site" if is_allowed else "✓ Allow Site"
            toggle_color = "#1a2235" if is_allowed else COLOR_SUCCESS

            btn = ctk.CTkButton(
                row,
                text=toggle_text,
                font=FONT_SMALL_B,
                width=100,
                height=26,
                fg_color=toggle_color,
                hover_color="#ef4444" if is_allowed else "#16a34a",
                corner_radius=6,
                command=lambda h=hostname, s=new_status: self._toggle_site_permission(h, s),
            )
            btn.pack(side="right", padx=14, pady=10)

    def _toggle_site_permission(self, hostname: str, new_status: str) -> None:
        """Update permission in DB so extension immediately coordinates."""
        sites_json = self.db.get_setting("site_permissions", "{}")
        try:
            sites_data = json.loads(sites_json) if sites_json else {}
        except Exception:
            sites_data = {}

        sites_data[hostname] = new_status
        self.db.set_setting("site_permissions", json.dumps(sites_data))
        self.refresh_sites_view()
        self._flash_status_beacon(f"{hostname} set to {new_status}!", COLOR_SUCCESS)

    # -------------------------------------------------------------
    # View 5: ⚡ Primer & Query Engine
    # -------------------------------------------------------------
    def _build_primer_view(self) -> None:
        frame = ctk.CTkFrame(self.content_container, fg_color="transparent")
        self.views["primer"] = frame
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(2, weight=1)

        head_card = ctk.CTkFrame(frame, fg_color=COLOR_BG_CARD, corner_radius=10, border_width=1, border_color=COLOR_BORDER)
        head_card.grid(row=0, column=0, sticky="ew", pady=(0, 10))

        ctk.CTkLabel(
            head_card,
            text="⚡ Query & Context Primer Engine",
            font=FONT_HEADING,
            text_color=COLOR_TEXT,
            anchor="w",
        ).pack(fill="x", padx=16, pady=(14, 2))

        ctk.CTkLabel(
            head_card,
            text="State your task — OwlThread will compile relevant project memory into a context brief ready to paste into your AI assistant.",
            font=FONT_CAPTION,
            text_color=COLOR_TEXT_MUTED,
            anchor="w",
        ).pack(fill="x", padx=16, pady=(0, 14))

        input_card = ctk.CTkFrame(frame, fg_color=COLOR_BG_CARD, corner_radius=10, border_width=1, border_color=COLOR_BORDER)
        input_card.grid(row=1, column=0, sticky="ew", pady=(0, 10))

        row1 = ctk.CTkFrame(input_card, fg_color="transparent")
        row1.pack(fill="x", padx=16, pady=14)

        self.primer_query_entry = ctk.CTkEntry(
            row1,
            placeholder_text="What are you about to do? e.g. integrate Stripe billing, audit release, send pitch...",
            font=FONT_BODY,
            fg_color=COLOR_BG_INPUT,
            border_color=COLOR_BORDER,
            corner_radius=8,
        )
        self.primer_query_entry.pack(side="left", fill="x", expand=True, padx=(0, 10))
        self.primer_query_entry.bind("<Return>", lambda e: self._handle_generate_primer())

        gen_btn = ctk.CTkButton(
            row1,
            text="🚀 Generate Primer",
            font=FONT_TITLE,
            fg_color=COLOR_PRIMARY,
            hover_color=COLOR_PRIMARY_HOVER,
            corner_radius=8,
            height=34,
            command=self._handle_generate_primer,
        )
        gen_btn.pack(side="right")

        output_card = ctk.CTkFrame(frame, fg_color=COLOR_BG_CARD, corner_radius=10, border_width=1, border_color=COLOR_BORDER)
        output_card.grid(row=2, column=0, sticky="nsew")
        output_card.grid_columnconfigure(0, weight=1)
        output_card.grid_rowconfigure(1, weight=1)

        out_header = ctk.CTkFrame(output_card, fg_color="transparent")
        out_header.grid(row=0, column=0, sticky="ew", padx=16, pady=(12, 4))

        self.primer_meta_lbl = ctk.CTkLabel(
            out_header,
            text="Ready to generate primer context.",
            font=FONT_CAPTION,
            text_color=COLOR_TEXT_MUTED,
        )
        self.primer_meta_lbl.pack(side="left")

        self.copy_primer_btn = ctk.CTkButton(
            out_header,
            text="📋 Copy to Clipboard",
            font=FONT_CAPTION_B,
            width=140,
            height=28,
            fg_color="#1a2235",
            hover_color="#2a3550",
            corner_radius=6,
            command=self._handle_copy_primer,
        )
        self.copy_primer_btn.pack(side="right")

        self.primer_output_text = ctk.CTkTextbox(
            output_card,
            font=FONT_BODY,
            fg_color=COLOR_BG_INPUT,
            border_width=1,
            border_color=COLOR_BORDER,
            corner_radius=8,
            wrap="word",
        )
        self.primer_output_text.grid(row=1, column=0, sticky="nsew", padx=16, pady=(0, 16))

    def _handle_generate_primer(self) -> None:
        query = self.primer_query_entry.get().strip()
        if not query:
            return

        self.primer_meta_lbl.configure(text="Compiling contextual primer...", text_color=COLOR_ACCENT)
        self.primer_output_text.delete("1.0", "end")
        self.primer_output_text.insert("end", "Gathering relevant memories and compiling brief...")

        def _worker():
            try:
                res = self.primer_engine.generate_primer(user_request=query, auto_copy=True)
                self.after(0, lambda: self._on_primer_generated(res))
            except Exception as e:
                logger.error("Primer error: %s", e)
                self.after(0, lambda: self.primer_meta_lbl.configure(text=f"Error: {e}", text_color=COLOR_DANGER))

        threading.Thread(target=_worker, daemon=True).start()

    def _on_primer_generated(self, res) -> None:
        self.primer_output_text.delete("1.0", "end")
        self.primer_output_text.insert("end", res.primer_text)
        self.primer_meta_lbl.configure(
            text=f"Intent: {res.intent} | Matched: {len(res.matched_entries)} entries | Copied to clipboard ✓",
            text_color=COLOR_SUCCESS
        )

    def _handle_copy_primer(self) -> None:
        text = self.primer_output_text.get("1.0", "end").strip()
        if text:
            copy_to_clipboard(text)
            self.copy_primer_btn.configure(text="✓ Copied!", fg_color="#16a34a")
            self.after(1500, lambda: self.copy_primer_btn.configure(text="📋 Copy to Clipboard", fg_color="#334155"))

    # -------------------------------------------------------------
    # View 6: ⚙️ AI Engine, Prompts & Settings
    # -------------------------------------------------------------
    def _build_settings_view(self) -> None:
        frame = ctk.CTkFrame(self.content_container, fg_color="transparent")
        self.views["settings"] = frame
        frame.grid_columnconfigure(0, weight=1)

        card = ctk.CTkScrollableFrame(frame, fg_color=COLOR_BG_CARD, corner_radius=10, border_width=1, border_color=COLOR_BORDER)
        card.pack(fill="both", expand=True, padx=4)

        # 1. AI Engine Configuration Section
        ctk.CTkLabel(
            card,
            text="🤖 AI Extraction & Synthesis Engine",
            font=FONT_HEADING,
            text_color=COLOR_TEXT,
            anchor="w",
        ).pack(fill="x", padx=16, pady=(14, 2))

        ctk.CTkLabel(
            card,
            text="Select which AI model handles knowledge extraction, categorization, and context primers. Supports Gemini (Free), OpenAI, Claude, and local Ollama.",
            font=FONT_CAPTION,
            text_color=COLOR_TEXT_MUTED,
            anchor="w",
        ).pack(fill="x", padx=16, pady=(0, 12))

        # Provider Selector
        row_p = ctk.CTkFrame(card, fg_color="transparent")
        row_p.pack(fill="x", padx=16, pady=4)
        ctk.CTkLabel(row_p, text="Provider:", font=FONT_CAPTION_B, width=90, anchor="w", text_color=COLOR_TEXT_MUTED).pack(side="left")
        self.ai_provider_menu = ctk.CTkOptionMenu(
            row_p,
            values=["Google Gemini (Free Tier)", "OpenAI (GPT-4o-mini)", "Anthropic (Claude 3.5)", "Ollama (Localhost)", "Offline Heuristic"],
            font=FONT_CAPTION,
            width=240,
            fg_color="#1a2235",
            button_color=COLOR_PRIMARY,
            corner_radius=8,
            command=self._on_provider_selected,
        )
        self.ai_provider_menu.pack(side="left")

        # API Key Input
        row_k = ctk.CTkFrame(card, fg_color="transparent")
        row_k.pack(fill="x", padx=16, pady=4)
        ctk.CTkLabel(row_k, text="API Key:", font=FONT_CAPTION_B, width=90, anchor="w", text_color=COLOR_TEXT_MUTED).pack(side="left")
        self.ai_key_entry = ctk.CTkEntry(row_k, font=FONT_CAPTION, width=340, show="•", fg_color=COLOR_BG_INPUT, border_color=COLOR_BORDER, corner_radius=8)
        self.ai_key_entry.pack(side="left", padx=(0, 6))

        self.btn_toggle_key = ctk.CTkButton(
            row_k,
            text="👁️",
            width=32,
            height=28,
            fg_color="#1a2235",
            hover_color="#2a3550",
            corner_radius=6,
            command=self._toggle_key_visibility,
        )
        self.btn_toggle_key.pack(side="left")

        # Model Input
        row_m = ctk.CTkFrame(card, fg_color="transparent")
        row_m.pack(fill="x", padx=16, pady=4)
        ctk.CTkLabel(row_m, text="Model Name:", font=FONT_CAPTION_B, width=90, anchor="w", text_color=COLOR_TEXT_MUTED).pack(side="left")
        self.ai_model_entry = ctk.CTkEntry(row_m, font=FONT_CAPTION, width=240, fg_color=COLOR_BG_INPUT, border_color=COLOR_BORDER, corner_radius=8)
        self.ai_model_entry.pack(side="left")

        # Base URL Input (for Ollama / OpenRouter)
        row_u = ctk.CTkFrame(card, fg_color="transparent")
        row_u.pack(fill="x", padx=16, pady=4)
        ctk.CTkLabel(row_u, text="Base URL:", font=FONT_CAPTION_B, width=90, anchor="w", text_color=COLOR_TEXT_MUTED).pack(side="left")
        self.ai_url_entry = ctk.CTkEntry(row_u, font=FONT_CAPTION, width=280, placeholder_text="e.g. http://localhost:11434/v1", fg_color=COLOR_BG_INPUT, border_color=COLOR_BORDER, corner_radius=8)
        self.ai_url_entry.pack(side="left")

        # AI Action Buttons (Test & Save)
        ai_btn_row = ctk.CTkFrame(card, fg_color="transparent")
        ai_btn_row.pack(fill="x", padx=16, pady=(10, 16))

        self.btn_test_ai = ctk.CTkButton(
            ai_btn_row,
            text="⚡ Test Connection",
            font=FONT_CAPTION_B,
            height=28,
            fg_color="#1a2235",
            hover_color="#2a3550",
            corner_radius=6,
            command=self._handle_test_ai_connection,
        )
        self.btn_test_ai.pack(side="left", padx=(0, 8))

        self.btn_save_ai = ctk.CTkButton(
            ai_btn_row,
            text="💾 Save AI Engine",
            font=FONT_CAPTION_B,
            height=28,
            fg_color=COLOR_PRIMARY,
            hover_color=COLOR_PRIMARY_HOVER,
            corner_radius=6,
            command=self._handle_save_ai_settings,
        )
        self.btn_save_ai.pack(side="left", padx=(0, 10))

        self.ai_status_badge = ctk.CTkLabel(ai_btn_row, text="", font=FONT_SMALL_B, text_color=COLOR_SUCCESS)
        self.ai_status_badge.pack(side="left")

        # Divider
        ctk.CTkFrame(card, height=1, fg_color=COLOR_BORDER).pack(fill="x", padx=16, pady=10)

        # 2. System Prompts Section
        ctk.CTkLabel(
            card,
            text="🧠 System Prompts",
            font=FONT_HEADING,
            text_color=COLOR_TEXT,
            anchor="w",
        ).pack(fill="x", padx=16, pady=(6, 2))

        ctk.CTkLabel(
            card,
            text="Extraction System Prompt (Categorizes raw captures into 4 quadrants):",
            font=FONT_CAPTION_B,
            text_color=COLOR_ACCENT,
            anchor="w",
        ).pack(fill="x", padx=16, pady=(8, 2))

        self.setting_extract_box = ctk.CTkTextbox(card, font=FONT_BODY, fg_color=COLOR_BG_INPUT, border_width=1, border_color=COLOR_BORDER, corner_radius=8, height=90)
        self.setting_extract_box.pack(fill="x", padx=16, pady=(0, 8))

        ctk.CTkLabel(
            card,
            text="Primer Generation System Prompt (Compiles context briefs):",
            font=FONT_CAPTION_B,
            text_color=COLOR_ACCENT,
            anchor="w",
        ).pack(fill="x", padx=16, pady=(6, 2))

        self.setting_primer_box = ctk.CTkTextbox(card, font=FONT_BODY, fg_color=COLOR_BG_INPUT, border_width=1, border_color=COLOR_BORDER, corner_radius=8, height=90)
        self.setting_primer_box.pack(fill="x", padx=16, pady=(0, 10))

        save_p_btn = ctk.CTkButton(
            card,
            text="💾 Save Prompts",
            font=FONT_CAPTION_B,
            height=28,
            fg_color=COLOR_PRIMARY,
            hover_color=COLOR_PRIMARY_HOVER,
            corner_radius=6,
            command=self._handle_save_prompts,
        )
        save_p_btn.pack(anchor="w", padx=16, pady=(0, 16))

        # Divider
        ctk.CTkFrame(card, height=1, fg_color=COLOR_BORDER).pack(fill="x", padx=16, pady=6)

        # 3. Danger Zone Section
        danger_card = ctk.CTkFrame(card, fg_color="#180b0b", border_width=1, border_color="#5f1d1d", corner_radius=10)
        danger_card.pack(fill="x", padx=16, pady=(10, 14))

        ctk.CTkLabel(
            danger_card,
            text="⚠️ Danger Zone — Clean / Wipe Database",
            font=FONT_TITLE,
            text_color=COLOR_DANGER,
            anchor="w",
        ).pack(fill="x", padx=14, pady=(12, 4))

        ctk.CTkLabel(
            danger_card,
            text="Permanently clear all memory entries and start fresh with 0 entries. Settings and AI keys will be preserved.",
            font=FONT_SMALL,
            text_color=COLOR_TEXT_MUTED,
            anchor="w",
        ).pack(fill="x", padx=14, pady=(0, 12))

        reset_btn = ctk.CTkButton(
            danger_card,
            text="🗑️ Wipe Database / Clear All Data",
            font=FONT_CAPTION_B,
            fg_color=COLOR_DANGER,
            hover_color="#dc2626",
            corner_radius=6,
            command=self._handle_reset_database,
        )
        reset_btn.pack(anchor="w", padx=14, pady=(0, 14))

    def _toggle_key_visibility(self) -> None:
        self._key_visible = not self._key_visible
        self.ai_key_entry.configure(show="" if self._key_visible else "•")
        self.btn_toggle_key.configure(text="🔒" if self._key_visible else "👁️")

    def _on_provider_selected(self, choice: str) -> None:
        c_low = choice.lower()
        if "gemini" in c_low:
            self.ai_model_entry.delete(0, "end")
            self.ai_model_entry.insert(0, "gemini-2.0-flash")
            self.ai_url_entry.delete(0, "end")
        elif "openai" in c_low:
            self.ai_model_entry.delete(0, "end")
            self.ai_model_entry.insert(0, "gpt-4o-mini")
            self.ai_url_entry.delete(0, "end")
        elif "claude" in c_low:
            self.ai_model_entry.delete(0, "end")
            self.ai_model_entry.insert(0, "claude-3-5-haiku-latest")
            self.ai_url_entry.delete(0, "end")
        elif "ollama" in c_low:
            self.ai_model_entry.delete(0, "end")
            self.ai_model_entry.insert(0, "llama3")
            self.ai_url_entry.delete(0, "end")
            self.ai_url_entry.insert(0, "http://localhost:11434/v1")

    def _load_settings_into_inputs(self) -> None:
        # Load AI settings
        db_provider = self.db.get_setting("llm_provider", "fallback")
        provider_map = {
            "gemini": "Google Gemini (Free Tier)",
            "openai": "OpenAI (GPT-4o-mini)",
            "anthropic": "Anthropic (Claude 3.5)",
            "ollama": "Ollama (Localhost)",
            "fallback": "Offline Heuristic",
        }
        self.ai_provider_menu.set(provider_map.get(db_provider, "Offline Heuristic"))

        key = self.db.get_setting("llm_api_key", "")
        self.ai_key_entry.delete(0, "end")
        self.ai_key_entry.insert(0, key)

        model = self.db.get_setting("llm_model", "")
        self.ai_model_entry.delete(0, "end")
        self.ai_model_entry.insert(0, model or ("gemini-2.0-flash" if db_provider == "gemini" else "gpt-4o-mini"))

        url = self.db.get_setting("llm_base_url", "")
        self.ai_url_entry.delete(0, "end")
        self.ai_url_entry.insert(0, url)

        # Load prompts
        custom_extract = self.db.get_setting("extraction_prompt") or self.pipeline.extractor.active_system_prompt
        custom_primer = self.db.get_setting("primer_prompt") or self.primer_engine.generator.active_system_prompt

        self.setting_extract_box.delete("1.0", "end")
        self.setting_extract_box.insert("end", custom_extract)

        self.setting_primer_box.delete("1.0", "end")
        self.setting_primer_box.insert("end", custom_primer)

    def _handle_save_ai_settings(self) -> None:
        choice = self.ai_provider_menu.get().lower()
        if "gemini" in choice:
            prov = "gemini"
        elif "openai" in choice:
            prov = "openai"
        elif "claude" in choice:
            prov = "anthropic"
        elif "ollama" in choice:
            prov = "ollama"
        else:
            prov = "fallback"

        key = self.ai_key_entry.get().strip()
        model = self.ai_model_entry.get().strip()
        url = self.ai_url_entry.get().strip()

        self.db.set_setting("llm_provider", prov)
        self.db.set_setting("llm_api_key", key)
        self.db.set_setting("llm_model", model)
        self.db.set_setting("llm_base_url", url)

        # Reload clients
        self.pipeline.extractor.llm_client.reload_from_db(self.db)
        self.primer_engine.generator.llm_client.reload_from_db(self.db)

        self.ai_status_badge.configure(text="✓ Saved & Active!", text_color=COLOR_SUCCESS)
        self.after(2500, lambda: self.ai_status_badge.configure(text=""))

    def _handle_test_ai_connection(self) -> None:
        self.btn_test_ai.configure(text="Testing...", state="disabled")
        self.ai_status_badge.configure(text="Connecting to model...", text_color=COLOR_ACCENT)

        # Temporarily apply in-memory settings to test
        self._handle_save_ai_settings()

        def _worker():
            client = self.pipeline.extractor.llm_client
            ok, msg = client.test_connection()
            self.after(0, lambda: self._on_ai_test_finished(ok, msg))

        threading.Thread(target=_worker, daemon=True).start()

    def _on_ai_test_finished(self, ok: bool, msg: str) -> None:
        self.btn_test_ai.configure(text="⚡ Test Connection", state="normal")
        if ok:
            self.ai_status_badge.configure(text=f"🟢 {msg[:45]}", text_color=COLOR_SUCCESS)
        else:
            self.ai_status_badge.configure(text=f"🔴 {msg[:45]}", text_color=COLOR_DANGER)

    def _handle_save_prompts(self) -> None:
        new_extract = self.setting_extract_box.get("1.0", "end").strip()
        new_primer = self.setting_primer_box.get("1.0", "end").strip()

        if new_extract:
            self.db.set_setting("extraction_prompt", new_extract)
            self.pipeline.extractor.custom_system_prompt = new_extract
        if new_primer:
            self.db.set_setting("primer_prompt", new_primer)
            self.primer_engine.generator.custom_system_prompt = new_primer

        messagebox.showinfo("Prompts Saved", "System prompts updated and synced with extension!", parent=self)

    def _handle_reset_database(self) -> None:
        confirm = messagebox.askyesno(
            "Confirm Database Wipe",
            "Are you sure you want to delete ALL captured memories? This cannot be undone.",
            parent=self
        )
        if confirm:
            self.db.clear_entries()
            self._set_inspector_empty_state()
            self.refresh_feed()
            self._update_status_counts()
            messagebox.showinfo("Database Cleared", "All memories have been wiped. You now have a clean database!", parent=self)

    # -------------------------------------------------------------
    # Delete Entry Handler
    # -------------------------------------------------------------
    def _handle_delete_entry(self, entry_id: int) -> None:
        """Delete an individual entry upon user clicking delete button."""
        self.db.delete_entry(entry_id)
        self.refresh_feed()
        self._update_status_counts()
        self._flash_status_beacon(f"Deleted #{entry_id}", COLOR_DANGER)

    # -------------------------------------------------------------
    # Feed Refresh & Filtering
    # -------------------------------------------------------------
    def _on_project_filter_changed(self, choice: str) -> None:
        self.filter_project = choice
        if choice != "All Projects":
            self.db.get_or_create_project(name=choice)
            self.db.set_setting("active_project", choice)
        self.refresh_feed()

    def _handle_create_project_dialog(self) -> None:
        dialog = ctk.CTkInputDialog(
            text="Enter project name (e.g. MySaaS, Billing, MobileApp):",
            title="Create New Project"
        )
        val = dialog.get_input()
        if val and val.strip():
            name = val.strip()
            self.db.get_or_create_project(name=name)
            self.db.set_setting("active_project", name)
            self.filter_project = name
            all_projects = {p["id"]: p["name"] for p in self.db.list_projects()}
            proj_names = ["All Projects"] + sorted(list(set(all_projects.values())))
            self.project_menu.configure(values=proj_names)
            self.project_menu.set(name)
            self.refresh_feed()
            self._flash_status_beacon(f"Project '{name}' created & active!", COLOR_SUCCESS)

    def refresh_feed(self) -> None:
        """Fetch matching entries from SQLite and render cards."""
        proj_id = None
        if self.filter_project != "All Projects":
            projects = self.db.list_projects()
            for p in projects:
                if p["name"] == self.filter_project:
                    proj_id = p["id"]
                    break

        search_txt = self.feed_search_entry.get().strip() if hasattr(self, "feed_search_entry") else ""

        entries = self.db.get_entries(limit=60, project_id=proj_id, include_history=False)

        # Search filter
        if search_txt:
            st = search_txt.lower()
            entries = [
                e for e in entries
                if st in (e.get("raw_text") or "").lower() or st in (e.get("summary") or "").lower()
            ]

        # Source chip filter
        if self.filter_source != "all":
            filtered = []
            for e in entries:
                src = (e.get("source_app") or "").lower()
                meta = e.get("source_metadata") or {}
                if isinstance(meta, str):
                    try:
                        meta = json.loads(meta)
                    except Exception:
                        meta = {}
                ctype = meta.get("container_type") or meta.get("type") or ""

                if self.filter_source in ("browser", "clipboard", "cursor"):
                    if src == self.filter_source:
                        filtered.append(e)
                elif self.filter_source == "direct":
                    if src == "direct" or ctype == "user_note":
                        filtered.append(e)
                elif self.filter_source == "user_message" and ctype == "user_message":
                    filtered.append(e)
                elif self.filter_source == "assistant_response" and ctype == "assistant_response":
                    filtered.append(e)
                elif self.filter_source == "user_selection" and ctype == "user_selection":
                    filtered.append(e)
            entries = filtered

        # Quadrant filter if in Knowledge Vault
        if self.current_view == "vault" and self.selected_quadrant != "all":
            entries = [e for e in entries if e.get("quadrant") == self.selected_quadrant]

        target_scroll = self.vault_scroll if self.current_view == "vault" else self.feed_scroll
        cards_list = self.vault_cards if self.current_view == "vault" else self.feed_cards

        # ── Diff-based refresh: compare entry IDs, skip if unchanged ──
        new_ids = [e.get("id") for e in entries]
        last_ids_attr = "_last_vault_ids" if self.current_view == "vault" else "_last_feed_ids"
        old_ids = getattr(self, last_ids_attr, [])

        # If entry IDs haven't changed, skip full rebuild (huge perf win)
        if new_ids == old_ids and cards_list:
            # Just update selection states
            selected_id = self.selected_entry.get("id") if self.selected_entry else None
            for card in cards_list:
                card.set_selected(card.entry.get("id") == selected_id)
            self._update_status_counts()
            return

        # IDs changed — do full rebuild but in batches
        setattr(self, last_ids_attr, new_ids)

        for widget in target_scroll.winfo_children():
            widget.destroy()
        cards_list.clear()

        if not entries:
            empty_lbl = ctk.CTkLabel(
                target_scroll,
                text="No memories found.\nStart chatting with the browser extension or use Quick Dump Box!",
                font=FONT_BODY,
                text_color=COLOR_TEXT_MUTED,
                pady=40,
            )
            empty_lbl.pack()
            self._set_inspector_empty_state()
            self._update_status_counts()
            return

        all_projects = {p["id"]: p["name"] for p in self.db.list_projects()}
        proj_names = ["All Projects"] + sorted(list(set(all_projects.values())))
        if hasattr(self, "project_menu"):
            self.project_menu.configure(values=proj_names)

        selected_id = self.selected_entry.get("id") if self.selected_entry else None

        # ── Batched card creation with stagger for smoothness ──
        new_cards = []
        for entry in entries:
            entry_copy = dict(entry)
            pid = entry_copy.get("project_id")
            entry_copy["project_name"] = all_projects.get(pid, "General")

            is_sel = (selected_id is not None and entry_copy.get("id") == selected_id)
            card = MemoryFeedCard(
                target_scroll,
                entry=entry_copy,
                on_select=self._show_detail_inspector,
                on_copy=copy_to_clipboard,
                on_delete=self._handle_delete_entry,
                is_selected=is_sel,
            )
            card.pack(fill="x", pady=2)
            cards_list.append(card)
            new_cards.append(card)

        # Staggered fade-in for visual polish
        if new_cards:
            AnimationEngine.staggered_fade_in(new_cards, stagger_ms=25, duration_ms=150)

        # Auto-select the first card if nothing is selected
        if not self.selected_entry and entries:
            self._show_detail_inspector(entries[0])

        self._update_status_counts()

    def _update_status_counts(self) -> None:
        """Update count labels with smooth animated transitions."""
        total = self.db.count_entries()
        projects = self.db.list_projects()
        domain_count = len(projects)

        self.mem_count_lbl.configure(text=f"Memories: {total} active")

        # Animated counter for memory count
        if hasattr(self, "stat_mem_val") and total != self._last_mem_count:
            old_val = max(0, self._last_mem_count) if self._last_mem_count >= 0 else 0
            AnimationEngine.animate_counter(
                self.stat_mem_val, old_val, total,
                duration_ms=350, steps=12
            )
            self._last_mem_count = total

        # Animated counter for domain count
        if hasattr(self, "stat_domains_val") and domain_count != self._last_domain_count:
            old_val = max(0, self._last_domain_count) if self._last_domain_count >= 0 else 0
            AnimationEngine.animate_counter(
                self.stat_domains_val, old_val, domain_count,
                duration_ms=300, steps=10
            )
            self._last_domain_count = domain_count

    def _flash_status_beacon(self, message: str, color: str) -> None:
        """Flash status beacon with pulse glow when a live event occurs."""
        self.beacon_lbl.configure(text=f"⚡ {message}", text_color=color)
        # Pulse the sidebar status card border for attention
        self.after(2500, lambda: self.beacon_lbl.configure(
            text=f"🟢 Server: 127.0.0.1:{self.port}",
            text_color=COLOR_SUCCESS
        ))

    def _handle_flush_done(self) -> None:
        """Flush capture buffers manually upon user click."""
        self.flush_btn.configure(text="Flushing...", state="disabled")

        def _worker():
            try:
                res = self.pipeline.handle_done_signal()
                self.after(0, lambda: self._on_flush_complete(res))
            except Exception as e:
                logger.error("Flush error: %s", e)
                self.after(0, lambda: self.flush_btn.configure(text="❌ Error", state="normal"))

        threading.Thread(target=_worker, daemon=True).start()

    def _on_flush_complete(self, res: Dict[str, Any]) -> None:
        count = res.get("total_extracted", 0)
        self.flush_btn.configure(text=f"✓ Flushed ({count})", fg_color="#16a34a", state="normal")
        self.refresh_feed()
        self.after(2000, lambda: self.flush_btn.configure(text="🏁 Task Done / Flush", fg_color=COLOR_PRIMARY))

    def _schedule_periodic_poll(self) -> None:
        """Sync status, project lists, brain badge, and memories periodically."""
        self._update_status_counts()
        self._sync_active_project_and_brain()

        # Check server listener health
        if hasattr(self, "beacon_lbl") and self.engine and self.engine.http_listener:
            if not self.engine.http_listener.is_running:
                err_text = f"🔴 Port {self.port} Blocked" if self.engine.http_listener_error else f"🔴 Server Offline ({self.port})"
                self.beacon_lbl.configure(text=err_text, text_color=COLOR_DANGER)
            elif not self.is_capture_paused and not str(self.beacon_lbl.cget("text")).startswith("⚡"):
                self.beacon_lbl.configure(text=f"🟢 Server: 127.0.0.1:{self.port}", text_color=COLOR_SUCCESS)

        self.after(5000, self._schedule_periodic_poll)

    def _sync_active_project_and_brain(self) -> None:
        # 1. Sync AI brain badge
        provider = self.db.get_setting("llm_provider", "fallback")
        has_key = bool(self.db.get_setting("llm_api_key", ""))
        model = self.db.get_setting("llm_model", "gemini-2.0-flash")

        if hasattr(self, "sidebar_brain_lbl"):
            if has_key and provider != "fallback":
                self.sidebar_brain_lbl.configure(
                    text=f"🧠 Brain: {provider.upper()} ({model[:12]})",
                    text_color=COLOR_SUCCESS
                )
            else:
                self.sidebar_brain_lbl.configure(
                    text="🧠 Brain: Offline (Click to set)",
                    text_color=COLOR_WARNING
                )

        # 2. Sync project names if created from extension
        all_projects = {p["id"]: p["name"] for p in self.db.list_projects()}
        proj_names = ["All Projects"] + sorted(list(set(all_projects.values())))
        if hasattr(self, "project_menu"):
            curr_values = self.project_menu.cget("values")
            if curr_values != proj_names:
                self.project_menu.configure(values=proj_names)

    # ─────────────────────────────────────────────────────────────
    # Keyboard Shortcuts
    # ─────────────────────────────────────────────────────────────
    def _bind_keyboard_shortcuts(self) -> None:
        """Bind keyboard shortcuts for power-user navigation."""
        views = ["live_feed", "quick_dump", "vault", "sites", "primer", "settings"]

        # Ctrl+1 through Ctrl+6 — view switching
        for i, view_key in enumerate(views, start=1):
            self.bind(f"<Control-Key-{i}>", lambda e, k=view_key: self.show_view(k))

        # Ctrl+F — focus search bar
        self.bind("<Control-f>", self._shortcut_focus_search)
        self.bind("<Control-F>", self._shortcut_focus_search)

        # Ctrl+N — Quick Dump
        self.bind("<Control-n>", lambda e: self.show_view("quick_dump"))
        self.bind("<Control-N>", lambda e: self.show_view("quick_dump"))

        # Ctrl+P — Primer
        self.bind("<Control-p>", lambda e: self.show_view("primer"))
        self.bind("<Control-P>", lambda e: self.show_view("primer"))

        # Escape — clear search or deselect
        self.bind("<Escape>", self._shortcut_escape)

        # Up/Down arrows — navigate feed cards
        self.bind("<Up>", lambda e: self._navigate_cards(-1))
        self.bind("<Down>", lambda e: self._navigate_cards(1))

    def _shortcut_focus_search(self, event=None) -> None:
        """Focus the search entry if in live feed view."""
        if self.current_view != "live_feed":
            self.show_view("live_feed")
        if hasattr(self, "feed_search_entry"):
            self.feed_search_entry.focus_set()

    def _shortcut_escape(self, event=None) -> None:
        """Clear search text or deselect current entry."""
        if hasattr(self, "feed_search_entry") and self.feed_search_entry.get():
            self.feed_search_entry.delete(0, "end")
            self._last_feed_ids.clear()  # Force refresh
            self.refresh_feed()
        else:
            self._set_inspector_empty_state()

    def _navigate_cards(self, direction: int) -> None:
        """Navigate feed cards with up/down arrow keys."""
        cards = self.vault_cards if self.current_view == "vault" else self.feed_cards
        if not cards:
            return

        current_id = self.selected_entry.get("id") if self.selected_entry else None
        current_idx = -1
        for i, card in enumerate(cards):
            if card.entry.get("id") == current_id:
                current_idx = i
                break

        new_idx = current_idx + direction
        if 0 <= new_idx < len(cards):
            self._show_detail_inspector(cards[new_idx].entry)


def run_app(port: int = DEFAULT_HTTP_PORT) -> None:
    """Launch the OwlThread Desktop Application."""
    app = OwlThreadDesktopApp(port=port)
    app.mainloop()


if __name__ == "__main__":
    run_app()
