"""CLI entry point and command wrapper for OwlThread."""

import argparse
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import List, Optional

from owlthread.capture.engine import CaptureEngine
from owlthread.config import DEFAULT_HTTP_PORT, SOURCE_CLI
from owlthread.db.database import Database, get_iso_now
from owlthread.extraction.pipeline import ExtractionPipeline
from owlthread.primer.engine import PrimerEngine
from owlthread.primer.ui import open_primer_popup


def run_wrapped_command(cmd_args: List[str], db: Optional[Database] = None) -> int:
    """
    Execute a child process, teeing stdout and stderr in real-time to both the
    console and an in-memory buffer, and writing the captured output to memory_entries.
    """
    if not cmd_args:
        print("Error: No command specified to run.", file=sys.stderr)
        return 1

    if db is None:
        db = Database()

    invoked_cmd = cmd_args[0]
    invoked_name = Path(invoked_cmd).stem
    cmd_str = subprocess.list2cmdline(cmd_args)
    start_timestamp = get_iso_now()

    captured_chunks: List[str] = []
    chunk_lock = threading.Lock()

    def stream_reader(pipe, output_stream, is_err=False):
        """Read from process pipe line-by-line or chunk-by-chunk and tee to stream & buffer."""
        try:
            for line in iter(pipe.readline, ''):
                output_stream.write(line)
                output_stream.flush()
                with chunk_lock:
                    captured_chunks.append(line)
        except Exception:
            pass
        finally:
            pipe.close()

    try:
        process = subprocess.Popen(
            cmd_args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            shell=False
        )
    except FileNotFoundError:
        try:
            process = subprocess.Popen(
                cmd_str,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                shell=True
            )
        except Exception as e:
            print(f"owlthread: failed to execute '{cmd_str}': {e}", file=sys.stderr)
            return 127
    except Exception as e:
        print(f"owlthread: failed to start process '{cmd_str}': {e}", file=sys.stderr)
        return 127

    t_out = threading.Thread(target=stream_reader, args=(process.stdout, sys.stdout, False), daemon=True)
    t_err = threading.Thread(target=stream_reader, args=(process.stderr, sys.stderr, True), daemon=True)
    t_out.start()
    t_err.start()

    exit_code = process.wait()
    t_out.join(timeout=2.0)
    t_err.join(timeout=2.0)

    with chunk_lock:
        full_text = "".join(captured_chunks).strip()

    if full_text:
        try:
            cwd_path = os.getcwd()
            project_name = Path(cwd_path).name
            project_id = db.get_or_create_project(name=project_name, root_path=cwd_path)

            # Ingest into extraction pipeline buffer
            pipeline = ExtractionPipeline(db=db)
            pipeline.ingest_capture(
                raw_text=full_text,
                source_app=SOURCE_CLI,
                project_name=project_name,
                root_path=cwd_path,
                timestamp=start_timestamp
            )

            metadata = {
                "command": invoked_name,
                "executable": invoked_cmd,
                "args": cmd_args[1:],
                "full_command": cmd_str,
                "exit_code": exit_code
            }

            # Also persist raw capture
            entry_id = db.insert_entry(
                raw_text=full_text,
                source_app=SOURCE_CLI,
                project_id=project_id,
                source_metadata=metadata,
                timestamp=start_timestamp,
                quadrant=None,
                summary=f"CLI run: {invoked_name}",
                status="active"
            )
        except Exception as db_err:
            print(f"\n[owlthread: warning - failed to record CLI session: {db_err}]", file=sys.stderr)

    return exit_code


def print_entries_table(
    db: Database,
    limit: int = 20,
    source: Optional[str] = None,
    include_history: bool = False
) -> None:
    """Print formatted view of captured memory entries."""
    entries = db.get_entries(limit=limit, source_app=source, include_history=include_history)
    total = db.count_entries(source_app=source, include_history=include_history)

    mode_label = "All History (Active + Superseded)" if include_history else "Active Memories"
    print(f"\n--- OwlThread Memory Entries ({mode_label} - Showing {len(entries)} of {total} total) ---")
    if not entries:
        print("  No entries recorded yet.")
        return

    for e in entries:
        eid = e["id"]
        src = e["source_app"]
        ts = e["timestamp"][:19].replace("T", " ") if e.get("timestamp") else "                   "
        quad = e.get("quadrant") or "unclassified"
        status = e.get("status") or "active"
        summary = e.get("summary") or ""
        raw = (e.get("raw_text") or "").replace("\n", " ")
        display_text = summary if summary else ((raw[:70] + "...") if len(raw) > 70 else raw)
        status_flag = "[ACT]" if status == "active" else f"[SUP -> #{e.get('superseded_by')}]"
        print(f"[{eid:04d}] | {status_flag:12s} | {src:9s} | {quad[:14]:14s} | {ts} | {display_text}")


