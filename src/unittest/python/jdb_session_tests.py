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

import queue
import time
import unittest
from unittest.mock import MagicMock, patch

from karellen_jdb_mcp.jdb_session import JdbSession, JdbSessionError, JdbTimeoutError, PROMPT_RE


class PromptRegexTests(unittest.TestCase):
    def test_initial_prompt(self):
        self.assertIsNotNone(PROMPT_RE.match("> "))

    def test_main_thread_prompt(self):
        self.assertIsNotNone(PROMPT_RE.match("main[1] "))

    def test_thread_with_depth(self):
        self.assertIsNotNone(PROMPT_RE.match("Thread-0[2] "))

    def test_deep_suspension(self):
        self.assertIsNotNone(PROMPT_RE.match("main[5] "))

    def test_non_prompt(self):
        self.assertIsNone(PROMPT_RE.match("some output"))

    def test_partial_prompt_no_space(self):
        self.assertIsNone(PROMPT_RE.match("main[1]"))

    def test_hyphenated_thread_name(self):
        self.assertIsNotNone(PROMPT_RE.match("pool-1-thread-3[1] "))

    def test_virtual_thread_name(self):
        self.assertIsNotNone(PROMPT_RE.match(
            "VirtualThread[#42]/runnable@ForkJoinPool-1-worker-1[1] "))

    def test_thread_name_with_hash_slash_at(self):
        self.assertIsNotNone(PROMPT_RE.match("pool#1/worker@2[3] "))

    def test_bare_greater_than_not_matched(self):
        self.assertIsNone(PROMPT_RE.match(">"))

    def test_output_with_greater_than_not_matched(self):
        self.assertIsNone(PROMPT_RE.match("x > 5"))


class JdbSessionNotConnectedTests(unittest.TestCase):
    def test_not_connected_initially(self):
        session = JdbSession()
        self.assertFalse(session.is_connected())

    def test_send_command_raises_when_not_connected(self):
        session = JdbSession()
        with self.assertRaises(JdbSessionError) as ctx:
            session.send_command("cont")
        self.assertIn("Not connected", str(ctx.exception))

    def test_version_info_none_initially(self):
        session = JdbSession()
        self.assertIsNone(session.version_info)


class SendCommandTests(unittest.TestCase):
    """Test send_command end-to-end with the line queue."""

    def setUp(self):
        self.session = JdbSession()
        self.session._connected = True
        self.session._process = MagicMock()
        self.session._process.poll.return_value = None
        self.session._process.stdin = MagicMock()
        self.session._line_queue = queue.Queue()

    def _enqueue(self, *chunks):
        for chunk in chunks:
            self.session._line_queue.put(chunk)

    def test_sends_command_and_returns_output(self):
        self._enqueue(b"result line\n> ")
        result = self.session.send_command("threads")
        self.assertEqual(result, "result line")
        self.session._process.stdin.write.assert_called_once_with(b"threads\n")
        self.session._process.stdin.flush.assert_called_once()

    def test_multiline_response(self):
        self._enqueue(b"line1\nline2\nline3\n> ")
        result = self.session.send_command("classes")
        self.assertEqual(result, "line1\nline2\nline3")

    def test_not_connected_raises(self):
        self.session._connected = False
        with self.assertRaises(JdbSessionError) as ctx:
            self.session.send_command("threads")
        self.assertIn("Not connected", str(ctx.exception))

    def test_process_none_raises(self):
        self.session._process = None
        with self.assertRaises(JdbSessionError):
            self.session.send_command("threads")

    def test_process_exited_raises(self):
        self.session._process.poll.return_value = 1
        with self.assertRaises(JdbSessionError) as ctx:
            self.session.send_command("threads")
        self.assertIn("exited", str(ctx.exception))
        self.assertFalse(self.session._connected)

    def test_broken_pipe_raises_and_disconnects(self):
        self.session._process.stdin.write.side_effect = BrokenPipeError()
        with self.assertRaises(JdbSessionError) as ctx:
            self.session.send_command("threads")
        self.assertIn("Failed to send", str(ctx.exception))
        self.assertFalse(self.session._connected)

    def test_os_error_raises_and_disconnects(self):
        self.session._process.stdin.write.side_effect = OSError("pipe error")
        with self.assertRaises(JdbSessionError):
            self.session.send_command("threads")
        self.assertFalse(self.session._connected)

    def test_timeout_raises_jdb_timeout_error(self):
        # No data in queue — should timeout
        with self.assertRaises(JdbTimeoutError):
            self.session.send_command("threads", timeout=0.3)

    def test_thread_prompt_response(self):
        self._enqueue(b"some result\nmain[1] ")
        result = self.session.send_command("where")
        self.assertEqual(result, "some result")


