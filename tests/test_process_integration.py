"""Real CLI process persistence and MCP stdio protocol integration."""
from __future__ import annotations
import asyncio
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from mcp import ClientSession,StdioServerParameters
from mcp.client.stdio import stdio_client
from owlthread.db.database import Database


class ProcessIntegration(unittest.TestCase):
    def test_cli_capture_survives_process_exit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory)/"cli.db")
            with Database(path) as db:
                db.set_setting("llm_provider","fallback")
            for args in (["test-capture","Decision: Use SQLite WAL locally"],["done"]):
                process = subprocess.run([sys.executable,"-m","owlthread","--db-path",path,*args],
                                         capture_output=True,text=True,encoding="utf-8",timeout=15)
                self.assertEqual(process.returncode,0,process.stderr)
            with Database(path) as db:
                self.assertEqual(db.pending_count(),0)
                self.assertEqual(db.count_entries(),1)

    def test_real_mcp_stdio(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory)/"mcp.db")
            with Database(path) as db:
                db.set_setting("llm_provider","fallback")
            async def exercise() -> None:
                parameters = StdioServerParameters(command=sys.executable,args=["-m","owlthread.mcp_server","--db-path",path])
                async with stdio_client(parameters) as (read,write):
                    async with ClientSession(read,write) as session:
                        await session.initialize()
                        tools = await session.list_tools()
                        self.assertEqual(len(tools.tools),8)
                        integrations = await session.call_tool("list_integrations",{})
                        self.assertFalse(getattr(integrations,"isError",getattr(integrations,"is_error",False)))
                        self.assertIn("cloudflare",integrations.content[0].text)
                        result = await session.call_tool("record_decision",{"summary":"Use SQLite WAL for local memory","quadrant":"technical_architecture"})
                        self.assertFalse(getattr(result,"isError",getattr(result,"is_error",False)))
                        found = await session.call_tool("search_memory",{"query":"SQLite WAL"})
                        self.assertFalse(getattr(found,"isError",getattr(found,"is_error",False)))
                        self.assertIn("SQLite WAL",found.content[0].text)
            asyncio.run(asyncio.wait_for(exercise(),timeout=25))
            with Database(path) as db:
                self.assertEqual(db.count_entries(),1)
