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

import unittest
from unittest.mock import patch, MagicMock

from mcp.server.fastmcp.exceptions import ToolError

from karellen_jdb_mcp.jdb_session import JdbSessionError
from karellen_jdb_mcp.process_manager import ProcessManagerError
from karellen_jdb_mcp.types import (
    BreakpointInfo, StopEvent,
    ClassInfo, LockInfo, ThreadLockInfo,
    MonitorInfo, EvalResult, ConnectStatus, StringResult,
    VersionInfo, ExceptionBreakInfo, WatchpointInfo,
    LaunchResult, ProcessStatus, SessionInfo,
)
import karellen_jdb_mcp.server as server


class TagErrorsDecoratorTests(unittest.TestCase):
    def test_jdb_error_tagged(self):
        @server._tag_errors
        def fail():
            raise JdbSessionError("bad jdb")
        with self.assertRaises(ToolError) as ctx:
            fail()
        self.assertTrue(str(ctx.exception).startswith("jdb:"))

    def test_unexpected_error_tagged_with_type_and_traceback(self):
        @server._tag_errors
        def fail():
            raise ValueError("bad value")
        with self.assertRaises(ToolError) as ctx:
            fail()
        msg = str(ctx.exception)
        self.assertTrue(msg.startswith("internal:"))
        self.assertIn("ValueError", msg)
        self.assertIn("bad value", msg)
        self.assertIn("in fail", msg)

    def test_unexpected_key_error_tagged(self):
        @server._tag_errors
        def fail():
            raise KeyError("missing")
        with self.assertRaises(ToolError) as ctx:
            fail()
        msg = str(ctx.exception)
        self.assertIn("internal:", msg)
        self.assertIn("KeyError", msg)

    def test_tool_error_passes_through(self):
        @server._tag_errors
        def fail():
            raise ToolError("already tagged")
        with self.assertRaises(ToolError) as ctx:
            fail()
        self.assertEqual(str(ctx.exception), "already tagged")

    def test_no_error_passes_through(self):
        @server._tag_errors
        def ok():
            return "fine"
        self.assertEqual(ok(), "fine")


class RequireSessionTests(unittest.TestCase):
    def setUp(self):
        server._jdb_sessions = {}

    def test_no_session_raises(self):
        with self.assertRaises(JdbSessionError):
            server._require_session()

    def test_disconnected_session_raises(self):
        mock_session = MagicMock()
        mock_session.is_connected.return_value = False
        server._jdb_sessions = {5005: mock_session}
        with self.assertRaises(JdbSessionError):
            server._require_session()

    def test_connected_session_returns(self):
        mock_session = MagicMock()
        mock_session.is_connected.return_value = True
        server._jdb_sessions = {5005: mock_session}
        self.assertIs(server._require_session(), mock_session)

    def test_single_session_auto_resolves(self):
        mock_session = MagicMock()
        mock_session.is_connected.return_value = True
        server._jdb_sessions = {9876: mock_session}
        self.assertIs(server._require_session(), mock_session)

    def test_multiple_sessions_requires_port(self):
        s1 = MagicMock()
        s1.is_connected.return_value = True
        s2 = MagicMock()
        s2.is_connected.return_value = True
        server._jdb_sessions = {5005: s1, 5006: s2}
        with self.assertRaises(JdbSessionError) as ctx:
            server._require_session()
        self.assertIn("Multiple", str(ctx.exception))
        self.assertIn("5005", str(ctx.exception))
        self.assertIn("5006", str(ctx.exception))

    def test_multiple_sessions_with_port(self):
        s1 = MagicMock()
        s1.is_connected.return_value = True
        s2 = MagicMock()
        s2.is_connected.return_value = True
        server._jdb_sessions = {5005: s1, 5006: s2}
        self.assertIs(server._require_session(5006), s2)

    def test_port_not_found_raises(self):
        s1 = MagicMock()
        s1.is_connected.return_value = True
        server._jdb_sessions = {5005: s1}
        with self.assertRaises(JdbSessionError) as ctx:
            server._require_session(9999)
        self.assertIn("9999", str(ctx.exception))

    def tearDown(self):
        server._jdb_sessions = {}