class JdbSessionCommandBuildingTests(unittest.TestCase):
    """Test that convenience methods build correct JDB command strings."""

    def setUp(self):
        self.session = JdbSession()
        self.session._connected = True
        self.session._process = MagicMock()
        self.session._process.poll.return_value = None
        self.session._process.stdin = MagicMock()
        self.session._line_queue = queue.Queue()
        self.commands_sent = []

        def capture_send(cmd, timeout=30):
            self.commands_sent.append(cmd)
            return ""
        self.session.send_command = capture_send

    def _get_stdin_command(self):
        """Extract the command string written to stdin."""
        call_args = self.session._process.stdin.write.call_args
        return call_args[0][0].decode().strip()

    def test_run_no_args(self):
        self.session.run()
        self.assertEqual(self._get_stdin_command(), "run")

    def test_run_with_class(self):
        self.session.run(class_name="com.example.Main")
        self.assertEqual(self._get_stdin_command(), "run com.example.Main")

    def test_run_with_class_and_args(self):
        self.session.run(class_name="com.example.Main", args="arg1 arg2")
        self.assertEqual(self._get_stdin_command(), "run com.example.Main arg1 arg2")

    def test_cont(self):
        self.session.cont()
        self.assertEqual(self._get_stdin_command(), "cont")

    def test_step(self):
        self.session.step()
        self.assertEqual(self._get_stdin_command(), "step")

    def test_step_up(self):
        self.session.step_up()
        self.assertEqual(self._get_stdin_command(), "step up")

    def test_next(self):
        self.session.next_()
        self.assertEqual(self._get_stdin_command(), "next")

    def test_breakpoint_set_line(self):
        self.session.breakpoint_set("com.example.Main:42")
        self.assertEqual(self.commands_sent, ["stop at com.example.Main:42"])

    def test_breakpoint_set_method(self):
        self.session.breakpoint_set("com.example.Main.myMethod")
        self.assertEqual(self.commands_sent, ["stop in com.example.Main.myMethod"])

    def test_breakpoint_set_with_thread(self):
        self.session.breakpoint_set("com.example.Main:42", thread_id="0x1a8")
        self.assertEqual(self.commands_sent, ["stop 0x1a8 at com.example.Main:42"])

    def test_breakpoint_set_with_suspend_policy(self):
        self.session.breakpoint_set("com.example.Main:42", suspend_policy="go")
        self.assertEqual(self.commands_sent, ["stop go at com.example.Main:42"])

    def test_breakpoint_set_with_both(self):
        self.session.breakpoint_set("com.example.Main.m", suspend_policy="thread", thread_id="0x1a8")
        self.assertEqual(self.commands_sent, ["stop thread 0x1a8 in com.example.Main.m"])

    def test_breakpoint_clear(self):
        self.session.breakpoint_clear("com.example.Main:42")
        self.assertEqual(self.commands_sent, ["clear com.example.Main:42"])

    def test_breakpoint_list(self):
        self.session.breakpoint_list()
        self.assertEqual(self.commands_sent, ["clear"])

    def test_catch_all(self):
        self.session.catch("java.lang.Exception")
        self.assertEqual(self.commands_sent, ["catch java.lang.Exception"])

    def test_catch_uncaught(self):
        self.session.catch("java.lang.Exception", filter_type="uncaught")
        self.assertEqual(self.commands_sent, ["catch uncaught java.lang.Exception"])

    def test_ignore(self):
        self.session.ignore("java.lang.Exception")
        self.assertEqual(self.commands_sent, ["ignore java.lang.Exception"])

    def test_watch_default(self):
        self.session.watch("com.example.Main.x")
        self.assertEqual(self.commands_sent, ["watch com.example.Main.x"])

    def test_watch_access(self):
        self.session.watch("com.example.Main.x", access_type="access")
        self.assertEqual(self.commands_sent, ["watch access com.example.Main.x"])

    def test_watch_all(self):
        self.session.watch("com.example.Main.x", access_type="all")
        self.assertEqual(self.commands_sent, ["watch all com.example.Main.x"])

    def test_unwatch(self):
        self.session.unwatch("com.example.Main.x")
        self.assertEqual(self.commands_sent, ["unwatch com.example.Main.x"])

    def test_threads(self):
        self.session.threads()
        self.assertEqual(self.commands_sent, ["threads"])

    def test_threads_with_group(self):
        self.session.threads(thread_group="main")
        self.assertEqual(self.commands_sent, ["threads main"])

    def test_thread(self):
        self.session.thread("0x1a8")
        self.assertEqual(self.commands_sent, ["thread 0x1a8"])

    def test_suspend_all(self):
        self.session.suspend()
        self.assertEqual(self.commands_sent, ["suspend"])

    def test_suspend_specific(self):
        self.session.suspend(thread_ids=["0x1a8", "0x1a9"])
        self.assertEqual(self.commands_sent, ["suspend 0x1a8 0x1a9"])

    def test_resume_all(self):
        self.session.resume()
        self.assertEqual(self.commands_sent, ["resume"])

    def test_where(self):
        self.session.where()
        self.assertEqual(self.commands_sent, ["where"])

    def test_where_thread(self):
        self.session.where(thread_id="0x1a8")
        self.assertEqual(self.commands_sent, ["where 0x1a8"])

    def test_where_all(self):
        self.session.where_all()
        self.assertEqual(self.commands_sent, ["where all"])

    def test_up(self):
        self.session.up()
        self.assertEqual(self.commands_sent, ["up"])

    def test_up_count(self):
        self.session.up(count=3)
        self.assertEqual(self.commands_sent, ["up 3"])

    def test_down(self):
        self.session.down()
        self.assertEqual(self.commands_sent, ["down"])

    def test_print(self):
        self.session.print_("myVar")
        self.assertEqual(self.commands_sent, ["print myVar"])

    def test_dump(self):
        self.session.dump("obj")
        self.assertEqual(self.commands_sent, ["dump obj"])

    def test_eval(self):
        self.session.eval_("x + 1")
        self.assertEqual(self.commands_sent, ["eval x + 1"])

    def test_set(self):
        self.session.set_("x", "42")
        self.assertEqual(self.commands_sent, ["set x = 42"])

    def test_locals(self):
        self.session.locals_()
        self.assertEqual(self.commands_sent, ["locals"])

    def test_classes(self):
        self.session.classes()
        self.assertEqual(self.commands_sent, ["classes"])

    def test_class_info(self):
        self.session.class_info("com.example.Main")
        self.assertEqual(self.commands_sent, ["class com.example.Main"])

    def test_methods(self):
        self.session.methods("com.example.Main")
        self.assertEqual(self.commands_sent, ["methods com.example.Main"])

    def test_fields(self):
        self.session.fields("com.example.Main")
        self.assertEqual(self.commands_sent, ["fields com.example.Main"])

    def test_list_no_location(self):
        self.session.list_()
        self.assertEqual(self.commands_sent, ["list"])

    def test_list_with_location(self):
        self.session.list_("42")
        self.assertEqual(self.commands_sent, ["list 42"])

    def test_sourcepath(self):
        self.session.sourcepath("/src")
        self.assertEqual(self.commands_sent, ["use /src"])

    def test_classpath(self):
        self.session.classpath()
        self.assertEqual(self.commands_sent, ["classpath"])

    def test_lock(self):
        self.session.lock("obj")
        self.assertEqual(self.commands_sent, ["lock obj"])

    def test_threadlocks(self):
        self.session.threadlocks()
        self.assertEqual(self.commands_sent, ["threadlocks"])

    def test_threadlocks_thread(self):
        self.session.threadlocks(thread_id="0x1a8")
        self.assertEqual(self.commands_sent, ["threadlocks 0x1a8"])

    def test_pop(self):
        self.session.pop()
        self.assertEqual(self.commands_sent, ["pop"])

    def test_reenter(self):
        self.session.reenter()
        self.assertEqual(self.commands_sent, ["reenter"])

    def test_trace(self):
        self.session.trace()
        self.assertEqual(self.commands_sent, ["trace"])

    def test_trace_methods(self):
        self.session.trace(what="methods")
        self.assertEqual(self.commands_sent, ["trace methods"])

    def test_trace_with_thread(self):
        self.session.trace(what="methods", thread="0x1a8")
        self.assertEqual(self.commands_sent, ["trace methods 0x1a8"])

    def test_untrace(self):
        self.session.untrace()
        self.assertEqual(self.commands_sent, ["untrace"])

    def test_monitor(self):
        self.session.monitor("locals")
        self.assertEqual(self.commands_sent, ["monitor locals"])

    def test_monitor_list(self):
        self.session.monitor_list()
        self.assertEqual(self.commands_sent, ["monitor"])

    def test_unmonitor(self):
        self.session.unmonitor(1)
        self.assertEqual(self.commands_sent, ["unmonitor 1"])

    def test_exclude(self):
        self.session.exclude(["java.*", "javax.*"])
        self.assertEqual(self.commands_sent, ["exclude java.*,javax.*"])

    def test_exclude_display(self):
        self.session.exclude()
        self.assertEqual(self.commands_sent, ["exclude"])