def main() -> None:
    """Main CLI entrypoint for `owlthread` command."""
    if sys.platform == "win32":
        try:
            if hasattr(sys.stdout, "reconfigure"):
                sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            if hasattr(sys.stderr, "reconfigure"):
                sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    # Special handling for `owlthread run -- <cmd>`
    raw_args = sys.argv[1:]
    if raw_args and raw_args[0] == "run":
        cmd_to_run = raw_args[1:]
        if cmd_to_run and cmd_to_run[0] == "--":
            cmd_to_run = cmd_to_run[1:]
        
        if not cmd_to_run:
            print("Usage: owlthread run -- <command> [args...]", file=sys.stderr)
            sys.exit(1)

        sys.exit(run_wrapped_command(cmd_to_run))

    parser = argparse.ArgumentParser(
        prog="owlthread",
        description="OwlThread Universal Capture & Context Primer CLI"
    )
    subparsers = parser.add_subparsers(dest="subcommand", help="Available subcommands")

    # `owlthread primer` / `owlthread query`
    primer_parser = subparsers.add_parser(
        "primer",
        help="State your task and generate a context primer"
    )
    primer_parser.add_argument(
        "query", nargs="*", default=[], help="Free-text task description (e.g. 'integrate Stripe billing')"
    )
    primer_parser.add_argument(
        "-i", "--intent", choices=["dev_task", "external_comms", "status_query", "other"], help="Override intent classification"
    )
    primer_parser.add_argument(
        "-n", "--limit", type=int, default=12, help="Number of context memories to include"
    )
    primer_parser.add_argument(
        "--include-history", action="store_true", help="Include superseded historical entries"
    )
    primer_parser.add_argument(
        "--no-copy", action="store_true", help="Disable automatic copy to system clipboard"
    )
    primer_parser.add_argument(
        "--ui", action="store_true", help="Launch visual Query & Primer popup dialog"
    )

    query_parser = subparsers.add_parser(
        "query",
        help="Alias for `owlthread primer`"
    )
    query_parser.add_argument(
        "query", nargs="*", default=[], help="Free-text task description"
    )
    query_parser.add_argument(
        "-i", "--intent", choices=["dev_task", "external_comms", "status_query", "other"], help="Override intent classification"
    )
    query_parser.add_argument(
        "-n", "--limit", type=int, default=12, help="Number of context memories to include"
    )
    query_parser.add_argument(
        "--include-history", action="store_true", help="Include superseded historical entries"
    )
    query_parser.add_argument(
        "--no-copy", action="store_true", help="Disable automatic copy to system clipboard"
    )
    query_parser.add_argument(
        "--ui", action="store_true", help="Launch visual Query & Primer popup dialog"
    )

    # `owlthread done` / `owlthread flush`
    done_parser = subparsers.add_parser(
        "done",
        help="Explicit 'task done' signal: flush rolling capture buffers and extract durable knowledge"
    )
    flush_parser = subparsers.add_parser(
        "flush",
        help="Alias for `owlthread done`"
    )

    # `owlthread projects`
    subparsers.add_parser("projects", help="List all registered project namespaces")

    # `owlthread run`
    run_parser = subparsers.add_parser(
        "run",
        help="Run a command through OwlThread CLI capture wrapper"
    )
    run_parser.add_argument("command", nargs=argparse.REMAINDER, help="Command to execute")

    # `owlthread start`
    start_parser = subparsers.add_parser("start", help="Start the capture engine daemon")
    start_parser.add_argument(
        "--port", type=int, default=DEFAULT_HTTP_PORT, help="Port for local HTTP listener"
    )
    start_parser.add_argument(
        "--headless", action="store_true", help="Run in headless terminal mode without system tray"
    )
    start_parser.add_argument(
        "--no-clipboard", action="store_true", help="Disable clipboard watcher"
    )
    start_parser.add_argument(
        "--no-connectors", action="store_true", help="Disable file connectors"
    )

    # `owlthread app` / `owlthread gui`
    app_parser = subparsers.add_parser(
        "app",
        help="Launch the OwlThread Windows Desktop GUI Application"
    )
    app_parser.add_argument(
        "--port", type=int, default=DEFAULT_HTTP_PORT, help="Port for local HTTP listener"
    )
    gui_parser = subparsers.add_parser(
        "gui",
        help="Alias for `owlthread app`"
    )
    gui_parser.add_argument(
        "--port", type=int, default=DEFAULT_HTTP_PORT, help="Port for local HTTP listener"
    )

    # `owlthread entries`
    entries_parser = subparsers.add_parser("entries", help="View recent captured entries")
    entries_parser.add_argument("-n", "--limit", type=int, default=20, help="Number of entries to show")
    entries_parser.add_argument("-s", "--source", type=str, default=None, help="Filter by source_app")
    entries_parser.add_argument("--include-history", action="store_true", help="Show superseded records as well")

    # `owlthread status`
    subparsers.add_parser("status", help="Check status of OwlThread and capture surfaces")

    # `owlthread test-capture`
    test_parser = subparsers.add_parser("test-capture", help="Manually insert a test capture")
    test_parser.add_argument("text", help="Text to capture")
    test_parser.add_argument("--source", default="test", help="Source app tag")
    test_parser.add_argument("--project", default="General", help="Project name")

    # `owlthread mcp`
    mcp_parser = subparsers.add_parser("mcp", help="Launch native Model Context Protocol (MCP) server for Cursor/Claude")
    mcp_parser.add_argument("--transport", default="stdio", choices=["stdio", "sse"], help="MCP transport (stdio or sse)")

    args = parser.parse_args()

    if not args.subcommand:
        parser.print_help()
        sys.exit(0)

    db = Database()

    if args.subcommand in ("done", "flush"):
        pipeline = ExtractionPipeline(db=db)
        res = pipeline.handle_done_signal()
        print(f"\n==================== OwlThread Capture Flush ====================")
        print(f"Batches Flushed: {res['batches_flushed']} | Extracted Items: {res['total_extracted']} | Superseded: {res['total_superseded']}")
        if res["extracted_entries"]:
            print("\nExtracted Knowledge Items:")
            for item in res["extracted_entries"]:
                sup_note = f" (Superseded #{item['superseded_id']})" if item.get("superseded_id") else ""
                print(f"  - [#{item['entry_id']}] [{item['quadrant']}] {item['summary']}{sup_note}")
        else:
            print("Capture buffers were empty or captured text contained no qualifying durable knowledge.")
        print(f"==================================================================\n")

    elif args.subcommand == "projects":
        projects = db.list_projects()
        print(f"\n--- OwlThread Projects ({len(projects)} registered) ---")
        for p in projects:
            root = p.get("root_path") or "(general / no path)"
            print(f"[{p['id']:03d}] {p['name']:20s} | Path: {root}")
        print()

    elif args.subcommand in ("primer", "query"):
        query_text = " ".join(args.query).strip() if isinstance(args.query, list) else str(args.query).strip()

        if args.ui or not query_text:
            open_primer_popup(engine=PrimerEngine(db=db), initial_query=query_text)
            return

        engine = PrimerEngine(db=db)
        result = engine.generate_primer(
            user_request=query_text,
            intent_override=args.intent,
            search_limit=args.limit,
            auto_copy=not args.no_copy,
            include_history=getattr(args, "include_history", False),
        )

        copy_notice = " [Copied to clipboard]" if result.copied_to_clipboard else ""
        try:
            print(f"\n==================== OwlThread Context Primer ====================")
            print(f"Query: \"{result.query}\" | Intent: {result.intent} | Memories: {len(result.matched_entries)}{copy_notice}")
            print(f"Elapsed: {result.elapsed_sec:.2f}s")
            print(f"==================================================================\n")
            print(result.primer_text)
            print(f"\n==================================================================")
        except UnicodeEncodeError:
            safe_text = result.primer_text.encode("ascii", errors="replace").decode("ascii")
            print(safe_text)

    elif args.subcommand in ("app", "gui"):
        from owlthread.gui import run_app
        run_app(port=args.port)
        return

    elif args.subcommand == "run":
        cmd_list = args.command
        if cmd_list and cmd_list[0] == "--":
            cmd_list = cmd_list[1:]
        sys.exit(run_wrapped_command(cmd_list, db=db))

    elif args.subcommand == "entries":
        print_entries_table(db, limit=args.limit, source=args.source, include_history=args.include_history)

    elif args.subcommand == "status":
        active_cnt = db.count_entries(include_history=False)
        total_cnt = db.count_entries(include_history=True)
        projects = db.list_projects()
        print(f"OwlThread Status:")
        print(f"  Database Path: {db.db_path}")
        print(f"  Active Memories: {active_cnt} (Total including history: {total_cnt})")
        print(f"  Projects ({len(projects)}):")
        for p in projects:
            p_cnt = db.count_entries(project_id=p["id"], include_history=False)
            print(f"    - [{p['id']}] {p['name']}: {p_cnt} active memories")

    elif args.subcommand == "test-capture":
        project_id = db.get_or_create_project(name=args.project)
        eid = db.insert_entry(raw_text=args.text, source_app=args.source, project_id=project_id, quadrant=None)
        print(f"Captured test entry #{eid} (project: {args.project} #{project_id}, source: {args.source})")

    elif args.subcommand == "start":
        if args.headless:
            print(f"Starting OwlThread Capture Engine (Headless mode on port {args.port})...")
            engine = CaptureEngine(
                db=db,
                http_port=args.port,
                enable_clipboard=not args.no_clipboard,
                enable_connectors=not args.no_connectors,
                enable_http=True
            )
            engine.start()
            print("Capture Engine active. Press Ctrl+C to terminate.")
            try:
                while True:
                    time.sleep(1.0)
            except KeyboardInterrupt:
                print("\nStopping Capture Engine...")
                engine.stop()
                print("Capture Engine stopped.")
        else:
            from owlthread.tray import run_tray
            run_tray(
                port=args.port,
                enable_clipboard=not args.no_clipboard,
                enable_connectors=not args.no_connectors
            )

    elif args.subcommand == "mcp":
        from owlthread.mcp_entry import run_mcp_service
        run_mcp_service(db_path=str(db.db_path), transport=args.transport)
        return


if __name__ == "__main__":
    main()
