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

"""JDB subprocess management and command execution."""

import logging
import os
import queue
import re
import socket
import subprocess
import threading
import time

from karellen_jdb_mcp.version import detect_version

logger = logging.getLogger(__name__)


def _env_timeout(name, default):
    """Read a timeout from environment variable, falling back to default."""
    value = os.environ.get(name)
    if value is not None:
        try:
            return int(value)
        except ValueError:
            logger.warning("Invalid value for %s: %r, using default %d", name, value, default)
    return default


TIMEOUT_CONNECT = _env_timeout("JDB_MCP_TIMEOUT_CONNECT", 60)
TIMEOUT_COMMAND = _env_timeout("JDB_MCP_TIMEOUT_COMMAND", 30)
TIMEOUT_EXECUTION = _env_timeout("JDB_MCP_TIMEOUT_EXECUTION", 120)

PORT_POLL_INTERVAL = 1.0
JDB_ATTACH_TIMEOUT = 15

# JDB prompt patterns:
# "> " (initial prompt before run)
# "main[1] " (thread[depth] after breakpoint)
# "Thread-0[2] " (any thread name with depth)
# "VirtualThread[#42]/runnable@ForkJoinPool-1-worker-1[1] " (JDK 20+ virtual threads)
# The prompt is: <thread-name>[<depth>]<space> where <depth> is a single integer
# and <thread-name> can contain nearly any character (including [] in virtual thread names).
# We match greedily: everything up to the LAST [digits] followed by a single space at EOL.
PROMPT_RE = re.compile(r'^(?:> |.+\[\d+\] )$')

# Prompt detection timeout: how long to wait after seeing a potential prompt
# before deciding the command is done (in seconds)
PROMPT_SETTLE_TIME = 0.2

# Sentinel value for stream-ended (distinct from None which queue.get returns on timeout)
_STREAM_ENDED = object()


class JdbSessionError(Exception):
    pass