class ConnectToolTests(unittest.TestCase):
    def setUp(self):
        server._jdb_sessions = {}

    @patch("karellen_jdb_mcp.server.JdbSession")
    def test_connect_success(self, mock_cls):
        mock_session = MagicMock()
        vi = VersionInfo(
            jdb_version_string="jdb 21.0.4",
            jdk_major_version=21,
            has_stop_modifiers=True,
            has_repeat_command=True,
            has_threadgroup_reset=True,
            has_track_all_threads=True,
        )
        mock_session.version_info = vi
        mock_cls.return_value = mock_session

        result = server.jdb_connect(host="myhost", port=8000)
        self.assertIsInstance(result, ConnectStatus)
        self.assertEqual(result.host, "myhost")
        self.assertEqual(result.port, 8000)
        self.assertEqual(result.jdk_major_version, 21)
        mock_session.connect.assert_called_once_with(
            "jdb", "myhost", 8000,
            sourcepath=None, classpath=None, trackallthreads=False,
            wait_timeout=0)

    def test_connect_already_active(self):
        server._jdb_sessions = {5005: MagicMock()}
        with self.assertRaises(ToolError) as ctx:
            server.jdb_connect(port=5005)
        self.assertIn("already active", str(ctx.exception))

    @patch("karellen_jdb_mcp.server.JdbSession")
    def test_connect_failure_cleans_up(self, mock_cls):
        mock_session = MagicMock()
        mock_session.connect.side_effect = JdbSessionError("connection refused")
        mock_cls.return_value = mock_session

        with self.assertRaises(ToolError):
            server.jdb_connect(port=5005)
        mock_session.close.assert_called_once()

    def tearDown(self):
        server._jdb_sessions = {}


class DisconnectToolTests(unittest.TestCase):
    def setUp(self):
        server._jdb_sessions = {}

    def test_disconnect_no_session(self):
        result = server.jdb_disconnect()
        self.assertIsInstance(result, StringResult)
        self.assertIn("No active", result.result)

    def test_disconnect_active_session(self):
        server._jdb_sessions = {5005: MagicMock()}
        result = server.jdb_disconnect()
        self.assertIsInstance(result, StringResult)
        self.assertIn("closed", result.result)
        self.assertEqual(len(server._jdb_sessions), 0)

    def tearDown(self):
        server._jdb_sessions = {}


class SessionListToolTests(unittest.TestCase):
    def setUp(self):
        server._jdb_sessions = {}

    def test_empty(self):
        result = server.jdb_session_list()
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 0)

    def test_single_session(self):
        mock_session = MagicMock()
        mock_session.is_connected.return_value = True
        mock_session.version_info = VersionInfo(
            jdb_version_string="jdb 21",
            jdk_major_version=21,
            has_stop_modifiers=True,
            has_repeat_command=True,
            has_threadgroup_reset=True,
            has_track_all_threads=True,
        )
        server._jdb_sessions = {5005: mock_session}
        result = server.jdb_session_list()
        self.assertEqual(len(result), 1)
        self.assertIsInstance(result[0], SessionInfo)
        self.assertEqual(result[0].port, 5005)
        self.assertTrue(result[0].connected)
        self.assertEqual(result[0].jdk_major_version, 21)

    def test_multiple_sessions(self):
        s1 = MagicMock()
        s1.is_connected.return_value = True
        s1.version_info = MagicMock(jdb_version_string="jdb 21", jdk_major_version=21)
        s2 = MagicMock()
        s2.is_connected.return_value = True
        s2.version_info = MagicMock(jdb_version_string="jdb 17", jdk_major_version=17)
        server._jdb_sessions = {5005: s1, 5006: s2}
        result = server.jdb_session_list()
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0].port, 5005)
        self.assertEqual(result[1].port, 5006)

    def tearDown(self):
        server._jdb_sessions = {}


