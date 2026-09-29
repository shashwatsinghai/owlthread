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
from owlthread.gui.feed_card import FeedCard
from owlthread.hotkey import WindowsHotkeyListener
from owlthread.primer.engine import PrimerEngine
from owlthread.primer.llm import LLMClient, DEFAULTS
from owlthread.primer.search import MemorySearcher
from owlthread.primer.ui import PrimerPanel, PrimerPopupUI

logger = logging.getLogger(__name__)
BG,CARD,TEXT,MUTED,ACCENT = "#1a1a2e","#222239","#e2e8f0","#a4abc2","#a7a1ff"


def label(master: tk.Misc, text: str, size: int = 11, color: str = TEXT, bold: bool = False) -> tk.Label:
    return tk.Label(master,text=text,bg=master.cget("bg"),fg=color,font=("Segoe UI",size,"bold" if bold else "normal"),
                    justify="left",anchor="w")


def button(master: tk.Misc, text: str, command: Callable[[],None], primary: bool = False) -> tk.Button:
    return tk.Button(master,text=text,command=command,bg=ACCENT if primary else "#30304b",fg="#161628" if primary else TEXT,
                     activebackground="#b7b1ff" if primary else "#41415f",activeforeground="#161628" if primary else TEXT,
                     relief="flat",bd=0,padx=15,pady=9,font=("Segoe UI",10,"bold"),cursor="hand2")


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
        self.title("OwlThread — State your task, get context.")
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
        self.project = tk.StringVar(value=self._settings.get("active_project","General"))
        self._style()
        self._build()
        self.protocol("WM_DELETE_WINDOW",self._on_close)
        self.bind("<MouseWheel>",self._wheel)
        self.bind("<Button-4>",self._wheel)
        self.bind("<Button-5>",self._wheel)
        self.bind("<Control-Shift-P>",lambda _:self.open_primer())
        self.bind("<Control-Shift-p>",lambda _:self.open_primer())
        self._tick()
        self.show_view("feed")
        if self.engine:
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
        style.configure("TCombobox",fieldbackground=CARD,background=CARD,foreground=TEXT,arrowcolor=MUTED,
                        bordercolor="#42425e",padding=6)
        style.map("TCombobox",fieldbackground=[("readonly",CARD)],foreground=[("readonly",TEXT)])
        style.configure("Vertical.TScrollbar",background="#42425e",troughcolor=BG,arrowcolor=MUTED,borderwidth=0)

    def _build(self) -> None:
        sidebar = tk.Frame(self,bg="#141425",width=64)
        sidebar.pack(side="left",fill="y")
        sidebar.pack_propagate(False)
        logo = tk.Canvas(sidebar,width=64,height=78,bg="#141425",highlightthickness=0)
        logo.pack()
        logo.create_polygon(15,23,22,31,42,31,49,23,47,53,32,65,17,53,fill=ACCENT,smooth=True)
        for x in (24,40):
            logo.create_oval(x-7,34,x+7,48,fill="#141425",outline="")
            logo.create_oval(x-2,38,x+2,44,fill=TEXT,outline="")
        self.nav: dict[str,tk.Button] = {}
        for key,symbol,title in (("feed","≡","Feed"),("search","⌕","Search"),("quadrants","▦","Memory"),("primer","ϟ","Ask"),("capture","+","Capture"),("integrations","⎈","Connect"),("settings","⚙","Settings")):
            nav = tk.Button(sidebar,text=symbol+"\n"+title,command=lambda k=key:self.show_view(k),bg="#141425",fg=MUTED,
                            activebackground="#2b2a48",activeforeground=TEXT,font=("Segoe UI",10),relief="flat",pady=12,cursor="hand2")
            nav.pack(side="bottom" if key=="settings" else "top",fill="x",pady=3)
            self.nav[key] = nav
        container = tk.Frame(self,bg=BG)
        container.pack(side="left",fill="both",expand=True,padx=34,pady=26)
        header = tk.Frame(container,bg=BG)
        header.pack(fill="x",pady=(0,24))
        label(header,"OWLTHREAD  /  PERSONAL MEMORY",9,MUTED,True).pack(side="left")
        self.project_menu = ttk.Combobox(header,textvariable=self.project,values=[p["name"] for p in self._projects],width=20)
        self.project_menu.pack(side="right")
        self.project_menu.bind("<<ComboboxSelected>>",self._project_changed)
        self.project_menu.bind("<Return>",self._project_changed)
        label(header,"Project   ",9,MUTED).pack(side="right")
        self.page = tk.Frame(container,bg=BG)
        self.page.pack(fill="both",expand=True)
        self.footer = label(container,"Local storage  ·  No telemetry  ·  Ctrl+Shift+P for context",9,MUTED)
        self.footer.pack(fill="x",pady=(14,0))

    def _project_changed(self, event: tk.Event | None = None) -> None:
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
        return {"name":name,"projects":self.db.list_projects(),"settings":self.db.get_all_settings(),
                "rows":self.db.get_entries(project_id=pid,limit=500),
                "counts":(self.db.count_entries(project_id=pid),self.db.pending_count()),
                "pending":self.db.execute_read("SELECT id,source_app,extraction_status,extraction_reason,attempts,processed_chars FROM capture_buffer WHERE processed=0 AND project_id=? ORDER BY id LIMIT 100",(pid,))}

    def _apply_snapshot(self, data: dict[str,Any]) -> None:
        self._refresh_busy=False
        if data["name"] != self.project.get():
            return
        changed=self._rows != data["rows"] or self._counts != data["counts"] or getattr(self,"_pending",[]) != data["pending"]
        self._rows,self._counts,self._settings,self._projects=data["rows"],data["counts"],data["settings"],data["projects"]
        self._pending=data["pending"]
        self.project_menu.configure(values=[p["name"] for p in self._projects])
        if changed and self.current_view in {"feed","quadrants"}:
            self.show_view(self.current_view)
        elif changed and self.current_view=="pending":
            self._view_pending()

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
        label(self.page,title,28,bold=True).pack(fill="x",pady=(0,8))
        label(self.page,subtitle,11,MUTED).pack(fill="x",pady=(0,24))

    def _scroll(self, master: tk.Misc | None = None) -> ScrollFrame:
        scroll = ScrollFrame(master or self.page)
        scroll.pack(fill="both",expand=True)
        self._scrolls.append(scroll)
        return scroll

    def show_view(self, key: str) -> None:
        if self._closing:
            return
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
        for name,nav in self.nav.items():
            nav.configure(bg="#2c2b4a" if name==key else "#141425",fg=ACCENT if name==key else MUTED)
        self.views[key] = self.page
        getattr(self,"_view_"+key)()

    def _view_feed(self) -> None:
        self._heading("Your work, remembered.","A living record of the architecture, rules and decisions that matter.")
        stats = tk.Frame(self.page,bg=BG)
        stats.pack(fill="x",pady=(0,22))
        count = self._counts[0]
        label(stats,f"{count} active memories",13,bold=True).pack(side="left")
        label(stats,f"   ·   {self._counts[1]} waiting to extract",10,MUTED).pack(side="left")
        button(stats,"Extract now",lambda:self._job(self.primer_engine.pipeline.handle_done_signal,self._flush_done)).pack(side="right")
        button(stats,"Pending captures",self._view_pending).pack(side="right",padx=6)
        self.feed_scroll = self._scroll().content
        self.refresh_feed()

    def _view_pending(self) -> None:
        for child in self.page.winfo_children(): child.destroy()
        self._scrolls.clear()
        self.current_view="pending"
        self._heading("Pending captures","Raw captures stay local until extraction succeeds. Failed items can be retried.")
        button(self.page,"Retry extraction",lambda:self._job(self.primer_engine.pipeline.handle_done_signal,self._flush_done)).pack(anchor="w",pady=(0,12))
        pane=self._scroll().content
        for row in getattr(self,"_pending",[]):
            label(pane,f"#{row['id']} · {row['source_app']} · {row['extraction_status']} · {row['attempts']} attempts\n{row['extraction_reason'] or 'Waiting for extraction'}",11).pack(fill="x",pady=8)
        if not getattr(self,"_pending",[]): label(pane,"No pending captures in this project.").pack(fill="x")

    def refresh_feed(self) -> None:
        for child in self.feed_scroll.winfo_children():
            child.destroy()
        rows = self._rows[:100]
        self._cards(self.feed_scroll,rows)

    def _cards(self, master: tk.Misc, rows: list[dict[str,Any]]) -> None:
        if not rows:
            frame = tk.Frame(master,bg=CARD,padx=30,pady=40)
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
        self._heading("Find the thread.","Search decisions, constraints and the details behind them.")
        self.search_query = tk.StringVar()
        entry = tk.Entry(self.page,textvariable=self.search_query,bg=CARD,fg=TEXT,insertbackground=ACCENT,font=("Segoe UI",14),relief="flat")
        entry.pack(fill="x",ipady=13,pady=(0,20))
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
        def done(rows: Any) -> None:
            if self.current_view=="search" and self._view_revision==revision and self.search_query.get()==query:
                self._cards(self.search_results,rows)
        self._job(lambda:MemorySearcher(self.db).search(query,limit=30,project_id=pid),done)

    def _view_quadrants(self) -> None:
        self._heading("The shape of your memory.","Four perspectives. One shared understanding.")
        grid = self._scroll().content
        for index,(quadrant,color) in enumerate(QUADRANT_COLORS.items()):
            grid.columnconfigure(index,weight=1,uniform="quadrants")
            col = tk.Frame(grid,bg=CARD,padx=14,pady=20)
            col.grid(row=0,column=index,sticky="nsew",padx=(0,10))
            title = quadrant.replace("_"," ").title()
            heading = label(col,"● "+title,11,color,True)
            heading.configure(wraplength=145)
            heading.pack(fill="x")
            for row in [r for r in self._rows if r["quadrant"]==quadrant][:5]:
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
        self._heading("Keep what matters.","Add a note, a decision or a conversation to your local capture buffer.")
        self.note = tk.Text(self.page,bg=CARD,fg=TEXT,insertbackground=ACCENT,wrap="word",font=("Segoe UI",12),relief="flat",padx=20,pady=20)
        self.note.pack(fill="both",expand=True,pady=(0,20))
        button(self.page,"Save capture",self._save_capture,True).pack(anchor="e")

    def _save_capture(self) -> None:
        text = self.note.get("1.0","end").strip()
        if text:
            name=self.project.get()
            revision=self._view_revision
            def done(_: Any) -> None:
                if self.current_view=="capture" and self._view_revision==revision and self.note.get("1.0","end").strip()==text:
                    self.note.delete("1.0","end")
                self.footer.configure(text="Capture saved locally. Choose Extract now or type done in Primer.",fg="#62d6ad")
            self._mutate(lambda:self.db.insert_capture(text,"manual",self.db.get_or_create_project(name)),done)

    def _view_integrations(self) -> None:
        """Show the permission catalog without pretending providers are connected."""
        from owlthread.integrations.registry import IntegrationRegistry
        self._heading("Connected ecosystem.","29 permission-scoped integration definitions share one OwlThread memory plane.")
        intro = label(self.page,
            "Every provider starts disabled and unconnected. Preparing read access records only an OwlThread grant for this project; provider authentication and a live adapter are still required. Admin, destructive and trading scopes are never granted here.",
            10,MUTED)
        intro.configure(wraplength=760,justify="left")
        intro.pack(fill="x",pady=(0,16))
        pane = self._scroll().content
        registry = IntegrationRegistry(self.db)
        for item in registry.list():
            card = tk.Frame(pane,bg=CARD,padx=16,pady=14)
            card.pack(fill="x",pady=(0,10))
            top = tk.Frame(card,bg=CARD)
            top.pack(fill="x")
            label(top,item["name"],13,bold=True).pack(side="left")
            state = "Prepared · not connected" if item["enabled"] else "Available · disabled"
            label(top,state,9,"#62d6ad" if item["enabled"] else MUTED).pack(side="right")
            label(card,f"{item['category']} · {str(item['connector_type']).upper()}\n{item['description']}",10,MUTED).pack(fill="x",pady=(7,8))
            configured = item.get("configured_scopes") or []
            if configured:
                label(card,"Project grant: "+", ".join(configured),9,ACCENT).pack(fill="x",pady=(0,8))
            action = (lambda integration_id=item["id"]: self._set_integration_read_access(integration_id,False)) if item["enabled"] else \
                     (lambda integration_id=item["id"]: self._set_integration_read_access(integration_id,True))
            button(card,"Disable grant" if item["enabled"] else "Prepare read-only",action).pack(anchor="e")

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
        self._heading("Make yourself at home.","Local by default. Configure the tools that work for you.")
        pane = self._scroll().content
        label(pane,"BROWSER CONNECTION",10,ACCENT,True).pack(fill="x",pady=(0,10))
        label(pane,"Copy the pairing secret into the extension popup → Connection settings. Keep it private.",10,MUTED).pack(fill="x")
        button(pane,"Copy pairing secret",self._copy_pairing_secret).pack(anchor="w",pady=(10,20))
        button(pane,"Revoke browser connections",lambda:self._copy_pairing_secret(True)).pack(anchor="w",pady=(0,20))
        label(pane,"MODEL CONNECTION",10,ACCENT,True).pack(fill="x",pady=(0,10))
        privacy = label(pane,"Fallback and local Ollama keep context on this machine. A remote provider receives the context used for extraction and briefs.",10,MUTED)
        privacy.configure(wraplength=600)
        privacy.pack(fill="x",pady=(0,16))
        privacy.bind("<Configure>",lambda event:privacy.configure(wraplength=max(200,event.width)))
        self.setting_vars: dict[str,tk.StringVar] = {}
        for key,title in (("llm_provider","Provider"),("llm_model","Model"),("llm_api_key","API key"),("llm_base_url","Base URL")):
            row = tk.Frame(pane,bg=BG)
            row.pack(fill="x",pady=6)
            label(row,title,11).pack(side="left",fill="x")
            var = tk.StringVar(value=self._settings.get(key,"fallback" if key=="llm_provider" else ""))
            self.setting_vars[key] = var
            if key=="llm_provider":
                widget = ttk.Combobox(row,textvariable=var,values=list(DEFAULTS),state="readonly",width=48)
                widget.bind("<<ComboboxSelected>>",self._provider_changed)
            else:
                widget = tk.Entry(row,textvariable=var,bg=CARD,fg=TEXT,insertbackground=ACCENT,relief="flat",width=50,
                                  show="•" if key=="llm_api_key" else "",font=("Segoe UI",11))
            widget.pack(side="right",ipady=7)
        if "llm_api_key" in self.db.unavailable_secret_settings:
            label(pane,"Saved model key cannot be unlocked on this Windows account. Enter it again and save settings.",
                  10,"#f59e0b").pack(fill="x",pady=(6,10))
        self.connection_notice = label(pane,"",10,MUTED)
        self.connection_notice.pack(fill="x",pady=6)
        button(pane,"Test connection",self._test_connection).pack(anchor="e",pady=(0,24))
        label(pane,"SYSTEM PROMPTS",10,ACCENT,True).pack(fill="x",pady=(0,12))
        self.prompt_fields: dict[str,tk.Text] = {}
        for key,title in (("extraction_prompt","Extraction instructions"),("primer_prompt","Primer instructions"),
                          ("page_context_prompt","On-demand page awareness"),
                          ("capture_importance_prompt","Legacy smart-capture gate (raw AI turns bypass this)")):
            label(pane,title,11).pack(fill="x",pady=(8,6))
            text = tk.Text(pane,height=4,bg=CARD,fg=TEXT,insertbackground=ACCENT,wrap="word",relief="flat",padx=12,pady=10,font=("Segoe UI",10))
            text.insert("1.0",self._settings.get(key,""))
            text.pack(fill="x")
            self.prompt_fields[key] = text
        label(pane,"Leave a prompt empty to restore the built-in instructions.",9,MUTED).pack(fill="x",pady=10)
        self.paused = tk.BooleanVar(value=self._settings.get("capture_paused","false")=="true")
        self.capture_options = {}
        for key,title,default in (("strict_site_isolation","Strict site isolation (disables origin-blind clipboard monitoring)","true"),
                                  ("clipboard_enabled","Read qualifying clipboard text (requires strict isolation off)","false"),
                                  ("ide_capture_enabled","Read local Cursor and VS Code chat stores (experimental)","false")):
            var=tk.BooleanVar(value=self._settings.get(key,default)=="true")
            self.capture_options[key]=var
            tk.Checkbutton(pane,text=title,variable=var,bg=BG,fg=TEXT,selectcolor=CARD,activebackground=BG,activeforeground=TEXT).pack(anchor="w",pady=6)
        label(pane,"Capture source changes apply after restarting OwlThread. Keep strict isolation on to guarantee blocked-site text cannot enter through the clipboard, which has no source URL.",9,MUTED).pack(fill="x",pady=6)
        tk.Checkbutton(pane,text="Pause browser, clipboard and IDE capture",variable=self.paused,bg=BG,fg=TEXT,selectcolor=CARD,
                       activebackground=BG,activeforeground=TEXT).pack(anchor="w",pady=10)
        button(pane,"Save settings",self._save_settings,True).pack(anchor="e",pady=10)

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

    def _save_settings(self) -> None:
        values={key:var.get().strip() for key,var in self.setting_vars.items()}
        values.update({key:field.get("1.0","end").strip() for key,field in self.prompt_fields.items()})
        values["capture_paused"]="true" if self.paused.get() else "false"
        values.update({key:"true" if var.get() else "false" for key,var in self.capture_options.items()})
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

    def _job(self, work: Callable[[],Any], callback: Callable[[Any],None]) -> bool:
        self._workers = [t for t in self._workers if t.is_alive()]
        if len(self._workers)>=2:
            self.footer.configure(text="Please wait for the current operation to finish.")
            return False
        def run() -> None:
            try:
                result = work()
                self._actions.put(lambda:callback(result))
            except Exception:
                logger.exception("Desktop operation failed")
                self._refresh_busy=False
                self._actions.put(lambda:self.footer.configure(text="Operation failed. Your captures remain saved.",fg="#f59e0b"))
        thread = threading.Thread(target=run,daemon=True,name="OwlThread-UIWorker")
        self._workers.append(thread)
        thread.start()
        return True

    def _flush_done(self, result: dict[str,Any]) -> None:
        self.footer.configure(text=f"Extracted {result['total_extracted']} memories · {result['total_superseded']} updated · {len(result.get('errors',[]))} errors",fg="#f59e0b" if result.get("errors") else "#62d6ad")
        self._refresh_busy=False
        self._job(lambda:self._snapshot(self._settings.get("active_project","General")),self._apply_snapshot)

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
            self._actions.get_nowait()()
        if not self._closing:
            self._tick_id = self.after(80,self._tick)

    def _refresh(self) -> None:
        if self._closing:
            return
        if not self._refresh_busy:
            name=self.project.get()
            self._refresh_busy=True
            if not self._job(lambda:self._snapshot(name),self._apply_snapshot):
                self._refresh_busy=False
        self._refresh_id = self.after(3000,self._refresh)

    def _wheel(self, event: tk.Event) -> None:
        # Text widgets own their wheel events; scroll only the pane under the pointer.
        if isinstance(event.widget,tk.Text):
            return
        for scroll in self._scrolls:
            if scroll.winfo_exists():
                scroll.wheel(event)
                break

    def _on_close(self) -> None:
        if self._closing:
            return
        self._closing = True
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
        for task in (self._tick_id,self._refresh_id,self._search_id):
            if task:
                self.after_cancel(task)
        super().destroy()


OwlThreadDesktopApp = OwlThreadApp


def run_app(port: int = DEFAULT_HTTP_PORT) -> None:
    app = OwlThreadApp(port=port)
    app.mainloop()