class JdbSessionCloseTests(unittest.TestCase):
    def test_close_sends_quit(self):
        session = JdbSession()
        mock_process = MagicMock()
        mock_process.stdin = MagicMock()
        session._process = mock_process
        session._connected = True

        session.close()
        mock_process.stdin.write.assert_called_with(b"quit\n")
        mock_process.wait.assert_called_once()
        self.assertFalse(session.is_connected())
        self.assertIsNone(session._process)

    def test_close_kills_on_timeout(self):
        import subprocess
        session = JdbSession()
        mock_process = MagicMock()
        mock_process.stdin = MagicMock()
        mock_process.wait.side_effect = [subprocess.TimeoutExpired("jdb", 5), None]
        session._process = mock_process
        session._connected = True

        session.close()
        mock_process.kill.assert_called_once()

    def test_close_when_not_connected(self):
        session = JdbSession()
        session.close()  # should not raise


class WaitForPortTests(unittest.TestCase):
    def _make_mock_socket(self, mock_sock_cls):
        mock_sock = MagicMock()
        mock_sock_cls.return_value.__enter__ = MagicMock(return_value=mock_sock)
        mock_sock_cls.return_value.__exit__ = MagicMock(return_value=False)
        return mock_sock

    @patch("karellen_jdb_mcp.jdb_session.time.sleep")
    @patch("karellen_jdb_mcp.jdb_session.socket.socket")
    def test_port_open_immediately(self, mock_sock_cls, _mock_sleep):
        session = JdbSession()
        import time
        deadline = time.monotonic() + 5
        mock_sock = self._make_mock_socket(mock_sock_cls)
        mock_sock.connect.return_value = None
        result = session._wait_for_port("localhost", 5005, deadline)
        self.assertTrue(result)

    @patch("karellen_jdb_mcp.jdb_session.time.sleep")
    @patch("karellen_jdb_mcp.jdb_session.socket.socket")
    def test_port_not_open_timeout(self, mock_sock_cls, _mock_sleep):
        session = JdbSession()
        mock_sock = self._make_mock_socket(mock_sock_cls)
        mock_sock.connect.side_effect = ConnectionRefusedError()
        import time
        # Deadline already in the past
        result = session._wait_for_port("localhost", 5005, time.monotonic() - 1)
        self.assertFalse(result)

    @patch("karellen_jdb_mcp.jdb_session.time.sleep")
    @patch("karellen_jdb_mcp.jdb_session.socket.socket")
    def test_port_opens_after_retries(self, mock_sock_cls, _mock_sleep):
        session = JdbSession()
        import time
        deadline = time.monotonic() + 10
        call_count = [0]

        def connect_side_effect(addr):
            call_count[0] += 1
            if call_count[0] < 3:
                raise ConnectionRefusedError()

        mock_sock = self._make_mock_socket(mock_sock_cls)
        mock_sock.connect.side_effect = connect_side_effect
        result = session._wait_for_port("localhost", 5005, deadline)
        self.assertTrue(result)
        self.assertEqual(call_count[0], 3)