class ExecutionToolTests(unittest.TestCase):
    def setUp(self):
        self.mock_session = MagicMock()
        self.mock_session.is_connected.return_value = True
        server._jdb_sessions = {5005: self.mock_session}

    def test_run(self):
        self.mock_session.run.return_value = (
            'Breakpoint hit: "thread=main", com.example.Main.main(), line=10 bci=0\n')
        result = server.jdb_run()
        self.assertIsInstance(result, StopEvent)

    def test_cont(self):
        self.mock_session.cont.return_value = (
            'Breakpoint hit: "thread=main", com.example.Main.foo(), line=20 bci=0\n')
        result = server.jdb_cont()
        self.assertIsInstance(result, StopEvent)
        self.assertEqual(result.reason, "breakpoint_hit")

    def test_step(self):
        self.mock_session.step.return_value = (
            'Step completed: "thread=main", com.example.Main.foo(), line=21 bci=5\n')
        result = server.jdb_step()
        self.assertIsInstance(result, StopEvent)
        self.assertEqual(result.reason, "step_completed")

    def test_next(self):
        self.mock_session.next_.return_value = (
            'Step completed: "thread=main", com.example.Main.foo(), line=22 bci=8\n')
        result = server.jdb_next()
        self.assertIsInstance(result, StopEvent)

    def test_step_up(self):
        self.mock_session.step_up.return_value = (
            'Step completed: "thread=main", com.example.Main.main(), line=11 bci=3\n')
        result = server.jdb_step_up()
        self.assertIsInstance(result, StopEvent)

    def test_cont_resumed(self):
        self.mock_session.cont.return_value = ""
        result = server.jdb_cont()
        self.assertIsInstance(result, StopEvent)
        self.assertEqual(result.reason, "resumed")

    def test_cont_nothing_suspended(self):
        self.mock_session.cont.return_value = "Nothing suspended."
        result = server.jdb_cont()
        self.assertIsInstance(result, StopEvent)
        self.assertEqual(result.reason, "completed")
        self.assertIn("Nothing suspended", result.location)

    def test_run_resumed(self):
        self.mock_session.run.return_value = ""
        result = server.jdb_run()
        self.assertIsInstance(result, StopEvent)
        self.assertEqual(result.reason, "resumed")

    def test_step_resumed(self):
        self.mock_session.step.return_value = ""
        result = server.jdb_step()
        self.assertIsInstance(result, StopEvent)
        self.assertEqual(result.reason, "resumed")

    def test_wait_for_event_breakpoint(self):
        self.mock_session.wait_for_event.return_value = (
            'Breakpoint hit: "thread=main", com.example.Main.foo(), line=42 bci=0\n')
        result = server.jdb_wait_for_event()
        self.assertIsInstance(result, StopEvent)
        self.assertEqual(result.reason, "breakpoint_hit")

    def test_wait_for_event_timeout(self):
        self.mock_session.wait_for_event.return_value = ""
        result = server.jdb_wait_for_event(timeout=5)
        self.assertIsInstance(result, StopEvent)
        self.assertEqual(result.reason, "resumed")

    def test_wait_for_event_custom_timeout(self):
        self.mock_session.wait_for_event.return_value = ""
        server.jdb_wait_for_event(timeout=300)
        self.mock_session.wait_for_event.assert_called_once_with(timeout=300)

    def test_cont_error(self):
        self.mock_session.cont.return_value = "** Not at a breakpoint\n"
        with self.assertRaises(ToolError):
            server.jdb_cont()

    def test_cont_jdb_error(self):
        self.mock_session.cont.side_effect = JdbSessionError("disconnected")
        with self.assertRaises(ToolError) as ctx:
            server.jdb_cont()
        self.assertIn("jdb:", str(ctx.exception))

    def tearDown(self):
        server._jdb_sessions = {}


