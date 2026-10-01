"""OwlThread's standard-library Tk desktop: feed, search, quadrants and primers."""
from __future__ import annotations

import logging
import queue
import threading
import tkinter as tk
from tkinter import ttk
from typing import Any, Callable

from owlthread.config import DEFAULT_HTTP_PORT, QUADRANT_COLORS
from owlthread.db.database import Database
from owlthread.capture.engine import CaptureEngine
from owlthread.gui.animations import Animator
from owlthread.gui.feed_card import FeedCard, CaptureCard, _relative_time
from owlthread.hotkey import WindowsHotkeyListener
from owlthread.primer.engine import PrimerEngine
from owlthread.primer.llm import LLMClient, DEFAULTS
from owlthread.primer.search import MemorySearcher
from owlthread.primer.ui import PrimerPanel, PrimerPopupUI
from owlthread.gui.theme import BG, CARD, TEXT, MUTED, ACCENT, SIDEBAR, BORDER, SELECTED, RoundedFrame, SegmentedTabs, button

logger = logging.getLogger(__name__)


def label(master: tk.Misc, text: str, size: int = 11, color: str = TEXT, bold: bool = False) -> tk.Label:
    widget = tk.Label(master,text=text,bg=master.cget("bg"),fg=color,font=("Segoe UI",size,"bold" if bold else "normal"),
                      justify="left",anchor="w")
    widget.bind("<Configure>",lambda event:widget.configure(wraplength=max(100,event.width)))
    return widget