class ConnectWithWaitTimeoutTests(unittest.TestCase):
    def _make_version_info(self):
        from karellen_jdb_mcp.types import VersionInfo
        return VersionInfo(
            jdb_version_string="jdb 21",
            jdk_major_version=21,
            has_stop_modifiers=True,
            has_repeat_command=True,
            has_threadgroup_reset=True,
            has_track_all_threads=True,
        )

    def _make_mock_proc(self):
        mock_proc = MagicMock()
        # stdout.read must return b"" to stop the reader thread immediately
        mock_proc.stdout.read.return_value = b""
        mock_proc.stdin = MagicMock()
        mock_proc.poll.return_value = None
        return mock_proc

    @patch("karellen_jdb_mcp.jdb_session.detect_version")
    @patch("karellen_jdb_mcp.jdb_session.subprocess.Popen")
    def test_connect_no_wait_timeout(self, mock_popen, mock_detect):
        mock_detect.return_value = self._make_version_info()
        mock_popen.return_value = self._make_mock_proc()

        session = JdbSession()
        with patch.object(session, '_read_until_prompt', return_value="Initializing jdb..."):
            session.connect("jdb", "localhost", 5005)
            self.assertTrue(session.is_connected())

    @patch("karellen_jdb_mcp.jdb_session.detect_version")
    @patch("karellen_jdb_mcp.jdb_session.subprocess.Popen")
    def test_connect_with_wait_timeout_retries_on_attach_failure(self, mock_popen, mock_detect):
        mock_detect.return_value = self._make_version_info()
        mock_popen.return_value = self._make_mock_proc()

        session = JdbSession()
        call_count = [0]

        def read_side_effect(timeout):
            call_count[0] += 1
            if call_count[0] < 3:
                raise JdbSessionError("Timeout")
            return "Initializing jdb..."

        with patch.object(session, '_wait_for_port', return_value=True):
            with patch.object(session, '_read_until_prompt', side_effect=read_side_effect):
                with patch("karellen_jdb_mcp.jdb_session.time.sleep"):
                    session.connect("jdb", "localhost", 5005, wait_timeout=30)
                    self.assertTrue(session.is_connected())
                    self.assertEqual(call_count[0], 3)

    @patch("karellen_jdb_mcp.jdb_session.detect_version")
    def test_connect_with_wait_timeout_port_never_opens(self, mock_detect):
        mock_detect.return_value = self._make_version_info()
        session = JdbSession()
        with patch.object(session, '_wait_for_port', return_value=False):
            with self.assertRaises(JdbSessionError) as ctx:
                session.connect("jdb", "localhost", 5005, wait_timeout=1)
            self.assertIn("did not open", str(ctx.exception))