class BreakpointToolTests(unittest.TestCase):
    def setUp(self):
        self.mock_session = MagicMock()
        self.mock_session.is_connected.return_value = True
        self.mock_session.version_info = VersionInfo(
            jdb_version_string="jdb 21",
            jdk_major_version=21,
            has_stop_modifiers=True,
            has_repeat_command=True,
            has_threadgroup_reset=True,
            has_track_all_threads=True,
        )
        server._jdb_sessions = {5005: self.mock_session}

    def test_set_breakpoint(self):
        self.mock_session.breakpoint_set.return_value = "Set breakpoint com.example.Main:42\n"
        result = server.jdb_breakpoint_set("com.example.Main:42")
        self.assertIsInstance(result, BreakpointInfo)
        self.assertEqual(result.line, 42)

    def test_set_breakpoint_error(self):
        self.mock_session.breakpoint_set.return_value = "** Invalid location\n"
        with self.assertRaises(ToolError):
            server.jdb_breakpoint_set("nonexistent")

    def test_set_breakpoint_thread_id_jdk8_fails(self):
        self.mock_session.version_info = VersionInfo(
            jdb_version_string="jdb 1.8",
            jdk_major_version=8,
            has_stop_modifiers=False,
            has_repeat_command=False,
            has_threadgroup_reset=False,
            has_track_all_threads=False,
        )
        with self.assertRaises(ToolError) as ctx:
            server.jdb_breakpoint_set("com.Main:10", thread_id="0x1a8")
        self.assertIn("JDK 13+", str(ctx.exception))

    def test_list_breakpoints(self):
        self.mock_session.breakpoint_list.return_value = (
            "Breakpoints set:\n"
            "  breakpoint com.example.Main:42\n"
            "  breakpoint com.example.Main.method\n"
        )
        result = server.jdb_breakpoint_list()
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 2)

    def test_clear_breakpoint(self):
        self.mock_session.breakpoint_clear.return_value = "Removed: breakpoint com.example.Main:42\n"
        result = server.jdb_breakpoint_clear("com.example.Main:42")
        self.assertIsInstance(result, StringResult)

    def tearDown(self):
        server._jdb_sessions = {}


class CatchToolTests(unittest.TestCase):
    def setUp(self):
        self.mock_session = MagicMock()
        self.mock_session.is_connected.return_value = True
        server._jdb_sessions = {5005: self.mock_session}

    def test_catch_success(self):
        self.mock_session.catch.return_value = "Set all java.lang.NullPointerException\n"
        result = server.jdb_catch("java.lang.NullPointerException")
        self.assertIsInstance(result, ExceptionBreakInfo)
        self.assertEqual(result.class_pattern, "java.lang.NullPointerException")

    def test_catch_error(self):
        self.mock_session.catch.return_value = "** Unknown exception class\n"
        with self.assertRaises(ToolError):
            server.jdb_catch("nonexistent.Class")

    def tearDown(self):
        server._jdb_sessions = {}


class WatchToolTests(unittest.TestCase):
    def setUp(self):
        self.mock_session = MagicMock()
        self.mock_session.is_connected.return_value = True
        server._jdb_sessions = {5005: self.mock_session}

    def test_watch_success(self):
        self.mock_session.watch.return_value = "Set watch com.example.Main.counter\n"
        result = server.jdb_watch("com.example.Main.counter")
        self.assertIsInstance(result, WatchpointInfo)
        self.assertEqual(result.field_name, "counter")

    def test_watch_error(self):
        self.mock_session.watch.return_value = "** Field not found\n"
        with self.assertRaises(ToolError):
            server.jdb_watch("com.example.Main.nonexistent")

    def tearDown(self):
        server._jdb_sessions = {}


