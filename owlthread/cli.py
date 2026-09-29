"""OwlThread CLI and live subprocess transcript capture."""
from __future__ import annotations
import argparse
import codecs
import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, BinaryIO, TextIO

from owlthread.config import DEFAULT_HTTP_PORT,SOURCE_CLI


def _show_desktop_error(message: str) -> None:
    """Make failures visible when a batch launcher uses pythonw or a GUI exe."""
    if os.name == "nt":
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, message, "OwlThread could not open", 0x10)

logger = logging.getLogger(__name__)


def run_wrapped_command(cmd_args: list[str], db: Database | None = None, project: str | None = None,
                        max_output_bytes: int = 2_000_000) -> int:
    """Tee both output streams immediately; spool large transcripts to disk."""
    if not cmd_args:
        print("No command specified.",file=sys.stderr)
        return 1
    owns = db is None
    if db is None:
        from owlthread.db.database import Database
        db = Database()
    lock = threading.Lock()
    errors: list[Exception] = []
    captured_bytes = 0
    truncated = False
    with tempfile.TemporaryFile(mode="w+b") as transcript:
        def reader(pipe: BinaryIO, destination: TextIO) -> None:
            nonlocal captured_bytes,truncated
            decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
            try:
                while True:
                    chunk = os.read(pipe.fileno(),4096)
                    if not chunk:
                        break
                    with lock:
                        keep=chunk[:max(0,max_output_bytes-captured_bytes)]
                        transcript.write(keep)
                        captured_bytes+=len(keep)
                        truncated = truncated or len(keep)<len(chunk)
                    text = decoder.decode(chunk)
                    if destination:
                        destination.write(text)
                        destination.flush()
                tail = decoder.decode(b"",final=True)
                if tail and destination:
                    destination.write(tail)
                    destination.flush()
            except Exception as exc:
                errors.append(exc)
                logger.exception("Could not tee command output")
            finally:
                pipe.close()
        try:
            executable = shutil.which(cmd_args[0]) or cmd_args[0]
            command: Any = [executable,*cmd_args[1:]]
            process = subprocess.Popen(command,stdout=subprocess.PIPE,stderr=subprocess.PIPE,shell=False)
        except OSError as exc:
            print(f"Could not start {cmd_args[0]}: {exc}",file=sys.stderr)
            if owns:
                db.close()
            return 127
        workers = [threading.Thread(target=reader,args=(pipe,dest),daemon=True,name="OwlThread-CLIStream")
                   for pipe,dest in ((process.stdout,sys.stdout),(process.stderr,sys.stderr))]
        for worker in workers:
            worker.start()
        try:
            code = process.wait()
        except KeyboardInterrupt:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            code = 130
        for worker in workers:
            worker.join()
        try:
            transcript.seek(0)
            decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
            pid = db.get_or_create_project(project) if project else db.get_or_create_project(Path.cwd().name,str(Path.cwd()))
            part = 0
            while True:
                chunk = transcript.read(65536)
                text = decoder.decode(chunk,final=not chunk)
                if text.strip():
                    part += 1
                    db.insert_capture(text,SOURCE_CLI,pid,{"command":cmd_args,"exit_code":code,"part":part,"truncated":truncated})
                if not chunk:
                    break
            if errors:
                print("Some output could not be read; captured portions were saved.",file=sys.stderr)
            if truncated:
                print("Transcript reached the 2 MB capture limit; remaining output was streamed but not saved.",file=sys.stderr)
        except Exception:
            logger.exception("Could not persist command transcript")
            return code or 1
        finally:
            if owns:
                db.close()
    return code


def print_entries_table(db: Database, limit: int = 20, source: str | None = None, include_history: bool = False) -> None:
    rows = db.get_entries(limit=limit,source_app=source,include_history=include_history)
    color = bool(sys.stdout and sys.stdout.isatty() and not os.environ.get("NO_COLOR"))
    print("ID     QUADRANT                  SOURCE                MEMORY")
    print("─"*90)
    for row in rows:
        badge = row["quadrant"].replace("_"," ")
        text = f"{row['id']:<6} {badge:<25} {row['source_app']:<21} {(row['summary'] or '').replace(chr(10),' ')}"
        print(("\033[36m"+text+"\033[0m") if color else text)
    if not rows:
        print("No memories yet. Capture context and run owlthread done.")