class StripPromptTests(unittest.TestCase):
    def test_strip_initial_prompt(self):
        session = JdbSession()
        result = session._strip_prompt("Initializing jdb ...\n> ")
        self.assertEqual(result, "Initializing jdb ...")

    def test_strip_thread_prompt(self):
        session = JdbSession()
        result = session._strip_prompt("Step completed\nmain[1] ")
        self.assertEqual(result, "Step completed")

    def test_no_prompt(self):
        session = JdbSession()
        result = session._strip_prompt("some output without prompt")
        self.assertIsNone(result)

    def test_empty_output_with_prompt(self):
        session = JdbSession()
        result = session._strip_prompt("\n> ")
        self.assertEqual(result, "")

    def test_bare_greater_than_not_matched(self):
        session = JdbSession()
        result = session._strip_prompt("x = 5\n>")
        self.assertIsNone(result)

    def test_prompt_like_output_mid_text_not_matched(self):
        session = JdbSession()
        result = session._strip_prompt("comparing x > y\nresult = true")
        self.assertIsNone(result)

    def test_virtual_thread_prompt(self):
        session = JdbSession()
        result = session._strip_prompt(
            "Step completed\nVirtualThread[#42]/runnable@ForkJoinPool-1-worker-1[1] ")
        self.assertEqual(result, "Step completed")

    def test_prompt_only(self):
        session = JdbSession()
        result = session._strip_prompt("> ")
        self.assertEqual(result, "")