class InspectionToolTests(unittest.TestCase):
    def setUp(self):
        self.mock_session = MagicMock()
        self.mock_session.is_connected.return_value = True
        server._jdb_sessions = {5005: self.mock_session}

    def test_where(self):
        self.mock_session.where.return_value = (
            "  [1] com.example.Main.foo (Main.java:42)\n"
            "  [2] com.example.Main.main (Main.java:10)\n"
        )
        result = server.jdb_where()
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0].class_name, "com.example.Main")

    def test_locals(self):
        self.mock_session.locals_.return_value = (
            "Method arguments:\n"
            "  this = instance of com.example.Main (id=1001)\n"
            "Local variables:\n"
            "  x = 42\n"
            "  y = 100\n"
        )
        result = server.jdb_locals()
        self.assertIsInstance(result, list)
        self.assertGreaterEqual(len(result), 2)

    def test_print(self):
        self.mock_session.print_.return_value = "  myVar = 42\n"
        result = server.jdb_print("myVar")
        self.assertIsInstance(result, EvalResult)
        self.assertEqual(result.expression, "myVar")
        self.assertEqual(result.value, "42")

    def test_dump(self):
        self.mock_session.dump.return_value = "  obj = {\n    x: 1\n    y: 2\n  }\n"
        result = server.jdb_dump("obj")
        self.assertIsInstance(result, EvalResult)
        self.assertIn("x: 1", result.value)

    def test_set(self):
        self.mock_session.set_.return_value = "x = 42\n"
        result = server.jdb_set("x", "42")
        self.assertIsInstance(result, StringResult)

    def test_classes(self):
        self.mock_session.classes.return_value = "com.example.Main\njava.lang.Object\n"
        result = server.jdb_classes()
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 2)

    def test_class_info(self):
        self.mock_session.class_info.return_value = (
            "Class: com.example.Main extends java.lang.Object\n"
        )
        result = server.jdb_class_info("com.example.Main")
        self.assertIsInstance(result, ClassInfo)
        self.assertEqual(result.superclass, "java.lang.Object")

    def test_methods(self):
        self.mock_session.methods.return_value = (
            "  void main(java.lang.String[])\n  int getValue()\n"
        )
        result = server.jdb_methods("com.example.Main")
        self.assertIsInstance(result, list)
        self.assertGreaterEqual(len(result), 2)

    def test_fields(self):
        self.mock_session.fields.return_value = (
            "  int x\n  static java.lang.String name\n"
        )
        result = server.jdb_fields("com.example.Main")
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 2)

    def tearDown(self):
        server._jdb_sessions = {}


class ThreadToolTests(unittest.TestCase):
    def setUp(self):
        self.mock_session = MagicMock()
        self.mock_session.is_connected.return_value = True
        server._jdb_sessions = {5005: self.mock_session}

    def test_threads(self):
        self.mock_session.threads.return_value = (
            "Group main:\n"
            "  (java.lang.Thread)0x1a8 main running\n"
            "  (java.lang.Thread)0x1a9 worker sleeping\n"
        )
        result = server.jdb_threads()
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].name, "main")
        self.assertEqual(len(result[0].threads), 2)

    def test_thread_set(self):
        self.mock_session.thread.return_value = "Thread set to 0x1a8\n"
        result = server.jdb_thread("0x1a8")
        self.assertIsInstance(result, StringResult)

    def test_suspend(self):
        self.mock_session.suspend.return_value = "All threads suspended.\n"
        result = server.jdb_suspend()
        self.assertIsInstance(result, StringResult)

    def test_resume(self):
        self.mock_session.resume.return_value = "All threads resumed.\n"
        result = server.jdb_resume()
        self.assertIsInstance(result, StringResult)

    def tearDown(self):
        server._jdb_sessions = {}


class ConcurrencyToolTests(unittest.TestCase):
    def setUp(self):
        self.mock_session = MagicMock()
        self.mock_session.is_connected.return_value = True
        server._jdb_sessions = {5005: self.mock_session}

    def test_lock(self):
        self.mock_session.lock.return_value = (
            "Monitor information for obj@0x100:\n"
            "  Owner: main\n"
            "  Waiting thread: Thread-1\n"
            "  Waiting thread: Thread-2\n"
        )
        result = server.jdb_lock("obj")
        self.assertIsInstance(result, LockInfo)
        self.assertEqual(result.owner_thread, "main")
        self.assertEqual(len(result.waiting_threads), 2)

    def test_threadlocks(self):
        self.mock_session.threadlocks.return_value = (
            "Monitor information for thread main:\n"
            "  Owned monitor: instance of java.lang.Object(id=1002)\n"
            "  Owned monitor: instance of java.lang.Object(id=1003)\n"
        )
        result = server.jdb_threadlocks("main")
        self.assertIsInstance(result, ThreadLockInfo)
        self.assertEqual(len(result.owned_monitors), 2)

    def tearDown(self):
        server._jdb_sessions = {}


class MonitorToolTests(unittest.TestCase):
    def setUp(self):
        self.mock_session = MagicMock()
        self.mock_session.is_connected.return_value = True
        server._jdb_sessions = {5005: self.mock_session}

    def test_monitor_set(self):
        self.mock_session.monitor.return_value = "Set monitor 1: locals\n"
        result = server.jdb_monitor("locals")
        self.assertIsInstance(result, MonitorInfo)
        self.assertEqual(result.number, 1)
        self.assertEqual(result.command, "locals")

    def test_monitor_list(self):
        self.mock_session.monitor_list.return_value = "  1: locals\n  2: where\n"
        result = server.jdb_monitor_list()
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 2)

    def test_unmonitor(self):
        self.mock_session.unmonitor.return_value = "Unset monitor 1\n"
        result = server.jdb_unmonitor(1)
        self.assertIsInstance(result, StringResult)

    def tearDown(self):
        server._jdb_sessions = {}