class JdbSession:
    def __init__(self):
        self._process = None
        self._connected = False
        self._version_info = None
        self._reader_thread = None
        self._line_queue = queue.Queue()
        self._reader_lock = threading.Lock()
        self._closed = False
        self._stream_ended = False

    @property
    def version_info(self):
        return self._version_info

    def is_connected(self):
        return self._connected

    def connect(self, jdb_path, host, port, sourcepath=None, classpath=None,
                trackallthreads=False, wait_timeout=0):
        """Start JDB and attach to a running JVM.

        Args:
            jdb_path: Path to the jdb executable.
            host: Host where the JVM is listening.
            port: JDWP debug port.
            sourcepath: Colon-separated source directories.
            classpath: Colon-separated class directories.
            trackallthreads: Track all threads including virtual (JDK 20+).
            wait_timeout: Seconds to wait for the JDWP port to become available.
                0 means no waiting (fail immediately if port is not open).
                When set, polls the port and retries JDB attach until the JVM
                is ready or the timeout expires.
        """
        self._version_info = detect_version(jdb_path)

        cmd = [jdb_path, "-attach", "%s:%d" % (host, port)]
        if sourcepath:
            cmd.extend(["-sourcepath", sourcepath])
        if classpath:
            cmd.extend(["-classpath", classpath])
        if trackallthreads:
            if self._version_info.has_track_all_threads:
                cmd.append("-trackallthreads")
            else:
                logger.warning("-trackallthreads not supported on JDK %d",
                               self._version_info.jdk_major_version)

        deadline = time.monotonic() + wait_timeout

        while True:
            # Wait for port to accept TCP connections before spawning JDB
            if wait_timeout > 0:
                if not self._wait_for_port(host, port, deadline):
                    raise JdbSessionError(
                        "JDWP port %s:%d did not open within %ds"
                        % (host, port, wait_timeout))

            logger.info("Starting JDB: %s", cmd)
            self._process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                bufsize=0,
            )
            self._closed = False
            self._stream_ended = False
            self._line_queue = queue.Queue()
            self._start_reader()

            try:
                attach_timeout = min(JDB_ATTACH_TIMEOUT, max(1, deadline - time.monotonic())) \
                    if wait_timeout > 0 else TIMEOUT_CONNECT
                initial_output = self._read_until_prompt(timeout=attach_timeout)
                logger.info("JDB connected. Initial output: %s", initial_output[:200])
                self._connected = True
                return
            except JdbSessionError as e:
                self.close()

                if wait_timeout <= 0 or time.monotonic() >= deadline:
                    raise

                logger.info("JDB attach failed (%s), retrying...", e)
                time.sleep(PORT_POLL_INTERVAL)

    def _wait_for_port(self, host, port, deadline):
        """Poll until a TCP connection to host:port succeeds or deadline expires."""
        while time.monotonic() < deadline:
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.settimeout(min(PORT_POLL_INTERVAL, max(0.1, deadline - time.monotonic())))
                    s.connect((host, port))
                    return True
            except (ConnectionRefusedError, OSError, socket.timeout):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                time.sleep(min(PORT_POLL_INTERVAL, remaining))
        return False

    def send_command(self, command, timeout=TIMEOUT_COMMAND):
        """Send a command to JDB and return all output until the next prompt.

        Args:
            command: JDB command string.
            timeout: Maximum seconds to wait for response.

        Returns:
            Raw JDB output text (without the prompt).

        Raises:
            JdbSessionError: If session is not connected or communication fails.
        """
        if not self._connected or self._process is None:
            raise JdbSessionError("Not connected to JDB")

        if self._process.poll() is not None:
            self._connected = False
            raise JdbSessionError("JDB process has exited")

        logger.debug("JDB command: %s", command)
        try:
            self._process.stdin.write((command + "\n").encode())
            self._process.stdin.flush()
        except (BrokenPipeError, OSError) as e:
            self._connected = False
            raise JdbSessionError("Failed to send command: %s" % e) from e

        output = self._read_until_prompt(timeout=timeout)
        logger.debug("JDB response: %s", output[:500])
        return output

    def _start_reader(self):
        """Start the background thread that reads JDB stdout."""
        self._reader_thread = threading.Thread(
            target=self._reader_loop, daemon=True)
        self._reader_thread.start()

    def _reader_loop(self):
        """Continuously read from JDB stdout and enqueue chunks."""
        try:
            while not self._closed:
                data = self._process.stdout.read(4096)
                if not data:
                    break
                self._line_queue.put(data)
        except (OSError, ValueError):
            pass
        finally:
            self._line_queue.put(_STREAM_ENDED)

    def _read_until_prompt(self, timeout):
        """Read output from JDB until a prompt is detected.

        Accumulates data from the reader thread's queue. After each chunk,
        checks if the buffer ends with a prompt pattern. Uses a settle time
        to avoid false-matching on output lines that resemble prompts: after
        a potential prompt is seen, waits PROMPT_SETTLE_TIME for more data.
        If more data arrives, re-evaluates. If not, accepts the prompt.

        Returns:
            The accumulated output text (without the trailing prompt).
        """
        buf = b""
        deadline = time.monotonic() + timeout
        last_data_time = time.monotonic()

        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                text = buf.decode("utf-8", errors="replace")
                raise JdbSessionError(
                    "Timeout waiting for JDB prompt after %ds. Output so far: %s"
                    % (timeout, text[:500]))

            try:
                chunk = self._line_queue.get(timeout=min(remaining, PROMPT_SETTLE_TIME))
            except queue.Empty:
                chunk = None

            if chunk is _STREAM_ENDED:
                self._stream_ended = True
                text = buf.decode("utf-8", errors="replace")
                return self._strip_prompt(text) or text

            if chunk is None:
                # Timeout — no data arrived. Check if we have a prompt candidate.
                text = buf.decode("utf-8", errors="replace")
                prompt_result = self._strip_prompt(text)
                if prompt_result is not None and (time.monotonic() - last_data_time >= PROMPT_SETTLE_TIME):
                    return prompt_result

                if self._process is not None and self._process.poll() is not None:
                    return self._strip_prompt(text) or text

                continue

            buf += chunk
            last_data_time = time.monotonic()

            text = buf.decode("utf-8", errors="replace")
            prompt_result = self._strip_prompt(text)
            if prompt_result is not None:
                # Potential prompt found. Wait settle time for more data.
                settle_deadline = time.monotonic() + PROMPT_SETTLE_TIME
                while time.monotonic() < settle_deadline:
                    try:
                        extra = self._line_queue.get(
                            timeout=settle_deadline - time.monotonic())
                    except queue.Empty:
                        break
                    if extra is _STREAM_ENDED:
                        self._stream_ended = True
                        text = buf.decode("utf-8", errors="replace")
                        return self._strip_prompt(text) or text
                    buf += extra
                    last_data_time = time.monotonic()
                    text = buf.decode("utf-8", errors="replace")
                    new_result = self._strip_prompt(text)
                    if new_result is not None:
                        prompt_result = new_result
                    else:
                        # More data arrived that no longer ends with a prompt.
                        # The previous match was a false positive. Break settle
                        # loop and return to the main loop.
                        prompt_result = None
                        break

                if prompt_result is not None:
                    return prompt_result

    def _strip_prompt(self, text):
        """Check if text ends with a JDB prompt, and if so return text without it.

        Only matches a prompt at the very end of the buffer, on its own line
        (after a newline). This avoids false-matching on output lines that
        happen to contain prompt-like text.

        Returns the text with the prompt stripped, or None if no prompt is found.
        """
        # The prompt always appears after a newline (or at start of output).
        # Split on newline and check the last segment.
        nl_pos = text.rfind("\n")
        if nl_pos >= 0:
            last_line = text[nl_pos + 1:]
        else:
            last_line = text

        if PROMPT_RE.match(last_line):
            if nl_pos >= 0:
                return text[:nl_pos]
            return ""

        return None

    def close(self):
        """Terminate the JDB session."""
        self._closed = True
        if self._process is not None:
            logger.info("Closing JDB session")
            try:
                self._process.stdin.write(b"quit\n")
                self._process.stdin.flush()
                self._process.wait(timeout=5)
            except (BrokenPipeError, OSError, subprocess.TimeoutExpired):
                try:
                    self._process.kill()
                    self._process.wait(timeout=5)
                except (OSError, subprocess.TimeoutExpired):
                    pass
            finally:
                self._process = None
        self._connected = False

    # --- Convenience Methods ---
    # Each returns raw JDB text output for the parser layer.

    def run(self, class_name=None, args=None):
        if args and not class_name:
            raise JdbSessionError("args requires class_name to be specified")
        cmd = "run"
        if class_name:
            cmd = "run %s" % class_name
            if args:
                cmd = "%s %s" % (cmd, args)
        return self.send_command(cmd, timeout=TIMEOUT_EXECUTION)

    def cont(self):
        return self.send_command("cont", timeout=TIMEOUT_EXECUTION)

    def step(self):
        return self.send_command("step", timeout=TIMEOUT_EXECUTION)

    def step_up(self):
        return self.send_command("step up", timeout=TIMEOUT_EXECUTION)

    def next_(self):
        return self.send_command("next", timeout=TIMEOUT_EXECUTION)

    def breakpoint_set(self, location, thread_id=None, suspend_policy=None):
        if ":" in location:
            cmd = "stop at %s" % location
        else:
            cmd = "stop in %s" % location

        if suspend_policy or thread_id:
            prefix = "stop"
            if suspend_policy:
                prefix = "stop %s" % suspend_policy
            if thread_id:
                prefix = "%s %s" % (prefix, thread_id)
            if ":" in location:
                cmd = "%s at %s" % (prefix, location)
            else:
                cmd = "%s in %s" % (prefix, location)

        return self.send_command(cmd)

    def breakpoint_clear(self, location):
        return self.send_command("clear %s" % location)

    def breakpoint_list(self):
        return self.send_command("clear")

    def catch(self, class_pattern, filter_type="all"):
        if filter_type and filter_type != "all":
            return self.send_command("catch %s %s" % (filter_type, class_pattern))
        return self.send_command("catch %s" % class_pattern)

    def ignore(self, class_pattern, filter_type="all"):
        if filter_type and filter_type != "all":
            return self.send_command("ignore %s %s" % (filter_type, class_pattern))
        return self.send_command("ignore %s" % class_pattern)

    def watch(self, class_field, access_type="modification"):
        if access_type == "access":
            return self.send_command("watch access %s" % class_field)
        elif access_type == "all":
            return self.send_command("watch all %s" % class_field)
        return self.send_command("watch %s" % class_field)

    def unwatch(self, class_field, access_type="modification"):
        if access_type == "access":
            return self.send_command("unwatch access %s" % class_field)
        elif access_type == "all":
            return self.send_command("unwatch all %s" % class_field)
        return self.send_command("unwatch %s" % class_field)

    def threads(self, thread_group=None):
        if thread_group:
            return self.send_command("threads %s" % thread_group)
        return self.send_command("threads")

    def thread(self, thread_id):
        return self.send_command("thread %s" % thread_id)

    def suspend(self, thread_ids=None):
        if thread_ids:
            return self.send_command("suspend %s" % " ".join(str(t) for t in thread_ids))
        return self.send_command("suspend")

    def resume(self, thread_ids=None):
        if thread_ids:
            return self.send_command("resume %s" % " ".join(str(t) for t in thread_ids))
        return self.send_command("resume")

    def where(self, thread_id=None):
        if thread_id:
            return self.send_command("where %s" % thread_id)
        return self.send_command("where")

    def where_all(self):
        return self.send_command("where all")

    def up(self, count=1):
        if count > 1:
            return self.send_command("up %d" % count)
        return self.send_command("up")

    def down(self, count=1):
        if count > 1:
            return self.send_command("down %d" % count)
        return self.send_command("down")

    def print_(self, expression):
        return self.send_command("print %s" % expression)

    def dump(self, expression):
        return self.send_command("dump %s" % expression)

    def eval_(self, expression):
        return self.send_command("eval %s" % expression)

    def set_(self, lvalue, expression):
        return self.send_command("set %s = %s" % (lvalue, expression))

    def locals_(self):
        return self.send_command("locals")

    def classes(self):
        return self.send_command("classes")

    def class_info(self, class_id):
        return self.send_command("class %s" % class_id)

    def methods(self, class_id):
        return self.send_command("methods %s" % class_id)

    def fields(self, class_id):
        return self.send_command("fields %s" % class_id)

    def list_(self, location=None):
        if location:
            return self.send_command("list %s" % location)
        return self.send_command("list")

    def sourcepath(self, path=None):
        if path:
            return self.send_command("use %s" % path)
        return self.send_command("use")

    def classpath(self):
        return self.send_command("classpath")

    def lock(self, expression):
        return self.send_command("lock %s" % expression)

    def threadlocks(self, thread_id=None):
        if thread_id:
            return self.send_command("threadlocks %s" % thread_id)
        return self.send_command("threadlocks")

    def pop(self):
        return self.send_command("pop")

    def reenter(self):
        return self.send_command("reenter")

    def trace(self, what=None, thread=None):
        cmd = "trace"
        if what:
            cmd = "%s %s" % (cmd, what)
        if thread:
            cmd = "%s %s" % (cmd, thread)
        return self.send_command(cmd)

    def untrace(self):
        return self.send_command("untrace")

    def monitor(self, command):
        return self.send_command("monitor %s" % command)

    def monitor_list(self):
        return self.send_command("monitor")

    def unmonitor(self, monitor_number):
        return self.send_command("unmonitor %d" % monitor_number)

    def exclude(self, class_patterns=None):
        if class_patterns:
            return self.send_command("exclude %s" % ",".join(class_patterns))
        return self.send_command("exclude")
