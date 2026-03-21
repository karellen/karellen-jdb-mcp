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

from karellen_jdb_mcp.process_manager import (
    ProcessManager, ManagedProcess, ProcessManagerError,
    _find_free_port,
)


class FindFreePortTests(unittest.TestCase):
    def test_returns_positive_int(self):
        port = _find_free_port()
        self.assertIsInstance(port, int)
        self.assertGreater(port, 0)

    def test_returns_different_ports(self):
        port1 = _find_free_port()
        port2 = _find_free_port()
        self.assertNotEqual(port1, port2)


class ManagedProcessTests(unittest.TestCase):
    def test_is_running_true(self):
        proc = MagicMock()
        proc.poll.return_value = None
        proc.pid = 1234
        managed = ManagedProcess(5005, ["java"], proc, "/tmp")
        self.assertTrue(managed.is_running())
        self.assertEqual(managed.pid, 1234)
        self.assertEqual(managed.port, 5005)

    def test_is_running_false(self):
        proc = MagicMock()
        proc.poll.return_value = 0
        managed = ManagedProcess(5005, ["java"], proc, "/tmp")
        self.assertFalse(managed.is_running())
        self.assertEqual(managed.exit_code(), 0)

    def test_stop_terminates(self):
        proc = MagicMock()
        proc.poll.return_value = None
        proc.pid = 1234
        managed = ManagedProcess(5005, ["java"], proc, "/tmp")
        managed.stop()
        proc.terminate.assert_called_once()
        proc.wait.assert_called_once()

    def test_stop_kills_on_timeout(self):
        import subprocess
        proc = MagicMock()
        proc.poll.return_value = None
        proc.pid = 1234
        proc.wait.side_effect = [subprocess.TimeoutExpired("java", 10), None]
        managed = ManagedProcess(5005, ["java"], proc, "/tmp")
        managed.stop()
        proc.terminate.assert_called_once()
        proc.kill.assert_called_once()

    def test_stop_already_exited(self):
        proc = MagicMock()
        proc.poll.return_value = 0
        managed = ManagedProcess(5005, ["java"], proc, "/tmp")
        managed.stop()
        proc.terminate.assert_not_called()