def main(argv: list[str] | None = None) -> int:
    if sys.stderr is None:  # pythonw.exe and the packaged GUI have no console.
        logging.basicConfig(level=logging.INFO,handlers=[logging.NullHandler()])
    else:
        logging.basicConfig(level=logging.INFO,format="%(levelname)s %(name)s: %(message)s")
    for stream in (sys.stdout,sys.stderr):
        if stream and hasattr(stream,"reconfigure"):
            stream.reconfigure(encoding="utf-8",errors="replace")
    parser = argparse.ArgumentParser(prog="owlthread",description="State your task, get context.")
    from owlthread import __version__
    parser.add_argument("--version", action="version", version="OwlThread " + __version__)
    parser.add_argument("--db-path",help="Override the local database location")
    subs = parser.add_subparsers(dest="command")
    start = subs.add_parser("start",help="Start capture, tray and global shortcut")
    start.add_argument("--headless",action="store_true")
    start.add_argument("--port",type=int,default=DEFAULT_HTTP_PORT)
    start.add_argument("--no-clipboard",action="store_true")
    start.add_argument("--no-connectors",action="store_true")
    primer = subs.add_parser("primer",aliases=["query"],help="Generate and copy a task context brief")
    primer.add_argument("query",nargs="*")
    primer.add_argument("--ui",action="store_true")
    primer.add_argument("--intent",choices=["dev_task","external_comms","status_query","other"])
    primer.add_argument("--limit",type=int,default=12)
    primer.add_argument("--include-history",action="store_true")
    primer.add_argument("--project-id",type=int)
    run = subs.add_parser("run",help="Run a command and capture stdout and stderr")
    run.add_argument("--project",help="Explicit project for the command transcript")
    run.add_argument("cmd",nargs=argparse.REMAINDER)
    entries = subs.add_parser("entries",help="Read memory entries")
    entries.add_argument("-n","--limit",type=int,default=20)
    entries.add_argument("--source")
    entries.add_argument("--include-history",action="store_true")
    status = subs.add_parser("status",help="Check running capture service and database counts")
    status.add_argument("--port",type=int,default=DEFAULT_HTTP_PORT)
    test = subs.add_parser("test-capture",help="Save text into the durable capture buffer")
    test.add_argument("text")
    test.add_argument("--source",default="manual")
    test.add_argument("--project",default="General")
    subs.add_parser("done",aliases=["flush"],help="Extract pending captures into memory")
    subs.add_parser("projects",help="List local projects")
    git_capture=subs.add_parser("git-capture",help="Explicit opt-in Git snapshot; no background monitoring")
    git_capture.add_argument("--repo",default=".")
    git_mode=git_capture.add_mutually_exclusive_group()
    git_mode.add_argument("--enable",action="store_true")
    git_mode.add_argument("--disable",action="store_true")
    git_capture.add_argument("--file",action="append",default=[])
    git_capture.add_argument("--exclude",action="append")
    app = subs.add_parser("app",aliases=["gui"],help="Open desktop")
    app.add_argument("--port",type=int,default=DEFAULT_HTTP_PORT)
    subs.add_parser("mcp",help="Run MCP stdio tools")
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 0
    if args.db_path:
        # The explicit CLI path applies to desktop and tray entry points too.
        os.environ["OWLTHREAD_DB_PATH"] = args.db_path
    try:
        if args.command in {"app","gui"}:
            from owlthread.db.database import Database
            from owlthread.gui.app import OwlThreadApp
            with Database(args.db_path) as db:
                app = OwlThreadApp(db=db,port=args.port)
                app.mainloop()
            return 0
        if args.command == "mcp":
            from owlthread.mcp_entry import run_mcp_service
            run_mcp_service(args.db_path)
            return 0
        if args.command=="start" and not args.headless:
            from owlthread.tray import run_tray
            run_tray(args.port,False if args.no_clipboard else None,False if args.no_connectors else None)
            return 0
        from owlthread.db.database import Database
        with Database(args.db_path) as db:
            if args.command=="run":
                return run_wrapped_command(args.cmd[1:] if args.cmd[:1]==["--"] else args.cmd,db,project=args.project)
            if args.command in {"primer","query"}:
                from owlthread.primer.engine import PrimerEngine
                query = " ".join(args.query).strip()
                if args.ui or not query:
                    from owlthread.primer.ui import open_primer_popup
                    open_primer_popup(PrimerEngine(db),query)
                else:
                    result = PrimerEngine(db).generate_primer(query,intent_override=args.intent,search_limit=args.limit,
                                                             include_history=args.include_history,project_id=args.project_id)
                    print(result.primer_text)
                    print("\nCopied to clipboard." if result.copied_to_clipboard else "\nClipboard unavailable; brief printed above.",file=sys.stderr)
            elif args.command in {"done","flush"}:
                from owlthread.extraction.pipeline import ExtractionPipeline
                result = ExtractionPipeline(db).handle_done_signal()
                print(json.dumps(result,ensure_ascii=False,indent=2))
                if result.get("errors"):
                    return 1
            elif args.command=="entries":
                print_entries_table(db,args.limit,args.source,args.include_history)
            elif args.command=="projects":
                print(json.dumps(db.list_projects(),ensure_ascii=False,indent=2))
            elif args.command=="git-capture":
                from owlthread.capture.git_capture import capture_git
                print(json.dumps(capture_git(db,args.repo,args.file,args.enable,args.exclude,args.disable),ensure_ascii=False,indent=2))
            elif args.command=="test-capture":
                pid = db.get_or_create_project(args.project)
                cid = db.insert_capture(args.text,args.source,pid)
                print(f"Saved capture #{cid}. Run owlthread done to extract it.")
            elif args.command=="status":
                print(f"Database: {db.db_path}\nActive memories: {db.count_entries()}\nPending captures: {db.pending_count()}")
                try:
                    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                    with opener.open(f"http://127.0.0.1:{args.port}/health",timeout=2) as response:
                        health = json.load(response)
                    print(json.dumps(health,ensure_ascii=False,indent=2))
                except (OSError,ValueError,urllib.error.URLError):
                    print("Capture service is not running on this port.")
            elif args.command=="start":
                from owlthread.capture.engine import CaptureEngine
                engine = CaptureEngine(db,http_port=args.port,enable_clipboard=False if args.no_clipboard else None,enable_connectors=False if args.no_connectors else None)
                engine.start()
                print(f"OwlThread is running on 127.0.0.1:{args.port}. Press Ctrl+C to stop.")
                try:
                    threading.Event().wait()
                except KeyboardInterrupt:
                    pass
                finally:
                    engine.stop()
        return 0
    except Exception as exc:
        logger.exception("OwlThread failed")
        if args.command in {"app", "gui", "start"} and not getattr(args, "headless", False):
            _show_desktop_error(str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
