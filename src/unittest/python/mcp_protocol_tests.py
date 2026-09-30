#   -*- coding: utf-8 -*-
#   Copyright 2026 Karellen, Inc.
#
#   Licensed under the Apache License, Version 2.0 (the "License");
#   you may not use this file except in compliance with the License.
#   You may obtain a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS,
#   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#   See the License for the specific language governing permissions and
#   limitations under the License.

"""Tests that drive the server through a real MCP client rather than calling tools directly."""

import asyncio
import os
import sys
import threading
import time
import unittest
from unittest.mock import MagicMock

from mcp import Client, StdioServerParameters

import karellen_jdb_mcp.server as server


class _OverlapTracker:
    """Records the peak number of tracked calls in flight at the same time."""

    def __init__(self):
        self._lock = threading.Lock()
        self.active = 0
        self.max_active = 0

    def hold(self, result):
        def side_effect(*args, **kwargs):
            with self._lock:
                self.active += 1
                self.max_active = max(self.max_active, self.active)
            time.sleep(0.2)
            with self._lock:
                self.active -= 1
            return result
        return side_effect


class ToolListingTests(unittest.IsolatedAsyncioTestCase):
    async def test_all_tools_listed_over_protocol(self):
        registered = await server.mcp.list_tools()
        async with Client(server.mcp) as client:
            result = await client.list_tools()
        names = {t.name for t in result.tools}
        self.assertEqual(names, {t.name for t in registered})
        self.assertIn("jdb_connect", names)
        self.assertIn("jdb_where", names)
        for tool in result.tools:
            self.assertEqual(tool.input_schema.get("type"), "object", tool.name)


class StdioTransportTests(unittest.IsolatedAsyncioTestCase):
    async def test_stdio_negotiates_modern_protocol(self):
        params = StdioServerParameters(
            command=sys.executable,
            args=["-c", "from karellen_jdb_mcp.server import main; main()"],
            env={"PYTHONPATH": os.pathsep.join(sys.path)},
        )
        async with Client(params) as client:
            self.assertEqual(client.protocol_version, "2026-07-28")
            self.assertEqual(client.server_info.name, "karellen-jdb-mcp")
            self.assertIn("jdb_connect", client.instructions)
            result = await client.list_tools()
        names = {t.name for t in result.tools}
        self.assertIn("jdb_connect", names)
        self.assertIn("jdb_where", names)


class ConcurrentToolCallTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tracker = _OverlapTracker()
        self.mock_session = MagicMock()
        self.mock_session.is_connected.return_value = True
        self.mock_session.where.side_effect = self.tracker.hold(
            "  [1] com.example.Main.foo (Main.java:42)\n"
            "  [2] com.example.Main.main (Main.java:10)\n"
        )
        self.mock_session.locals_.side_effect = self.tracker.hold(
            "Method arguments:\n"
            "  this = instance of com.example.Main (id=1001)\n"
            "Local variables:\n"
            "  x = 42\n"
            "  y = 100\n"
        )
        self.mock_session.classes.side_effect = self.tracker.hold("com.example.Main\njava.lang.Object\n")
        self.mock_session.classpath.side_effect = self.tracker.hold(
            "base directory: /app\nclasspath: [/app/classes, /app/lib/dep.jar]\n")
        server._jdb_sessions = {5005: self.mock_session}

    def tearDown(self):
        server._jdb_sessions = {}

    async def test_session_tools_never_overlap(self):
        async with Client(server.mcp) as client:
            results = await asyncio.gather(
                client.call_tool("jdb_where", {}),
                client.call_tool("jdb_locals", {}),
                client.call_tool("jdb_classes", {}),
                client.call_tool("jdb_classpath", {}),
            )
        for result in results:
            self.assertFalse(result.is_error, result.content)
        self.assertEqual(self.tracker.max_active, 1)