@patch("karellen_jdb_mcp.process_manager.time.sleep")
class ProcessManagerLaunchTests(unittest.TestCase):
    def _make_running_proc(self, pid=5555):
        proc = MagicMock()
        proc.pid = pid
        proc.poll.return_value = None
        return proc

    @patch("karellen_jdb_mcp.process_manager._find_free_port")
    @patch("karellen_jdb_mcp.process_manager.subprocess.Popen")
    def test_launch_substitutes_port(self, mock_popen, mock_port, _sleep):
        mock_port.return_value = 9876
        mock_popen.return_value = self._make_running_proc(5555)

        mgr = ProcessManager()
        managed = mgr.launch(["java", "-agentlib:jdwp=address=*:${JDB_PORT}", "Main"])

        self.assertEqual(managed.port, 9876)
        self.assertEqual(managed.pid, 5555)
        self.assertEqual(managed.command, ["java", "-agentlib:jdwp=address=*:9876", "Main"])
        mock_popen.assert_called_once()
        call_args = mock_popen.call_args
        self.assertEqual(call_args[0][0], ["java", "-agentlib:jdwp=address=*:9876", "Main"])

    @patch("karellen_jdb_mcp.process_manager._find_free_port")
    @patch("karellen_jdb_mcp.process_manager.subprocess.Popen")
    def test_launch_with_working_directory(self, mock_popen, mock_port, _sleep):
        mock_port.return_value = 9877
        mock_popen.return_value = self._make_running_proc(5556)

        mgr = ProcessManager()
        managed = mgr.launch(["java", "Main"], working_directory="/my/project")

        call_kwargs = mock_popen.call_args[1]
        self.assertEqual(call_kwargs["cwd"], "/my/project")
        self.assertEqual(managed.working_directory, "/my/project")

    @patch("karellen_jdb_mcp.process_manager._find_free_port")
    @patch("karellen_jdb_mcp.process_manager.subprocess.Popen")
    def test_launch_with_env(self, mock_popen, mock_port, _sleep):
        mock_port.return_value = 9878
        mock_popen.return_value = self._make_running_proc(5557)

        mgr = ProcessManager()
        mgr.launch(["java", "Main"], env={"MY_VAR": "my_value"})

        call_kwargs = mock_popen.call_args[1]
        self.assertIn("MY_VAR", call_kwargs["env"])
        self.assertEqual(call_kwargs["env"]["MY_VAR"], "my_value")

    @patch("karellen_jdb_mcp.process_manager._find_free_port")
    @patch("karellen_jdb_mcp.process_manager.subprocess.Popen")
    def test_launch_failure_raises(self, mock_popen, mock_port, _sleep):
        mock_port.return_value = 9879
        mock_popen.side_effect = FileNotFoundError("java not found")

        mgr = ProcessManager()
        with self.assertRaises(ProcessManagerError) as ctx:
            mgr.launch(["java", "Main"])
        self.assertIn("Failed to launch", str(ctx.exception))

    @patch("karellen_jdb_mcp.process_manager._find_free_port")
    @patch("karellen_jdb_mcp.process_manager.subprocess.Popen")
    def test_launch_uses_start_new_session(self, mock_popen, mock_port, _sleep):
        mock_port.return_value = 9880
        mock_popen.return_value = self._make_running_proc(5558)

        mgr = ProcessManager()
        mgr.launch(["java", "Main"])

        call_kwargs = mock_popen.call_args[1]
        self.assertTrue(call_kwargs["start_new_session"])

    def _make_dead_proc(self, pid=100, exit_code=2, stderr_text="Address already in use"):
        from io import BytesIO
        proc = MagicMock()
        proc.pid = pid
        proc.poll.return_value = exit_code
        proc.stderr = BytesIO(stderr_text.encode())
        return proc

    @patch("karellen_jdb_mcp.process_manager._find_free_port")
    @patch("karellen_jdb_mcp.process_manager.subprocess.Popen")
    def test_launch_retries_on_port_conflict(self, mock_popen, mock_port, _sleep):
        mock_port.side_effect = [9001, 9002, 9003]
        dead1 = self._make_dead_proc(100, 2, "ERROR: transport error 202: bind failed: Address already in use")
        dead2 = self._make_dead_proc(101, 2, "bind failed: Address already in use")
        alive = self._make_running_proc(200)
        mock_popen.side_effect = [dead1, dead2, alive]

        mgr = ProcessManager()
        managed = mgr.launch(["java", "Main"])

        self.assertEqual(managed.port, 9003)
        self.assertEqual(managed.pid, 200)
        self.assertEqual(mock_popen.call_count, 3)

    @patch("karellen_jdb_mcp.process_manager._find_free_port")
    @patch("karellen_jdb_mcp.process_manager.subprocess.Popen")
    def test_launch_all_retries_exhausted(self, mock_popen, mock_port, _sleep):
        mock_port.side_effect = [9001, 9002, 9003]
        mock_popen.side_effect = [
            self._make_dead_proc(100, 2, "Address already in use"),
            self._make_dead_proc(101, 2, "Address already in use"),
            self._make_dead_proc(102, 2, "Address already in use"),
        ]

        mgr = ProcessManager()
        with self.assertRaises(ProcessManagerError) as ctx:
            mgr.launch(["java", "Main"])
        self.assertIn("Failed to launch after", str(ctx.exception))

    @patch("karellen_jdb_mcp.process_manager._find_free_port")
    @patch("karellen_jdb_mcp.process_manager.subprocess.Popen")
    def test_launch_non_port_error_does_not_retry(self, mock_popen, mock_port, _sleep):
        mock_port.return_value = 9001
        mock_popen.return_value = self._make_dead_proc(100, 1, "Error: Main class not found")

        mgr = ProcessManager()
        with self.assertRaises(ProcessManagerError) as ctx:
            mgr.launch(["java", "Main"])
        self.assertIn("Main class not found", str(ctx.exception))
        self.assertEqual(mock_popen.call_count, 1)