class ScrollFrame(tk.Frame):
    def __init__(self, master: tk.Misc) -> None:
        super().__init__(master,bg=BG)
        self.canvas = tk.Canvas(self,bg=BG,highlightthickness=0,bd=0)
        scrollbar = ttk.Scrollbar(self,orient="vertical",command=self.canvas.yview)
        scrollbar.pack(side="right",fill="y")
        self.canvas.pack(side="left",fill="both",expand=True)
        self.canvas.configure(yscrollcommand=scrollbar.set)
        self.content = tk.Frame(self.canvas,bg=BG)
        window = self.canvas.create_window((0,0),window=self.content,anchor="nw")
        self.content.bind("<Configure>",lambda _:self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>",lambda event:self.canvas.itemconfigure(window,width=event.width))

    def wheel(self, event: tk.Event) -> None:
        self.canvas.yview_scroll(-int(event.delta/120) if event.delta else (-1 if event.num==4 else 1),"units")


class OwlThreadApp(tk.Tk):
    def __init__(self, db: Database | None = None, port: int = DEFAULT_HTTP_PORT,
                 auto_start_engine: bool = True) -> None:
        super().__init__()
        self._owns_db = db is None
        self.db = db or Database()
        self.port = port
        self.engine = CaptureEngine(self.db,http_port=port) if auto_start_engine else None
        self.primer_engine = PrimerEngine(self.db,extraction_pipeline=self.engine.pipeline if self.engine else None)
        self.title("OwlThread — Your personal workspace")
        self.geometry("1180x800")
        self.minsize(920,650)
        self.configure(bg=BG)
        self._closing = False
        self.on_quit: Callable[[],None] | None = None
        self._hotkey: WindowsHotkeyListener | None = None
        self._actions: queue.Queue[Callable[[],None]] = queue.Queue()
        self._workers: list[threading.Thread] = []
        self._popups: list[PrimerPopupUI] = []
        self._search_id: str | None = None
        self._tick_id: str | None = None
        self._refresh_id: str | None = None
        self.current_view = "feed"
        self._note_drafts: dict[str,str] = {}
        self._search_text = ""
        self._settings_draft: dict[str,str] = {}
        self._saving_capture = False
        self.views: dict[str,tk.Frame] = {}
        self._scrolls: list[ScrollFrame] = []
        self._last_counts = (-1,-1)
        # Initial reads happen before entering the event loop; later I/O uses _job.
        self._settings = self.db.get_all_settings()
        self._projects = self.db.list_projects()
        self._rows: list[dict[str,Any]] = []
        self._counts = (0,0)
        self._view_revision = 0
        self._refresh_busy = False
        self._capture_status: dict[str,Any] = {}
        self._transfer_status: dict[str,Any] = {}
        self._captures: list[dict[str,Any]] = []
        from owlthread.integrations.browser_login import BrowserLoginService
        self.login_service = BrowserLoginService(self.db)
        self._browser_fields: dict[str,dict[str,Any]] = {}
        self._login_tick_id: str | None = None
        self._connector_advanced_open: dict[str,bool] = {}
        self.project = tk.StringVar(value=self._settings.get("active_project","General"))
        self._style()
        self._build()
        self.protocol("WM_DELETE_WINDOW",self._on_close)
        self.bind("<MouseWheel>",self._wheel)
        self.bind("<Button-4>",self._wheel)
        self.bind("<Button-5>",self._wheel)
        self.bind("<Control-k>",lambda _:self._shortcut("search"))
        self.bind("<Control-n>",lambda _:self._shortcut("capture"))
        self.bind("<Control-s>",self._save_shortcut)
        self.bind("<Control-Shift-P>",lambda _:self.open_primer())
        self.bind("<Control-Shift-p>",lambda _:self.open_primer())
        self._tick()
        self.show_view("feed")
        if self.engine:
            self.engine.add_capture_callback(lambda _:self._actions.put(self._request_refresh))
            try:
                self.engine.start()
            except RuntimeError as exc:
                self.footer.configure(text=str(exc),fg="#f59e0b")
            self._hotkey = WindowsHotkeyListener(lambda:self._actions.put(self.open_primer))
            self._hotkey.start()
            if not self._hotkey.error:
                self.unbind("<Control-Shift-P>")
                self.unbind("<Control-Shift-p>")
        self._refresh()
        Animator.fade_in(self)

    def _style(self) -> None:
        style = ttk.Style(self)
        style.theme_use("clam")
        style.layout("Vertical.TScrollbar",[("Vertical.Scrollbar.trough",{"sticky":"ns","children":[("Vertical.Scrollbar.thumb",{"expand":"1","sticky":"nswe"})]})])
        style.configure("TCombobox",fieldbackground=CARD,background=CARD,foreground=TEXT,arrowcolor=MUTED,
                        bordercolor=CARD,lightcolor=CARD,darkcolor=CARD,padding=6,arrowsize=14)
        style.map("TCombobox",fieldbackground=[("readonly",CARD)],foreground=[("readonly",TEXT)])
        style.configure("Vertical.TScrollbar",background=BORDER,troughcolor=BG,arrowcolor=MUTED,borderwidth=0,lightcolor=BORDER,darkcolor=BORDER,bordercolor=BG,width=8,arrowsize=8,gripcount=0)
        style.map("Vertical.TScrollbar",background=[("active",MUTED),("!active",BORDER)])

        style.configure("TNotebook",background=BG,borderwidth=0,bordercolor=BORDER,lightcolor=BG,darkcolor=BG)
        style.configure("TNotebook.Tab",background=CARD,foreground=MUTED,padding=(14,10),bordercolor=BORDER,lightcolor=BORDER,darkcolor=BORDER)
        style.map("TNotebook.Tab",background=[("selected",SELECTED)],foreground=[("selected",TEXT)],padding=[("selected",(14,10))])
        style.configure("TEntry",fieldbackground=CARD,foreground=TEXT,insertcolor=ACCENT,padding=7,bordercolor=BORDER,lightcolor=BORDER,darkcolor=BORDER)
        self.option_add("*TCombobox*Listbox.background",CARD)
        self.option_add("*TCombobox*Listbox.foreground",TEXT)
        self.option_add("*TCombobox*Listbox.selectBackground",SELECTED)

    def _shortcut(self, view: str) -> str:
        if self.current_view != view:
            self.show_view(view)
        if view == "search": self.search_entry.focus_set()
        elif view == "capture": self.note.focus_set()
        return "break"

    def _save_shortcut(self, event: tk.Event | None = None) -> str:
        if self.current_view == "capture": self._save_capture()
        elif self.current_view == "settings": self._save_settings()
        return "break"

    def _build(self) -> None:
        sidebar = tk.Frame(self,bg=SIDEBAR,width=210)
        sidebar.pack(side="left",fill="y")
        sidebar.pack_propagate(False)
        brand = tk.Frame(sidebar,bg=SIDEBAR,padx=18,pady=26)
        brand.pack(fill="x")
        label(brand,"OwlThread",20, TEXT,True).pack(anchor="w")
        label(brand,"Your personal memory",10,MUTED).pack(anchor="w",pady=(5,0))
        button(sidebar,"+  New capture",lambda:self.show_view("capture"),True).pack(fill="x",padx=14,pady=(2,24))
        label(sidebar,"   Workspace",9,MUTED,True).pack(fill="x",padx=12,pady=(0,8))
        self.nav: dict[str,tk.Button] = {}
        for key,title in (("feed","Overview"),("search","Search"),("quadrants","Memory library"),("primer","Ask OwlThread"),("capture","Capture a note"),("integrations","Connections"),("settings","Settings")):
            nav = button(sidebar,title,lambda k=key:self.show_view(k))
            nav.configure(bg=SIDEBAR,anchor="w",font=("Segoe UI",11),padx=16,pady=7)
            nav.pack(side="bottom" if key=="settings" else "top",fill="x",padx=10,pady=2)
            self.nav[key] = nav
        label(sidebar,"Ctrl+K   Search\nCtrl+N   New capture",9,MUTED).pack(side="bottom",fill="x",padx=24,pady=20)
        container = tk.Frame(self,bg=BG)
        container.pack(side="left",fill="both",expand=True,padx=26,pady=24)
        header = tk.Frame(container,bg=BG)
        header.pack(fill="x",pady=(0,16))
        label(header,"Your workspace",10,MUTED).pack(side="left")
        self.project_menu = ttk.Combobox(header,textvariable=self.project,values=[p["name"] for p in self._projects],width=20)
        self.project_menu.pack(side="right")
        self.project_menu.bind("<<ComboboxSelected>>",self._project_changed)
        self.project_menu.bind("<Return>",self._project_changed)
        label(header,"Project   ",9,MUTED).pack(side="right")
        transfer = RoundedFrame(container,bg=CARD,padx=18,pady=12)
        transfer.pack(fill="x",pady=(0,20))
        button(transfer,"Browser setup",lambda:self.show_view("settings")).pack(side="right",padx=(12,0))
        self.browser_status = label(transfer,"Checking browser connection…",9,MUTED)
        self.browser_status.pack(fill="x",expand=True)
        self.browser_status.bind("<Configure>",lambda event:self.browser_status.configure(wraplength=max(180,event.width)))
        self.page = tk.Frame(container,bg=BG)
        self.footer = label(container,"Saved on this device  ·  Ctrl+Shift+P for quick context",9,MUTED)
        self.footer.pack(side="bottom",fill="x",pady=(14,0))
        self.page.pack(fill="both",expand=True)

    def _project_changed(self, event: tk.Event | None = None) -> None:
        self._remember_draft()
        name = self.project.get().strip() or "General"
        self.project.set(name)
        def work() -> Any:
            self.db.get_or_create_project(name)
            self.db.set_setting("active_project",name)
            return self._snapshot(name)
        self._job(work,self._apply_snapshot)

    def _pid(self) -> int:
        return next((p["id"] for p in self._projects if p["name"]==self.project.get()),0)

    def _snapshot(self, name: str) -> dict[str,Any]:
        pid=self.db.get_or_create_project(name)
        status=self.engine.status() if self.engine else {"http_listener":{"running":False},"capture_paused":self.db.get_setting("capture_paused","false")=="true"}
        capture_status=self.db.capture_status(pid)
        return {"name":name,"projects":self.db.list_projects(),"settings":self.db.get_all_settings(),
                "rows":self.db.get_entries(project_id=pid,limit=500),
                "counts":(self.db.count_entries(project_id=pid),capture_status["pending_captures"]),
                "capture_status":capture_status,"transfer_status":status,
                "captures":self.db.execute_read("SELECT * FROM capture_buffer WHERE project_id=? ORDER BY id DESC LIMIT 100",(pid,)),
                "pending":self.db.execute_read("SELECT * FROM capture_buffer WHERE processed=0 AND project_id=? ORDER BY id DESC LIMIT 100",(pid,))}

    def _apply_snapshot(self, data: dict[str,Any]) -> None:
        self._refresh_busy=False
        if data["name"] != self.project.get():
            return
        memories_changed=self._rows != data["rows"]
        changed=memories_changed or self._counts != data["counts"] or self._captures != data["captures"]
        self._rows,self._counts,self._settings,self._projects=data["rows"],data["counts"],data["settings"],data["projects"]
        self._pending=data["pending"]
        self._captures,self._capture_status,self._transfer_status=data["captures"],data["capture_status"],data["transfer_status"]
        self.project_menu.configure(values=[p["name"] for p in self._projects])
        self._update_browser_status()
        if self.current_view == "capture" and getattr(self,"_note_project",None) != self.project.get():
            self.show_view("capture")
        if changed and self.current_view in {"feed","quadrants"}:
            position=self._scrolls[0].canvas.yview()[0] if self._scrolls else 0
            self.show_view(self.current_view)
            if self._scrolls:
                self.update_idletasks()
                self._scrolls[0].canvas.yview_moveto(position)
        elif changed and self.current_view=="pending":
            self._view_pending()
        elif changed and self.current_view=="captures":
            self._view_captures()
        elif memories_changed and self.current_view=="search":
            self._search()
        elif memories_changed and self.current_view=="quadrant":
            self._show_quadrant(self._active_quadrant)

    def _update_browser_status(self) -> None:
        status=self._transfer_status
        color=MUTED
        if status.get("capture_paused"):
            state="Browser capture paused · resume in Settings"
            color="#f59e0b"
        elif status.get("http_listener",{}).get("running"):
            state="Browser capture ready"
            if not status.get("authorized_browser_count",0):
                state+=" · pair your extension"
            color="#62d6ad"
        elif self.engine and self.engine.http_listener_error:
            state="Browser receiver unavailable · local port is already in use"
            color="#f59e0b"
        else:
            state="Browser capture is offline · open Browser setup to connect"
        received=self._capture_status.get("last_browser_capture_at")
        state+="\n"+(f"Last browser capture {_relative_time(received)}" if received else "No browser captures received in this project yet")
        state+=f" · {self._capture_status.get('pending_captures',0)} waiting to extract"
        failed=self._capture_status.get("failed_captures",0)
        if failed:
            state+=f" · {failed} need retry"
        self.browser_status.configure(text=state,fg=color)

    def _mutate(self, work: Callable[[],Any], callback: Callable[[Any],None] | None = None) -> None:
        name=self.project.get()
        def run() -> Any:
            result=work()
            return result,self._snapshot(name)
        def done(value: Any) -> None:
            self._apply_snapshot(value[1])
            if callback: callback(value[0])
        self._job(run,done)

    def _heading(self, title: str, subtitle: str) -> None:
        label(self.page,title,26,bold=True).pack(fill="x",pady=(0,8))
        description=label(self.page,subtitle,11,MUTED)
        description.configure(wraplength=760)
        description.pack(fill="x",pady=(0,18))
        description.bind("<Configure>",lambda event:description.configure(wraplength=max(180,event.width)))

    def _scroll(self, master: tk.Misc | None = None) -> ScrollFrame:
        scroll = ScrollFrame(master or self.page)
        scroll.pack(fill="both",expand=True)
        self._scrolls.append(scroll)
        return scroll

    def _remember_draft(self) -> None:
        if self.current_view == "capture" and hasattr(self,"note") and self.note.winfo_exists():
            self._note_drafts[self._note_project] = self.note.get("1.0","end-1c")
        if self.current_view == "settings" and hasattr(self,"prompt_fields"):
            self._settings_draft = self._settings_values()
        if self.current_view == "search" and hasattr(self,"search_query"):
            self._search_text = self.search_query.get()

    def show_view(self, key: str) -> None:
        if self._closing:
            return
        self._remember_draft()
        aliases = {"live_feed":"feed","quick_dump":"capture","vault":"quadrants","sites":"settings"}
        key = aliases.get(key,key)
        self.current_view = key
        self._view_revision += 1
        if self._search_id:
            self.after_cancel(self._search_id)
            self._search_id = None
        for child in self.page.winfo_children():
            child.destroy()
        self._scrolls.clear()
        self._set_navigation(key)
        self.views[key] = self.page
        getattr(self,"_view_"+key)()
        self._bind_editor_shortcuts(self.page)

    def _bind_editor_shortcuts(self, parent: tk.Misc) -> None:
        # Handle shortcuts before Tk's editing bindings (Ctrl+K deletes text).
        for widget in parent.winfo_children():
            if isinstance(widget,(tk.Text,tk.Entry,ttk.Entry)):
                widget.bind("<Control-k>",lambda _:self._shortcut("search"))
                widget.bind("<Control-n>",lambda _:self._shortcut("capture"))
                widget.bind("<Control-s>",self._save_shortcut)
            self._bind_editor_shortcuts(widget)

    def _set_navigation(self, key: str) -> None:
        key = {"captures":"feed","pending":"feed","quadrant":"quadrants"}.get(key,key)
        for name,nav in self.nav.items():
            nav.configure(bg=SELECTED if name==key else SIDEBAR,fg=TEXT if name==key else MUTED,
                          font=("Segoe UI",11,"bold" if name==key else "normal"))

    def _view_feed(self) -> None:
        self._heading("Overview","Your recent captures and saved memories, together in one place.")
        stats = tk.Frame(self.page,bg=BG)
        stats.pack(fill="x",pady=(0,22))
        count = self._counts[0]
        label(stats,f"{count} active memories",13,bold=True).pack(side="left")
        label(stats,f"   ·   {self._counts[1]} waiting to extract",10,MUTED).pack(side="left")
        button(stats,"Extract now",lambda:self._job(self.primer_engine.pipeline.handle_done_signal,self._flush_done),True).pack(side="right")
        button(stats,"Raw captures",self._view_captures).pack(side="right",padx=6)
        self.feed_scroll = self._scroll().content
        self.refresh_feed()

    def _view_pending(self) -> None:
        for child in self.page.winfo_children(): child.destroy()
        self._scrolls.clear()
        self.current_view="pending"
        self._set_navigation("pending")
        self._heading("Pending captures","Raw captures stay local until extraction succeeds. Failed items can be retried.")
        button(self.page,"← Overview",lambda:self.show_view("feed")).pack(anchor="w",pady=(0,8))
        button(self.page,"Retry extraction",lambda:self._job(self.primer_engine.pipeline.handle_done_signal,self._flush_done)).pack(anchor="w",pady=(0,12))
        pane=self._scroll().content
        for row in getattr(self,"_pending",[]):
            CaptureCard(pane,row).pack(fill="x",pady=(0,10))
        if not getattr(self,"_pending",[]): label(pane,"No pending captures in this project.").pack(fill="x")

    def _view_captures(self) -> None:
        for child in self.page.winfo_children(): child.destroy()
        self._scrolls.clear()
        self.current_view="captures"
        self._set_navigation("captures")
        self._view_revision+=1
        self._heading("Raw captures",f"{self._capture_status.get('total_captures',0)} received in {self.project.get()} · newest 100 shown. Raw text remains local after extraction.")
        actions=tk.Frame(self.page,bg=BG)
        actions.pack(fill="x",pady=(0,14))
        button(actions,"← Overview",lambda:self.show_view("feed")).pack(side="left")
        button(actions,"Pending only",self._view_pending).pack(side="left",padx=8)
        button(actions,"Extract now",lambda:self._job(self.primer_engine.pipeline.handle_done_signal,self._flush_done)).pack(side="right")
        pane=self._scroll().content
        for row in self._captures:
            CaptureCard(pane,row).pack(fill="x",pady=(0,10))
        if not self._captures:
            label(pane,"No captures received in this project. Pair the Chrome extension in Settings, or save a note.",11,MUTED).pack(fill="x")

    def refresh_feed(self) -> None:
        for child in self.feed_scroll.winfo_children():
            child.destroy()
        if self._captures:
            label(self.feed_scroll,"Recent captures",11,TEXT,True).pack(fill="x",pady=(0,10))
            for row in self._captures[:3]:
                CaptureCard(self.feed_scroll,row).pack(fill="x",pady=(0,10))
            label(self.feed_scroll,"Saved memories",11,TEXT,True).pack(fill="x",pady=(12,10))
        rows = self._rows[:100]
        if not rows and self._captures:
            label(self.feed_scroll,"Your captures are saved. Use Extract now to turn decisions and useful details into memories.",11,MUTED).pack(fill="x",pady=12)
            return
        self._cards(self.feed_scroll,rows)

    def _cards(self, master: tk.Misc, rows: list[dict[str,Any]]) -> None:
        if not rows:
            frame = RoundedFrame(master,bg=CARD,padx=30,pady=32)
            frame.pack(fill="x")
            label(frame,"A little context goes a long way.",18,bold=True).pack(fill="x")
            label(frame,"Capture a note or conversation, then extract it into lasting memory.\nYour first decision will appear here.",11,MUTED).pack(fill="x",pady=(12,20))
            button(frame,"Capture your first note",lambda:self.show_view("capture"),True).pack(anchor="w")
        for row in rows:
            FeedCard(master,row,on_action=self._entry_action).pack(fill="x",pady=(0,12))

    def _entry_action(self, entry_id: int, action: str) -> None:
        self._mutate(lambda:self.db.archive_entry(entry_id) if action=="archive" else self.db.supersede_entry(entry_id))

    def _handle_delete_entry(self, entry_id: int) -> None:
        self._entry_action(entry_id,"archive")

    def _view_search(self) -> None:
        self._heading("Search your memory","Find a decision, constraint or detail in the current project.")
        label(self.page,"Search by keyword or phrase",10,MUTED).pack(anchor="w",pady=(0,8))
        self.search_query = tk.StringVar(value=self._search_text)
        search_box = RoundedFrame(self.page,bg=CARD,padx=18,pady=14)
        search_box.pack(fill="x",pady=(0,12))
        entry = tk.Entry(search_box,textvariable=self.search_query,bg=CARD,fg=TEXT,insertbackground=ACCENT,font=("Segoe UI",14),relief="flat")
        self.search_entry = entry
        entry.pack(fill="x")
        self.search_notice = label(self.page,"",10,MUTED)
        self.search_notice.pack(fill="x",pady=(0,12))
        self.search_results = self._scroll().content
        def changed(*_: Any) -> None:
            if self._search_id:
                self.after_cancel(self._search_id)
            self._search_id = self.after(300,self._search)
        self.search_query.trace_add("write",changed)
        entry.focus_set()
        self._search()

    def _search(self) -> None:
        self._search_id = None
        if self.current_view!="search":
            return
        for widget in self.search_results.winfo_children():
            widget.destroy()
        query,pid,revision=self.search_query.get(),self._pid(),self._view_revision
        self.search_notice.configure(text="Searching…")
        def done(rows: Any) -> None:
            if self.current_view=="search" and self._view_revision==revision and self.search_query.get()==query:
                self.search_notice.configure(text=f"{len(rows)} results" if query.strip() else "Recent memories · type above to search")
                if not rows and query.strip():
                    label(self.search_results,"No matching memories",17,bold=True).pack(anchor="w",pady=(18,8))
                    label(self.search_results,"Try fewer words or choose another project.",11,MUTED).pack(anchor="w")
                    button(self.search_results,"Clear search",lambda:self.search_query.set("")).pack(anchor="w",pady=16)
                else:
                    self._cards(self.search_results,rows)
        self._job(lambda:MemorySearcher(self.db).search(query,limit=30,project_id=pid),done)

    def _view_quadrants(self) -> None:
        self._heading("Memory library","Browse saved knowledge by category.")
        grid = self._scroll().content
        for index,(quadrant,color) in enumerate(QUADRANT_COLORS.items()):
            grid.columnconfigure(index % 2,weight=1,uniform="quadrants")
            col = RoundedFrame(grid,bg=CARD,padx=22,pady=22)
            col.grid(row=index // 2,column=index % 2,sticky="nsew",padx=(0,10),pady=(0,12))
            title = quadrant.replace("_"," ").title()
            heading = label(col,"● "+title,11,color,True)
            heading.configure(wraplength=145)
            heading.pack(fill="x")
            matches = [r for r in self._rows if r["quadrant"]==quadrant]
            label(col,f"{len(matches)} {'memory' if len(matches)==1 else 'memories'}",10,MUTED).pack(fill="x",pady=(8,0))
            for row in matches[:2]:
                item = label(col,f"#{row['id']}\n{row['summary']}",11)
                item.configure(wraplength=145)
                item.pack(fill="x",pady=15)
            def resize(event: tk.Event, frame: tk.Frame = col) -> None:
                for child in frame.winfo_children():
                    if isinstance(child,tk.Label):
                        child.configure(wraplength=max(90,event.width-28))
            col.bind("<Configure>",resize)
            button(col,"Show all",lambda q=quadrant:self._show_quadrant(q)).pack(fill="x",pady=(15,0))

    def _show_quadrant(self, quadrant: str) -> None:
        self.current_view="quadrant"
        self._set_navigation("quadrant")
        self._active_quadrant=quadrant
        self._view_revision+=1
        for child in self.page.winfo_children():
            child.destroy()
        self._scrolls.clear()
        self._heading(quadrant.replace("_"," ").title(),"Active memories in this quadrant")
        button(self.page,"← All quadrants",lambda:self.show_view("quadrants")).pack(anchor="w",pady=(0,16))
        self._cards(self._scroll().content,[r for r in self._rows if r["quadrant"]==quadrant])

    def _view_primer(self) -> None:
        self._panels = [p for p in getattr(self,"_panels",[]) if p._worker and p._worker.is_alive()]
        self.primer_panel = PrimerPanel(self.page,self.primer_engine)
        self.primer_panel.pack(fill="both",expand=True)
        self._panels = getattr(self,"_panels",[])+[self.primer_panel]

    def _view_capture(self) -> None:
        self._heading("Capture a note","Save a decision, useful detail or conversation to this project.")
        self._note_project = self.project.get()
        label(self.page,"Your note",10,MUTED,True).pack(anchor="w",pady=(0,8))
        editor = RoundedFrame(self.page,bg=CARD,padx=18,pady=18)
        self.note = tk.Text(editor,bg=CARD,fg=TEXT,insertbackground=ACCENT,wrap="word",font=("Segoe UI",12),relief="flat",padx=0,pady=0)
        self.note.insert("1.0",self._note_drafts.get(self._note_project,""))
        actions = tk.Frame(self.page,bg=BG)
        actions.pack(side="bottom",fill="x")
        editor.pack(fill="both",expand=True,pady=(0,16))
        self.note.pack(fill="both",expand=True)
        label(actions,"Saved locally · extract into memories from Overview",9,MUTED).pack(side="left")
        self.save_capture_button = button(actions,"Save capture",self._save_capture,True)
        self.save_capture_button.pack(side="right")
        self.save_capture_button.configure(state="disabled" if self._saving_capture else "normal")
        self.note.focus_set()

    def _save_capture(self) -> None:
        if self._saving_capture: return
        text = self.note.get("1.0","end").strip()
        if not text:
            self.footer.configure(text="Write or paste a note before saving.",fg="#f59e0b")
            self.note.focus_set()
            return
        if text:
            name=self._note_project
            self._saving_capture = True
            self.save_capture_button.configure(state="disabled",text="Saving…")
            def done(_: Any) -> None:
                self._saving_capture = False
                if self._note_drafts.get(name,"").strip() == text: self._note_drafts.pop(name,None)
                if self.current_view=="capture" and self.save_capture_button.winfo_exists():
                    self.save_capture_button.configure(state="normal",text="Save capture")
                if self.current_view=="capture" and self._note_project==name and self.note.get("1.0","end").strip()==text:
                    self.note.delete("1.0","end")
                self.footer.configure(text="Capture saved. Open Overview and choose Extract now to create memories.",fg="#62d6ad")
            def work() -> Any:
                self.db.insert_capture(text,"manual",self.db.get_or_create_project(name))
                return self._snapshot(name)
            def saved(data: Any) -> None:
                self._apply_snapshot(data)
                done(None)
            def failed() -> None:
                self._saving_capture = False
                if self.current_view=="capture": self.save_capture_button.configure(state="normal",text="Save capture")
            if not self._job(work,saved,on_error=failed): failed()

    def _view_integrations(self) -> None:
        """Cloudflare and GitHub setup; other integrations are previews only."""
        from owlthread.integrations.registry import IntegrationRegistry
        from owlthread.integrations.context import ContextConnectorService
        self._heading("Connections","Bring context from your tools into this project.")
        intro = label(self.page,
            "Sign in, choose an account or repository, then import. Context is saved to the project selected when sign-in begins.",
            10,MUTED)
        intro.configure(wraplength=760,justify="left")
        intro.pack(fill="x",pady=(0,16))
        pane = self._scroll().content
        registry = IntegrationRegistry(self.db)
        service=ContextConnectorService(self.db)
        self.integration_fields: dict[str,dict[str,Any]]={}
        for integration_id in ("cloudflare","github"):
            self._connector_card(pane,service.status(integration_id))
        label(pane,"MORE TOOLS",10,ACCENT,True).pack(fill="x",pady=(18,8))
        note=label(pane,"Cloudflare and GitHub are available above. Other integrations are coming soon.",10,MUTED)
        note.configure(wraplength=760)
        note.pack(fill="x",pady=(0,14))
        for item in registry.list():
            if item["id"] in {"cloudflare","github"}: continue
            card = RoundedFrame(pane,bg=CARD,padx=22,pady=20)
            card.pack(fill="x",pady=(0,10))
            top = tk.Frame(card,bg=CARD)
            top.pack(fill="x")
            label(top,item["name"],13,bold=True).pack(side="left")
            label(top,"Coming soon",9,ACCENT).pack(side="right")
            description=label(card,f"{item['category']}\n{item['description']}",10,MUTED)
            description.configure(wraplength=760)
            description.pack(fill="x",pady=(7,8))
            description.bind("<Configure>",lambda event,w=description:w.configure(wraplength=max(180,event.width)))

    def _connector_card(self, pane: tk.Frame, item: dict[str,Any]) -> None:
        provider=item["id"]
        card=RoundedFrame(pane,bg=CARD,padx=22,pady=20)
        card.pack(fill="x",pady=(0,12))
        label(card,item["name"],15,bold=True).pack(fill="x")
        text="Sign in to choose your Cloudflare account. Context reads never change your resources." if provider=="cloudflare" else "Sign in to choose a public repository. Private repositories can use a restricted token in Advanced."
        label(card,text,10,MUTED).pack(fill="x",pady=(7,8))
        row=tk.Frame(card,bg=CARD);row.pack(fill="x")
        connect=button(row,"Sign in with "+item["name"],lambda:self._begin_browser_login(provider),True)
        connect.pack(side="left",padx=(0,8))
        reopen=button(row,"Open browser again",lambda:self._reopen_browser_login(provider))
        cancel=button(row,"Cancel",lambda:self.login_service.cancel(provider))
        notice=label(card,"Ready to connect.",10,MUTED);notice.pack(fill="x",pady=(10,8))
        notice.bind("<Configure>",lambda event,w=notice:w.configure(wraplength=max(180,event.width)))
        choice=tk.StringVar()
        resources=ttk.Combobox(card,textvariable=choice,state="readonly")
        resources.pack(fill="x",pady=(0,8))
        actions=tk.Frame(card,bg=CARD);actions.pack(fill="x")
        import_button=button(actions,"Use selected account and import" if provider=="cloudflare" else "Use selected repository and import",lambda:self._import_browser_context(provider))
        import_button.pack(side="left",padx=(0,8))
        button(actions,"Disconnect",lambda:self._disconnect_browser_login(provider)).pack(side="left")
        self._browser_fields[provider]={"choice":choice,"resources":resources,"notice":notice,"connect":connect,"reopen":reopen,"cancel":cancel,"import":import_button,"resource_map":{},"signature":None}
        if provider=="github" and not self.login_service.client_id():
            setup=tk.Frame(card,bg=CARD);setup.pack(fill="x",pady=(12,0))
            label(setup,"One-time app setup: register OwlThread with GitHub and enable Device Flow.",10,MUTED).pack(fill="x")
            setup_row=tk.Frame(setup,bg=CARD);setup_row.pack(fill="x",pady=(6,0))
            button(setup_row,"Set up GitHub sign-in",lambda:self._open_github_registration()).pack(side="left",padx=(0,8))
            client_id=tk.StringVar()
            ttk.Entry(setup_row,textvariable=client_id,width=24).pack(side="left",padx=(0,8))
            button(setup_row,"Save Client ID",lambda:self._save_github_client(client_id.get())).pack(side="left")
        advanced=tk.Frame(card,bg=CARD)
        def toggle():
            opened=not self._connector_advanced_open.get(provider,False)
            self._connector_advanced_open[provider]=opened
            if opened: advanced.pack(fill="x",pady=(8,0))
            else: advanced.pack_forget()
        button(card,"Advanced · use an API token",toggle).pack(anchor="w",pady=(12,0))
        self._token_connector_card(advanced,item)
        if self._connector_advanced_open.get(provider,False): advanced.pack(fill="x",pady=(8,0))
        self._poll_browser_logins()

    def _open_github_registration(self) -> None:
        import webbrowser
        webbrowser.open("https://github.com/settings/applications/new")
        self.footer.configure(text="Register OwlThread, enable Device Flow, then paste its public Client ID here. No client secret is needed.")

    def _save_github_client(self, client_id: str) -> None:
        import re
        if not re.fullmatch(r"[A-Za-z0-9_.-]{10,128}",client_id.strip()):
            self.footer.configure(text="Paste the public Client ID from your OwlThread GitHub app.",fg="#f59e0b");return
        self._mutate(lambda:self.db.set_setting("github_oauth_client_id",client_id.strip()),lambda _:self.show_view("integrations"))

    def _begin_browser_login(self, provider: str) -> None:
        project=self.project.get()
        def work():
            return self.login_service.begin(provider,self.db.get_or_create_project(project))
        def done(result): self._poll_browser_logins()
        def failed():
            self.footer.configure(text="GitHub needs its registered Client ID; otherwise check your connection and try again.",fg="#f59e0b")
        self._job(work,done,on_error=failed)

    def _reopen_browser_login(self, provider: str) -> None:
        import webbrowser
        session=self.login_service.status(provider).get("session") or {}
        if session.get("state") in {"starting","waiting"} and session.get("browser_url"): webbrowser.open(session["browser_url"])

    def _poll_browser_logins(self) -> None:
        if self._login_tick_id:
            self.after_cancel(self._login_tick_id);self._login_tick_id=None
        if self._closing: return
        for provider,fields in self._browser_fields.items():
            if not fields["notice"].winfo_exists(): continue
            status=self.login_service.status(provider)
            session=status.get("session") or {}
            pending=session.get("state") in {"starting","waiting","discovering"}
            fields["connect"].configure(state="disabled" if pending or not status["browser_login_available"] else "normal")
            if pending:
                fields["cancel"].pack(side="left",padx=(0,8))
                if session.get("browser_url"): fields["reopen"].pack(side="left",padx=(0,8))
            else: fields["cancel"].pack_forget();fields["reopen"].pack_forget()
            message=session.get("message") or ("Signed in as "+status["label"]+". Choose a resource to import." if status["signed_in"] else "Ready to connect." if status["browser_login_available"] else "GitHub app registration is required once before browser sign-in.")
            fields["notice"].configure(text=message,fg="#f59e0b" if session.get("state")=="error" else MUTED)
            items=status["resources"] if status["signed_in"] else []
            signature=repr(items)
            if fields["signature"]!=signature:
                fields["signature"]=signature
                selected_id=fields["resource_map"].get(fields["choice"].get())
                counts: dict[str,int]={}
                for resource in items:
                    name=str(resource["label"])
                    counts[name]=counts.get(name,0)+1
                choices: dict[str,str]={}
                for resource in items:
                    name=str(resource["label"])
                    display=f"{name} ({resource['id']})" if counts[name]>1 else name
                    # Provider account names need not be unique, including names
                    # that already look like a generated disambiguation label.
                    original=display
                    duplicate=2
                    while display in choices:
                        display=f"{original} · {duplicate}"
                        duplicate+=1
                    choices[display]=resource["id"]
                fields["resource_map"]=choices
                fields["resources"].configure(values=list(fields["resource_map"]))
                selected=next((name for name,resource_id in choices.items() if resource_id==selected_id),None)
                fields["choice"].set(selected or (next(iter(choices)) if len(choices)==1 else ""))
            fields["import"].configure(state="normal" if items and not pending else "disabled")
        if self.current_view=="integrations": self._login_tick_id=self.after(400,self._poll_browser_logins)

    def _import_browser_context(self, provider: str) -> None:
        fields=self._browser_fields[provider]
        resource=fields["resource_map"].get(fields["choice"].get())
        if not resource:
            fields["notice"].configure(text="Choose an account or repository first.",fg="#f59e0b");return
        fields["notice"].configure(text="Importing context…")
        def work():
            try: return self.login_service.select(provider,resource)
            except Exception: return {"ok":False,"error":"Could not import context. Check your sign-in permissions and try again."}
        def done(result):
            self.footer.configure(text=f"Imported {result.get('imported_count',0)} captures into your connection's project." if result.get("ok") else result["error"],fg="#62d6ad" if result.get("ok") else "#f59e0b")
            self._request_refresh()
        self._job(work,done)

    def _disconnect_browser_login(self, provider: str) -> None:
        from owlthread.integrations.context import ContextConnectorService
        self.login_service.cancel(provider)
        self._mutate(lambda:ContextConnectorService(self.db).disconnect(provider),lambda _:self.show_view("integrations"))

    def _token_connector_card(self, pane: tk.Frame, item: dict[str,Any]) -> None:
        integration_id=item["id"]
        card=tk.Frame(pane,bg=CARD,padx=16,pady=16)
        card.pack(fill="x",pady=(0,12))
        top=tk.Frame(card,bg=CARD)
        top.pack(fill="x")
        label(top,item["name"],15,bold=True).pack(side="left")
        state={"disabled_unconnected":"Ready to set up","credentials_required":"Token required","options_required":"Resource details required",
               "credential_unavailable":"Saved token unavailable · enter it again",
               "project_required":"Project required","scopes_required":"Select a read scope","unverified":"Saved · test access",
               "connected":"Access verified","verification_expired":"Test access again","error":"Connection needs attention"}.get(item.get("connection_state"),"Ready to set up")
        label(top,state,10,"#62d6ad" if item.get("connected") else MUTED).pack(side="right")
        stored_project=next((p["name"] for p in self._projects if p["id"]==item.get("project_id")),None)
        target=f"Configured project: {stored_project}" if stored_project else f"Setup will use project: {self.project.get()}"
        label(card,target,10,ACCENT).pack(fill="x",pady=(7,12))
        fields: dict[str,Any]={"scopes":{},"buttons":[],"saved_options":item.get("options") or {},
                              "saved_scopes":set(item.get("configured_scopes") or [])}
        self.integration_fields[integration_id]=fields
        options=item.get("options") or {}
        descriptors=(("account_id","Account ID"),("zone_id","Zone ID (for DNS only)")) if integration_id=="cloudflare" else (("repository","Repository (owner/name)"),)
        resources=tk.Frame(card,bg=CARD)
        resources.pack(fill="x")
        for index,(key,title) in enumerate(descriptors):
            resources.columnconfigure(index,weight=1,uniform="resources")
            resource=tk.Frame(resources,bg=CARD)
            resource.grid(row=0,column=index,sticky="ew",padx=(0,10 if index<len(descriptors)-1 else 0))
            label(resource,title,10).pack(fill="x",pady=(5,4))
            var=tk.StringVar(value=options.get(key,"") or "")
            fields[key]=var
            tk.Entry(resource,textvariable=var,bg="#19192d",fg=TEXT,insertbackground=ACCENT,relief="flat",font=("Segoe UI",11)).pack(fill="x",ipady=7)
        label(card,"API token · leave empty to keep the saved token" if item.get("credential_stored") else "API token",10).pack(fill="x",pady=(10,4))
        fields["token"]=tk.StringVar(value="")
        fields["token_widget"]=tk.Entry(card,textvariable=fields["token"],show="•",bg="#19192d",fg=TEXT,insertbackground=ACCENT,relief="flat",font=("Segoe UI",11))
        fields["token_widget"].pack(fill="x",ipady=7)
        help_text="Use a Cloudflare API token scoped to this account: Zone Read, DNS Read, Workers Scripts Read, or Pages Read for the options you select." if integration_id=="cloudflare" else "Use a GitHub fine-grained token limited to this repository with Metadata, Issues, and Pull requests read access as needed."
        hint=label(card,help_text,9,MUTED)
        hint.configure(wraplength=760)
        hint.pack(fill="x",pady=(6,10))
        hint.bind("<Configure>",lambda event,w=hint:w.configure(wraplength=max(180,event.width)))
        configured=set(item.get("configured_scopes") or [])
        supported=item.get("supported_scopes") or []
        scope_labels={"zones.read":"Domains and zones","dns.read":"DNS records","workers.read":"Worker details",
                      "pages.read":"Pages projects","repositories.read":"Repository details","issues.read":"Issues",
                      "pull-requests.read":"Pull requests"}
        scope_grid=tk.Frame(card,bg=CARD)
        scope_grid.pack(fill="x")
        for index,scope in enumerate(supported):
            var=tk.BooleanVar(value=scope in configured)
            fields["scopes"][scope]=var
            tk.Checkbutton(scope_grid,text=scope_labels.get(scope,scope),variable=var,bg=CARD,fg=TEXT,selectcolor="#19192d",
                           activebackground=CARD,activeforeground=TEXT,font=("Segoe UI",10)).grid(row=index//2,column=index%2,sticky="w",padx=(0,30))
        details=[]
        if item.get("last_checked_at"): details.append("Access tested "+_relative_time(item["last_checked_at"]))
        if item.get("last_sync_at"): details.append("Last import "+_relative_time(item["last_sync_at"]))
        if item.get("last_error"): details.append(str(item["last_error"]))
        fields["notice"]=label(card," · ".join(details),10,"#f59e0b" if item.get("last_error") else MUTED)
        fields["notice"].configure(wraplength=760)
        fields["notice"].pack(fill="x",pady=(10,8))
        actions=tk.Frame(card,bg=CARD)
        actions.pack(fill="x")
        for title,operation,primary in (("Save connection","save",True),("Test access","test",False),("Import context","sync",False)):
            control=button(actions,title,lambda key=integration_id,op=operation:self._integration_action(key,op),primary)
            control.pack(side="left",padx=(0,8))
            fields["buttons"].append(control)
        if item.get("enabled") or item.get("credential_stored"):
            control=button(actions,"Disconnect",lambda key=integration_id:self._integration_action(key,"disconnect"))
            control.pack(side="right")
            fields["buttons"].append(control)

    def _integration_action(self, integration_id: str, operation: str) -> None:
        if operation in {"save","disconnect"}: self.login_service.cancel(integration_id)
        from owlthread.integrations.context import ContextConnectorService
        fields=self.integration_fields[integration_id]
        notice=fields["notice"]
        revision=self._view_revision
        name=self.project.get()
        options={key:fields[key].get().strip() for key in (("account_id","zone_id") if integration_id=="cloudflare" else ("repository",))}
        scopes=[scope for scope,var in fields["scopes"].items() if var.get()]
        token=fields["token"].get().strip() or None
        saved_options={key:fields["saved_options"].get(key,"") or "" for key in options}
        if operation in {"test","sync"} and (token or options!=saved_options or set(scopes)!=fields["saved_scopes"]):
            notice.configure(text="Save connection changes before testing or importing context.",fg="#f59e0b")
            return
        controls=fields["buttons"]
        def reset() -> None:
            if self.current_view=="integrations" and self._view_revision==revision:
                for control in controls: control.configure(state="normal")
                notice.configure(text="Connection action failed. Check the token, resource details and selected permissions.",fg="#f59e0b")
        def work() -> Any:
            service=ContextConnectorService(self.db)
            try:
                if operation=="save":
                    result=service.configure(integration_id,token=token,options=options,scopes=scopes,project_id=self.db.get_or_create_project(name))
                elif operation=="disconnect":
                    result=service.disconnect(integration_id)
                else:
                    # Test/import use the saved connection so editing a draft cannot silently grant access.
                    result=getattr(service,operation)(integration_id)
            except (ValueError,PermissionError) as exc:
                result={"ok":False,"error":str(exc)}
            return result,self._snapshot(name)
        def done(value: Any) -> None:
            result,snapshot=value
            self._apply_snapshot(snapshot)
            if operation=="sync":
                message=f"Imported {result.get('imported_count',0)} captures · {result.get('duplicate_count',0)} already saved. Use Extract now when ready."
            elif operation=="save": message="Connection saved. Test access before importing context."
            elif operation=="disconnect": message="Provider disconnected. Imported captures remain saved locally."
            else: message="Provider access verified." if result.get("ok") else "Provider access failed. Check the connection details."
            if result.get("ok") is False:
                message=str(result.get("error") or result.get("last_error") or result.get("status",{}).get("last_error") or "Provider request failed. Check access and try again.")
            self.footer.configure(text=message,fg="#f59e0b" if result.get("ok") is False else "#62d6ad")
            if self.current_view=="integrations" and self._view_revision==revision:
                if result.get("ok") is False:
                    for control in controls: control.configure(state="normal")
                    notice.configure(text=message,fg="#f59e0b")
                else:
                    self.show_view("integrations")
        if self._job(work,done,on_error=reset):
            notice.configure(text={"save":"Saving connection…","test":"Testing saved connection…","sync":"Importing context…","disconnect":"Disconnecting provider…"}[operation],fg=MUTED)
            for control in controls: control.configure(state="disabled")

    def _set_integration_read_access(self, integration_id: str, enabled: bool) -> None:
        from owlthread.integrations.catalog import get_spec
        from owlthread.integrations.registry import IntegrationRegistry
        read_scopes = [scope.name for scope in get_spec(integration_id).scopes if scope.risk == "read"] if enabled else []
        pid = self._pid() or None
        def done(_: Any) -> None:
            self.footer.configure(text=("Read-only grant prepared; connect the provider before use." if enabled else "Integration grant disabled."),fg="#62d6ad")
            if self.current_view == "integrations":
                self.show_view("integrations")
        self._mutate(lambda:IntegrationRegistry(self.db).configure(integration_id,enabled=enabled,scopes=read_scopes,project_id=pid),done)

    def _view_settings(self) -> None:
        self._heading("Settings","Manage your browser connection, AI provider and capture preferences.")
        save_bar = tk.Frame(self.page,bg=BG)
        save_bar.pack(side="bottom",fill="x",pady=(12,0))
        label(save_bar,"Changes apply when you save.  ·  Ctrl+S",9,MUTED).pack(side="left")
        button(save_bar,"Save settings",self._save_settings,True).pack(side="right")
        tabs = SegmentedTabs(self.page)
        tabs.pack(fill="both",expand=True)
        sections = {}
        for title in ("Browser", "AI model", "Capture", "Advanced"):
            frame = tk.Frame(tabs,bg=BG,padx=4,pady=16)
            tabs.add(frame,text=title)
            sections[title] = self._scroll(frame).content
        self.settings_tabs = tabs
        values = self._settings | self._settings_draft
        pane = sections["Browser"]
        label(pane,"BROWSER CONNECTION",10,ACCENT,True).pack(fill="x",pady=(0,10))
        receiver=label(pane,f"Receiver: http://127.0.0.1:{self.port} · selected project: {self.project.get()}\nChoose this same project in the extension popup to see its captures here.",10,MUTED)
        receiver.configure(wraplength=760)
        receiver.pack(fill="x",pady=(0,10))
        label(pane,"Copy the pairing secret into the extension popup → Connection settings. Keep it private.",10,MUTED).pack(fill="x")
        browser_actions=tk.Frame(pane,bg=BG)
        browser_actions.pack(fill="x",pady=(10,20))
        button(browser_actions,"Copy pairing secret",self._copy_pairing_secret).pack(side="left",padx=(0,10))
        button(browser_actions,"Revoke browser connections",lambda:self._copy_pairing_secret(True)).pack(side="left")
        pane = sections["AI model"]
        label(pane,"MODEL CONNECTION",10,ACCENT,True).pack(fill="x",pady=(0,10))
        privacy = label(pane,"Fallback and local Ollama keep context on this machine. A remote provider receives the context used for extraction and briefs.",10,MUTED)
        privacy.configure(wraplength=600)
        privacy.pack(fill="x",pady=(0,16))
        privacy.bind("<Configure>",lambda event:privacy.configure(wraplength=max(200,event.width)))
        self.setting_vars: dict[str,tk.StringVar] = {}
        for key,title in (("llm_provider","Provider"),("llm_model","Model"),("llm_api_key","API key"),("llm_base_url","Base URL")):
            row = tk.Frame(pane,bg=BG)
            row.pack(fill="x",pady=6)
            label(row,title,11).pack(anchor="w",pady=(0,6))
            var = tk.StringVar(value=values.get(key,"fallback" if key=="llm_provider" else ""))
            self.setting_vars[key] = var
            field = RoundedFrame(row,bg=CARD,radius=12,padx=12,pady=8)
            field.pack(fill="x")
            if key=="llm_provider":
                widget = ttk.Combobox(field,textvariable=var,values=list(DEFAULTS),state="readonly",width=48)
                widget.bind("<<ComboboxSelected>>",self._provider_changed)
            else:
                widget = tk.Entry(field,textvariable=var,bg=CARD,fg=TEXT,insertbackground=ACCENT,relief="flat",width=50,
                                  show="•" if key=="llm_api_key" else "",font=("Segoe UI",11))
            widget.pack(fill="x",ipady=3)
        if "llm_api_key" in self.db.unavailable_secret_settings:
            label(pane,"Saved model key cannot be unlocked on this Windows account. Enter it again and save settings.",
                  10,"#f59e0b").pack(fill="x",pady=(6,10))
        self.connection_notice = label(pane,"",10,MUTED)
        self.connection_notice.pack(fill="x",pady=6)
        button(pane,"Test connection",self._test_connection).pack(anchor="e",pady=(0,24))
        pane = sections["Advanced"]
        label(pane,"SYSTEM PROMPTS",10,ACCENT,True).pack(fill="x",pady=(0,12))
        self.prompt_fields: dict[str,tk.Text] = {}
        for key,title in (("extraction_prompt","Extraction instructions"),("primer_prompt","Primer instructions"),
                          ("page_context_prompt","On-demand page awareness"),
                          ("capture_importance_prompt","Legacy smart-capture gate (raw AI turns bypass this)")):
            label(pane,title,11).pack(fill="x",pady=(8,6))
            prompt_box = RoundedFrame(pane,bg=CARD,padx=16,pady=12)
            prompt_box.pack(fill="x")
            text = tk.Text(prompt_box,height=4,bg=CARD,fg=TEXT,insertbackground=ACCENT,wrap="word",relief="flat",padx=0,pady=0,font=("Segoe UI",10))
            text.insert("1.0",values.get(key,""))
            text.pack(fill="x")
            self.prompt_fields[key] = text
        label(pane,"Leave a prompt empty to restore the built-in instructions.",9,MUTED).pack(fill="x",pady=10)
        pane = sections["Capture"]
        label(pane,"CAPTURE PREFERENCES",10,ACCENT,True).pack(fill="x",pady=(0,12))
        self.paused = tk.BooleanVar(value=values.get("capture_paused","false")=="true")
        self.capture_options = {}
        for key,title,default in (("strict_site_isolation","Strict site isolation (disables origin-blind clipboard monitoring)","true"),
                                  ("clipboard_enabled","Read qualifying clipboard text (requires strict isolation off)","false"),
                                  ("ide_capture_enabled","Read local Cursor and VS Code chat stores (experimental)","false")):
            var=tk.BooleanVar(value=values.get(key,default)=="true")
            self.capture_options[key]=var
            control=tk.Checkbutton(pane,text=title,variable=var,bg=BG,fg=TEXT,selectcolor=CARD,activebackground=BG,activeforeground=TEXT,justify="left",anchor="w")
            control.pack(fill="x",pady=6)
            control.bind("<Configure>",lambda event,w=control:w.configure(wraplength=max(150,event.width-35)))
        label(pane,"Capture source changes apply after restarting OwlThread. Keep strict isolation on to guarantee blocked-site text cannot enter through the clipboard, which has no source URL.",9,MUTED).pack(fill="x",pady=6)
        tk.Checkbutton(pane,text="Pause browser, clipboard and IDE capture",variable=self.paused,bg=BG,fg=TEXT,selectcolor=CARD,
                       activebackground=BG,activeforeground=TEXT).pack(anchor="w",pady=10)


    def _copy_pairing_secret(self, rotate: bool = False) -> None:
        from owlthread.security import local_token
        def work() -> bool:
            return self.primer_engine._copy(local_token(self.db,rotate=rotate))
        self._job(work,lambda copied:self.footer.configure(text=("Connections revoked. " if rotate else "")+
            ("Pairing secret copied. Paste it only into OwlThread's extension popup." if copied else "Clipboard unavailable. Try again.")))

    def _provider_changed(self, event: tk.Event | None = None) -> None:
        base,model = DEFAULTS[self.setting_vars["llm_provider"].get()]
        self.setting_vars["llm_base_url"].set(base)
        self.setting_vars["llm_model"].set(model)
        self.setting_vars["llm_api_key"].set("")

    def _settings_values(self) -> dict[str,str]:
        values={key:var.get().strip() for key,var in self.setting_vars.items()}
        values.update({key:field.get("1.0","end").strip() for key,field in self.prompt_fields.items()})
        values["capture_paused"]="true" if self.paused.get() else "false"
        values.update({key:"true" if var.get() else "false" for key,var in self.capture_options.items()})
        return values

    def _save_settings(self) -> None:
        values = self._settings_values()
        self._settings_draft = values.copy()
        self._mutate(lambda:[self.db.set_setting(key,value) for key,value in values.items()],
            lambda _:self.footer.configure(text="Settings saved. New requests use this configuration.",fg="#62d6ad"))

    def _test_connection(self) -> None:
        client = LLMClient(**{key.removeprefix("llm_"):var.get().strip() for key,var in self.setting_vars.items()})
        self.connection_notice.configure(text="Testing connection…")
        def done(result: Any) -> None:
            if self.current_view=="settings":
                self.connection_notice.configure(text=f"Connected · {result['latency_ms']} ms" if result["success"] else result["error"],
                                                 fg="#62d6ad" if result["success"] else "#f59e0b")
        self._job(client.test_connection,done)

    def _job(self, work: Callable[[],Any], callback: Callable[[Any],None], *,
             on_error: Callable[[],None] | None = None, quiet: bool = False) -> bool:
        self._workers = [t for t in self._workers if t.is_alive()]
        if len(self._workers)>=2:
            if not quiet:
                self.footer.configure(text="Please wait for the current operation to finish.")
            return False
        def run() -> None:
            try:
                result = work()
                self._actions.put(lambda:callback(result))
            except Exception:
                logger.exception("Desktop operation failed")
                def failed() -> None:
                    self._refresh_busy=False
                    if on_error: on_error()
                    if not quiet:
                        self.footer.configure(text="Operation failed. Your captures remain saved.",fg="#f59e0b")
                self._actions.put(failed)
        thread = threading.Thread(target=run,daemon=True,name="OwlThread-UIWorker")
        self._workers.append(thread)
        thread.start()
        return True

    def _flush_done(self, result: dict[str,Any]) -> None:
        self.footer.configure(text=f"Extracted {result['total_extracted']} memories · {result['total_superseded']} updated · {len(result.get('errors',[]))} errors",fg="#f59e0b" if result.get("errors") else "#62d6ad")
        self._refresh_busy=False
        name=self.project.get()
        self._job(lambda:self._snapshot(name),self._apply_snapshot)

    def open_primer(self) -> None:
        self._popups = [p for p in self._popups if p.winfo_exists() or (p.panel._worker and p.panel._worker.is_alive())]
        for popup in self._popups:
            if popup.winfo_exists():
                popup.lift()
                popup.panel.input.focus_force()
                popup._activity()
                return
        popup = PrimerPopupUI(self,self.primer_engine)
        self._popups.append(popup)

    def _tick(self) -> None:
        while not self._actions.empty() and not self._closing:
            try:
                self._actions.get_nowait()()
            except Exception:
                logger.exception("Desktop update failed")
                self.footer.configure(text="Display update failed. Your captures remain saved.",fg="#f59e0b")
        if not self._closing:
            self._tick_id = self.after(80,self._tick)

    def _refresh(self) -> None:
        if self._closing:
            return
        if not self._refresh_busy:
            name=self.project.get()
            self._refresh_busy=True
            if not self._job(lambda:self._snapshot(name),self._apply_snapshot,quiet=True):
                self._refresh_busy=False
        self._refresh_id = self.after(1500,self._refresh)

    def _request_refresh(self) -> None:
        if self._refresh_id:
            self.after_cancel(self._refresh_id)
            self._refresh_id=None
        self._refresh()

    def _wheel(self, event: tk.Event) -> None:
        # Text widgets own their wheel events; scroll only the pane under the pointer.
        if isinstance(event.widget,tk.Text):
            return
        for scroll in self._scrolls:
            if scroll.winfo_exists() and scroll.winfo_ismapped():
                scroll.wheel(event)
                break

    def _on_close(self) -> None:
        if self._closing:
            return
        self._closing = True
        self.login_service.close()
        if self._hotkey:
            self._hotkey.stop()
        if self.on_quit:
            self.on_quit()
        self.withdraw()
        threads = self._workers+[p._worker for p in getattr(self,"_panels",[]) if p._worker]+[p.panel._worker for p in self._popups if p.panel._worker]
        def shutdown() -> None:
            if self.engine:
                self.engine.stop()
            for thread in threads:
                thread.join()
            if self._owns_db:
                self.db.close()
        worker = threading.Thread(target=shutdown,daemon=True,name="OwlThread-Shutdown")
        worker.start()
        def finish() -> None:
            if worker.is_alive():
                self.after(100,finish)
            else:
                self.destroy()
        finish()

    def destroy(self) -> None:
        self._closing=True
        self.login_service.close()
        for task in (self._tick_id,self._refresh_id,self._search_id,self._login_tick_id):
            if task:
                self.after_cancel(task)
        super().destroy()


OwlThreadDesktopApp = OwlThreadApp


def run_app(port: int = DEFAULT_HTTP_PORT) -> None:
    app = OwlThreadApp(port=port)
    app.mainloop()