class LaunchToolTests(unittest.TestCase):
    def setUp(self):
        self._orig_manager = server._process_manager
        server._process_manager = MagicMock()

    def test_launch(self):
        mock_managed = MagicMock()
        mock_managed.port = 9876
        mock_managed.pid = 5555
        mock_managed.command = ["java", "-agentlib:jdwp=address=*:9876", "Main"]
        server._process_manager.launch.return_value = mock_managed

        result = server.jdb_launch(["java", "-agentlib:jdwp=address=*:${JDB_PORT}", "Main"])
        self.assertIsInstance(result, LaunchResult)
        self.assertEqual(result.port, 9876)
        self.assertEqual(result.pid, 5555)
        server._process_manager.launch.assert_called_once()

    def test_launch_list(self):
        m1 = MagicMock()
        m1.port = 9001
        m1.pid = 100
        m1.command = ["java", "App1"]
        m1.is_running.return_value = True
        m1.exit_code.return_value = None
        m2 = MagicMock()
        m2.port = 9002
        m2.pid = 101
        m2.command = ["java", "App2"]
        m2.is_running.return_value = False
        m2.exit_code.return_value = 1
        server._process_manager.list_all.return_value = [m1, m2]

        result = server.jdb_launch_list()
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 2)
        self.assertTrue(result[0].running)
        self.assertFalse(result[1].running)
        self.assertEqual(result[1].exit_code, 1)

    def test_launch_status(self):
        mock_managed = MagicMock()
        mock_managed.port = 9001
        mock_managed.pid = 100
        mock_managed.command = ["java", "Main"]
        mock_managed.is_running.return_value = True
        mock_managed.exit_code.return_value = None
        server._process_manager.get.return_value = mock_managed

        result = server.jdb_launch_status(9001)
        self.assertIsInstance(result, ProcessStatus)
        self.assertEqual(result.port, 9001)
        self.assertTrue(result.running)

    def test_launch_status_not_found(self):
        server._process_manager.get.return_value = None
        with self.assertRaises(ToolError) as ctx:
            server.jdb_launch_status(9999)
        self.assertIn("process:", str(ctx.exception))

    def test_launch_stop(self):
        mock_managed = MagicMock()
        mock_managed.pid = 100
        server._process_manager.stop.return_value = mock_managed

        result = server.jdb_launch_stop(9001)
        self.assertIsInstance(result, StringResult)
        self.assertIn("Stopped", result.result)
        server._process_manager.stop.assert_called_once_with(9001)

    def test_launch_stop_not_found(self):
        server._process_manager.stop.side_effect = ProcessManagerError("No managed process on port 9999")
        with self.assertRaises(ToolError) as ctx:
            server.jdb_launch_stop(9999)
        self.assertIn("process:", str(ctx.exception))

    def tearDown(self):
        server._process_manager = self._orig_manager


class NoSessionToolTests(unittest.TestCase):
    """Verify tools raise ToolError when no session is active."""
    def setUp(self):
        server._jdb_sessions = {}

    def test_breakpoint_set_no_session(self):
        with self.assertRaises(ToolError) as ctx:
            server.jdb_breakpoint_set("com.example.Main:42")
        self.assertIn("jdb:", str(ctx.exception))

    def test_cont_no_session(self):
        with self.assertRaises(ToolError):
            server.jdb_cont()

    def test_where_no_session(self):
        with self.assertRaises(ToolError):
            server.jdb_where()

    def test_print_no_session(self):
        with self.assertRaises(ToolError):
            server.jdb_print("x")

    def test_threads_no_session(self):
        with self.assertRaises(ToolError):
            server.jdb_threads()

    def test_locals_no_session(self):
        with self.assertRaises(ToolError):
            server.jdb_locals()