@patch("karellen_jdb_mcp.process_manager.time.sleep")
class ProcessManagerMultipleLaunchTests(unittest.TestCase):
    def _make_running_proc(self, pid=100):
        proc = MagicMock()
        proc.pid = pid
        proc.poll.return_value = None
        return proc

    @patch("karellen_jdb_mcp.process_manager._find_free_port")
    @patch("karellen_jdb_mcp.process_manager.subprocess.Popen")
    def test_multiple_launches(self, mock_popen, mock_port, _sleep):
        mock_port.side_effect = [9001, 9002, 9003]
        mock_popen.return_value = self._make_running_proc()

        mgr = ProcessManager()
        m1 = mgr.launch(["java", "App1"])
        m2 = mgr.launch(["java", "App2"])
        m3 = mgr.launch(["java", "App3"])

        self.assertEqual(m1.port, 9001)
        self.assertEqual(m2.port, 9002)
        self.assertEqual(m3.port, 9003)
        self.assertEqual(len(mgr.list_all()), 3)

    @patch("karellen_jdb_mcp.process_manager._find_free_port")
    @patch("karellen_jdb_mcp.process_manager.subprocess.Popen")
    def test_list_all(self, mock_popen, mock_port, _sleep):
        mock_port.side_effect = [9001, 9002]
        mock_popen.return_value = self._make_running_proc()

        mgr = ProcessManager()
        mgr.launch(["java", "App1"])
        mgr.launch(["java", "App2"])

        all_procs = mgr.list_all()
        self.assertEqual(len(all_procs), 2)
        ports = {p.port for p in all_procs}
        self.assertEqual(ports, {9001, 9002})


@patch("karellen_jdb_mcp.process_manager.time.sleep")
class ProcessManagerStopTests(unittest.TestCase):
    @patch("karellen_jdb_mcp.process_manager._find_free_port")
    @patch("karellen_jdb_mcp.process_manager.subprocess.Popen")
    def test_stop_by_port(self, mock_popen, mock_port, _sleep):
        mock_port.return_value = 9001
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        mock_proc.pid = 100
        mock_popen.return_value = mock_proc

        mgr = ProcessManager()
        mgr.launch(["java", "Main"])
        stopped = mgr.stop(9001)

        self.assertEqual(stopped.port, 9001)
        mock_proc.terminate.assert_called_once()
        self.assertIsNone(mgr.get(9001))

    def test_stop_nonexistent_port_raises(self, _sleep):
        mgr = ProcessManager()
        with self.assertRaises(ProcessManagerError) as ctx:
            mgr.stop(9999)
        self.assertIn("No managed process", str(ctx.exception))

    @patch("karellen_jdb_mcp.process_manager._find_free_port")
    @patch("karellen_jdb_mcp.process_manager.subprocess.Popen")
    def test_stop_all(self, mock_popen, mock_port, _sleep):
        mock_port.side_effect = [9001, 9002]
        mock_proc1 = MagicMock(pid=100)
        mock_proc1.poll.return_value = None
        mock_proc2 = MagicMock(pid=101)
        mock_proc2.poll.return_value = None
        mock_popen.side_effect = [mock_proc1, mock_proc2]

        mgr = ProcessManager()
        mgr.launch(["java", "App1"])
        mgr.launch(["java", "App2"])
        mgr.stop_all()

        mock_proc1.terminate.assert_called_once()
        mock_proc2.terminate.assert_called_once()
        self.assertEqual(len(mgr.list_all()), 0)


@patch("karellen_jdb_mcp.process_manager.time.sleep")
class ProcessManagerGetTests(unittest.TestCase):
    @patch("karellen_jdb_mcp.process_manager._find_free_port")
    @patch("karellen_jdb_mcp.process_manager.subprocess.Popen")
    def test_get_existing(self, mock_popen, mock_port, _sleep):
        mock_port.return_value = 9001
        proc = MagicMock(pid=100)
        proc.poll.return_value = None
        mock_popen.return_value = proc

        mgr = ProcessManager()
        mgr.launch(["java", "Main"])

        managed = mgr.get(9001)
        self.assertIsNotNone(managed)
        self.assertEqual(managed.port, 9001)

    def test_get_nonexistent(self, _sleep):
        mgr = ProcessManager()
        self.assertIsNone(mgr.get(9999))