class ReadUntilPromptTests(unittest.TestCase):
    """Test _read_until_prompt directly against the line queue."""

    def setUp(self):
        self.session = JdbSession()
        self.session._connected = True
        self.session._process = MagicMock()
        self.session._process.poll.return_value = None
        self.session._line_queue = queue.Queue()

    def _enqueue(self, *chunks):
        for chunk in chunks:
            self.session._line_queue.put(chunk)

    def test_prompt_detected_single_chunk(self):
        self._enqueue(b"Initializing jdb ...\n> ")
        result = self.session._read_until_prompt(timeout=2)
        self.assertEqual(result, "Initializing jdb ...")

    def test_prompt_detected_split_chunks(self):
        self._enqueue(b"output line\n", b"> ")
        result = self.session._read_until_prompt(timeout=2)
        self.assertEqual(result, "output line")

    def test_thread_prompt(self):
        self._enqueue(b"Step completed\nmain[1] ")
        result = self.session._read_until_prompt(timeout=2)
        self.assertEqual(result, "Step completed")

    def test_timeout_raises_jdb_timeout_error(self):
        # Nothing in queue — should timeout
        with self.assertRaises(JdbTimeoutError) as ctx:
            self.session._read_until_prompt(timeout=0.3)
        self.assertIn("Timeout", str(ctx.exception))

    def test_timeout_includes_partial_output(self):
        self._enqueue(b"partial output without prompt")
        with self.assertRaises(JdbTimeoutError) as ctx:
            self.session._read_until_prompt(timeout=0.5)
        self.assertIn("partial output", str(ctx.exception))

    def test_stream_ended_returns_output(self):
        from karellen_jdb_mcp.jdb_session import _STREAM_ENDED
        self._enqueue(b"final output\n> ", _STREAM_ENDED)
        result = self.session._read_until_prompt(timeout=2)
        self.assertEqual(result, "final output")

    def test_stream_ended_no_prompt_returns_raw(self):
        from karellen_jdb_mcp.jdb_session import _STREAM_ENDED
        self._enqueue(b"output with no prompt", _STREAM_ENDED)
        result = self.session._read_until_prompt(timeout=2)
        self.assertEqual(result, "output with no prompt")

    def test_process_exited_returns_output(self):
        self.session._process.poll.return_value = 0
        self._enqueue(b"exited output")
        result = self.session._read_until_prompt(timeout=1)
        self.assertEqual(result, "exited output")

    def test_settle_time_false_positive_prompt(self):
        """A prompt-like line followed by more data is not a false return."""
        self._enqueue(b"main[1] ", b"extra output\nmain[1] ")
        result = self.session._read_until_prompt(timeout=2)
        self.assertIn("extra output", result)

    def test_multiline_output_with_prompt(self):
        self._enqueue(b"line1\nline2\nline3\n> ")
        result = self.session._read_until_prompt(timeout=2)
        self.assertEqual(result, "line1\nline2\nline3")

    def test_stream_ended_during_settle(self):
        """Stream ending during settle time still returns properly."""
        from karellen_jdb_mcp.jdb_session import _STREAM_ENDED
        self._enqueue(b"output\nmain[1] ", _STREAM_ENDED)
        result = self.session._read_until_prompt(timeout=2)
        self.assertEqual(result, "output")

    def test_virtual_thread_prompt(self):
        self._enqueue(
            b"Step completed\n"
            b"VirtualThread[#42]/runnable@ForkJoinPool-1-worker-1[1] ")
        result = self.session._read_until_prompt(timeout=2)
        self.assertEqual(result, "Step completed")


class JdbTimeoutErrorTests(unittest.TestCase):
    def test_is_subclass_of_session_error(self):
        self.assertTrue(issubclass(JdbTimeoutError, JdbSessionError))

    def test_isinstance_check(self):
        err = JdbTimeoutError("timed out")
        self.assertIsInstance(err, JdbSessionError)
        self.assertIsInstance(err, JdbTimeoutError)


