"""Exercise the built Windows executable with an isolated, offline database."""
from __future__ import annotations
import asyncio
import json
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from mcp import ClientSession,StdioServerParameters
from mcp.client.stdio import stdio_client
from owlthread.db.database import Database


async def mcp_check(exe: Path, database: Path) -> None:
    parameters = StdioServerParameters(command=str(exe),args=["--db-path",str(database),"mcp"])
    async with stdio_client(parameters) as (read,write):
        async with ClientSession(read,write) as session:
            await session.initialize()
            tools = {tool.name for tool in (await session.list_tools()).tools}
            assert tools == {"search_memory","record_decision","get_quadrant","generate_primer",
                "get_memory_stats","list_integrations","get_integration_status","configure_integration",
                "test_integration_connection","sync_integration_context"},tools
            available = await session.call_tool("get_integration_status",{"integration_id":"cloudflare"})
            assert not available.isError,available
            snapshot = json.loads(available.content[0].text)
            assert snapshot["builtin"] and not snapshot["connected"],snapshot
            result = await session.call_tool("record_decision",{
                "summary":"Keep local SQLite backups before schema upgrades",
                "quadrant":"settled_decisions"})
            assert not result.isError,result
            result = await session.call_tool("search_memory",{"query":"SQLite backups"})
            assert not result.isError and "backups" in result.content[0].text,result
            result = await session.call_tool("get_memory_stats",{})
            assert not result.isError,result


def main() -> None:
    root=Path(__file__).resolve().parent.parent
    version=tomllib.loads((root/'pyproject.toml').read_text())['project']['version']
    exe = Path(sys.argv[1]).resolve() if len(sys.argv)>1 else root/'artifacts/dist'/version/'OwlThread/owlthread-cli.exe'
    assert exe.is_file(),exe
    with tempfile.TemporaryDirectory(prefix="owlthread-package-") as directory:
        database = Path(directory)/"smoke.db"
        with Database(str(database)) as db:
            db.set_setting("llm_provider","fallback")
        def command(*args: str) -> subprocess.CompletedProcess[str]:
            result = subprocess.run([str(exe),"--db-path",str(database),*args],capture_output=True,
                text=True,encoding="utf-8",timeout=30)
            assert result.returncode==0,(args,result.stdout,result.stderr)
            return result
        command("test-capture","Decision: Use SQLite WAL for durable local memory")
        flushed = json.loads(command("done").stdout)
        assert flushed["total_extracted"]==1,flushed
        primer = command("primer","fix SQLite locking")
        assert "SQLite WAL" in primer.stdout,primer.stdout
        assert "Copied to clipboard" in primer.stderr,primer.stderr
        assert "Active memories: 1" in command("status").stdout
        asyncio.run(asyncio.wait_for(mcp_check(exe,database),timeout=45))
        with Database(str(database)) as db:
            assert db.count_entries()==2
            assert db.pending_count()==0
    print("PASS: packaged CLI capture, extraction, primer, native clipboard, status and MCP stdio.")


if __name__=="__main__":
    main()