class ExecutionCommandTests(unittest.TestCase):
    """Test that execution commands use content-based completion, not prompt-based."""

    def setUp(self):
        self.session = JdbSession()
        self.session._connected = True
        self.session._process = MagicMock()
        self.session._process.poll.return_value = None
        self.session._process.stdin = MagicMock()
        self.session._line_queue = queue.Queue()

    def _enqueue(self, *chunks):
        """Enqueue byte chunks for the reader to find."""
        for chunk in chunks:
            self.session._line_queue.put(chunk)

    def test_cont_returns_empty_when_no_output(self):
        """Fire-and-forget: execution resumed, no output within timeout."""
        from karellen_jdb_mcp import jdb_session
        orig = jdb_session.TIMEOUT_RESUME
        try:
            jdb_session.TIMEOUT_RESUME = 0.3
            result = self.session.cont()
            self.assertEqual(result, "")
        finally:
            jdb_session.TIMEOUT_RESUME = orig

    def test_cont_returns_immediately_on_nothing_suspended(self):
        """'Nothing suspended.' response should return immediately, no prompt needed."""
        self._enqueue(b"> Nothing suspended.\n")
        result = self.session.cont()
        self.assertIn("Nothing suspended.", result)

    def test_cont_returns_immediately_with_prompt(self):
        """When prompt IS present, strip it and return."""
        self._enqueue(b"Nothing suspended.\n> ")
        result = self.session.cont()
        self.assertEqual(result, "Nothing suspended.")

    def test_step_returns_stop_event(self):
        self._enqueue(
            b'Step completed: "thread=main", com.example.Main.foo(), '
            b'line=21 bci=5\nmain[1] ')
        result = self.session.step()
        self.assertIn("Step completed", result)

    def test_next_returns_stop_event(self):
        self._enqueue(
            b'Step completed: "thread=main", com.example.Main.foo(), '
            b'line=22 bci=8\nmain[1] ')
        result = self.session.next_()
        self.assertIn("Step completed", result)

    def test_step_up_returns_stop_event(self):
        self._enqueue(
            b'Step completed: "thread=main", com.example.Main.main(), '
            b'line=11 bci=3\nmain[1] ')
        result = self.session.step_up()
        self.assertIn("Step completed", result)

    def test_run_returns_empty_when_no_output(self):
        from karellen_jdb_mcp import jdb_session
        orig = jdb_session.TIMEOUT_RESUME
        try:
            jdb_session.TIMEOUT_RESUME = 0.3
            result = self.session.run()
            self.assertEqual(result, "")
        finally:
            jdb_session.TIMEOUT_RESUME = orig

    def test_cont_not_connected_raises(self):
        self.session._connected = False
        with self.assertRaises(JdbSessionError):
            self.session.cont()

    def test_cont_process_exited_raises(self):
        self.session._process.poll.return_value = 1
        with self.assertRaises(JdbSessionError):
            self.session.cont()

    def test_cont_broken_pipe_raises(self):
        self.session._process.stdin.write.side_effect = BrokenPipeError()
        with self.assertRaises(JdbSessionError):
            self.session.cont()

    def test_stream_ended_returns_output(self):
        from karellen_jdb_mcp.jdb_session import _STREAM_ENDED
        self._enqueue(b"Nothing suspended.\n", _STREAM_ENDED)
        result = self.session.cont()
        self.assertIn("Nothing suspended.", result)


class WaitForEventTests(unittest.TestCase):
    """Test wait_for_event blocks until stop event or timeout."""

    def setUp(self):
        self.session = JdbSession()
        self.session._connected = True
        self.session._process = MagicMock()
        self.session._process.poll.return_value = None
        self.session._line_queue = queue.Queue()

    def _enqueue(self, *chunks):
        for chunk in chunks:
            self.session._line_queue.put(chunk)

    def test_returns_stop_event_with_prompt(self):
        self._enqueue(
            b'Breakpoint hit: "thread=main", com.example.Main.foo(), '
            b'line=42 bci=0\nmain[1] ')
        result = self.session.wait_for_event(timeout=2)
        self.assertIn("Breakpoint hit", result)

    def test_returns_empty_on_timeout(self):
        result = self.session.wait_for_event(timeout=0.3)
        self.assertEqual(result, "")

    def test_returns_stop_event_without_prompt(self):
        self._enqueue(
            b'Breakpoint hit: "thread=main", com.example.Main.foo(), '
            b'line=42 bci=0\n')
        result = self.session.wait_for_event(timeout=1)
        self.assertIn("Breakpoint hit", result)

    def test_not_connected_raises(self):
        self.session._connected = False
        with self.assertRaises(JdbSessionError):
            self.session.wait_for_event()

    def test_process_exited_raises(self):
        self.session._process.poll.return_value = 1
        with self.assertRaises(JdbSessionError):
            self.session.wait_for_event()

    def test_stream_ended_returns_output(self):
        from karellen_jdb_mcp.jdb_session import _STREAM_ENDED
        self._enqueue(
            b'The application exited\n', _STREAM_ENDED)
        result = self.session.wait_for_event(timeout=2)
        self.assertIn("application exited", result)

    def test_delayed_event(self):
        """Event arriving after initial silence is still caught."""
        import threading

        def delayed_enqueue():
            time.sleep(0.3)
            self.session._line_queue.put(
                b'Breakpoint hit: "thread=main", Main.m(), line=10\nmain[1] ')

        t = threading.Thread(target=delayed_enqueue)
        t.start()
        result = self.session.wait_for_event(timeout=2)
        t.join()
        self.assertIn("Breakpoint hit", result)
