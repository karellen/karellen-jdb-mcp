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

"""Managed JVM process lifecycle for JDB debugging."""

import logging
import os
import socket
import subprocess
import time

logger = logging.getLogger(__name__)

JDB_PORT_VAR = "${JDB_PORT}"

LAUNCH_RETRIES = 3
LAUNCH_SETTLE_TIME = 1.0


class ProcessManagerError(Exception):
    pass


def _find_free_port():
    """Allocate a free TCP port from the OS."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


class ManagedProcess:
    """A JVM process launched with JDWP enabled on a known port."""

    def __init__(self, port, command, process, working_directory):
        self.port = port
        self.command = command
        self.process = process
        self.working_directory = working_directory

    @property
    def pid(self):
        return self.process.pid

    def is_running(self):
        return self.process.poll() is None

    def exit_code(self):
        return self.process.poll()

    def stop(self):
        """Stop the managed process. SIGTERM first, SIGKILL if needed."""
        if self.process.poll() is not None:
            return
        logger.info("Stopping managed process PID %d on port %d", self.pid, self.port)
        try:
            self.process.terminate()
            self.process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            logger.warning("Process PID %d did not terminate, killing", self.pid)
            self.process.kill()
            self.process.wait(timeout=5)



class ProcessManager:
    """Manages launched JVM processes, keyed by port."""

    def __init__(self):
        self._processes = {}

    def launch(self, command, working_directory=None, env=None):
        """Launch a process with ${JDB_PORT} substituted in the command.

        Allocates a random free port, substitutes ${JDB_PORT}, and starts the
        process. If the process exits immediately (likely a port conflict from
        the TOCTOU window between port allocation and process bind), retries
        with a new port up to LAUNCH_RETRIES times.

        Args:
            command: Command as a list of strings. Any occurrence of
                ${JDB_PORT} in any element is replaced with the allocated port.
            working_directory: Working directory for the process.
            env: Optional extra environment variables (merged with current env).

        Returns:
            ManagedProcess with the allocated port and running process.

        Raises:
            ProcessManagerError: If the process cannot be started after retries.
        """
        run_env = os.environ.copy()
        if env:
            run_env.update(env)

        last_error = None
        for attempt in range(LAUNCH_RETRIES):
            port = _find_free_port()
            expanded_command = [arg.replace(JDB_PORT_VAR, str(port)) for arg in command]

            logger.info("Launching on port %d (attempt %d): %s",
                        port, attempt + 1, expanded_command)

            try:
                process = subprocess.Popen(
                    expanded_command,
                    cwd=working_directory,
                    env=run_env,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    stdin=subprocess.DEVNULL,
                    start_new_session=True,
                )
            except (FileNotFoundError, PermissionError, OSError) as e:
                raise ProcessManagerError("Failed to launch: %s" % e) from e

            # Wait briefly to detect immediate exit (e.g. port already taken)
            time.sleep(LAUNCH_SETTLE_TIME)
            exit_code = process.poll()
            if exit_code is not None:
                stderr = ""
                try:
                    stderr = process.stderr.read().decode("utf-8", errors="replace").strip()
                except Exception:
                    pass
                finally:
                    try:
                        process.stderr.close()
                    except Exception:
                        pass

                if "Address already in use" in stderr or "bind failed" in stderr:
                    last_error = ("Port %d already in use (exit code %d)"
                                  % (port, exit_code))
                    logger.warning("Launch attempt %d: %s", attempt + 1, last_error)
                    continue

                # Not a port conflict — report the actual error
                raise ProcessManagerError(
                    "Process exited immediately with code %d: %s"
                    % (exit_code, stderr[:500] if stderr else "no output"))

            # Process is running — close stderr pipe to avoid blocking the child
            try:
                process.stderr.close()
            except Exception:
                pass

            managed = ManagedProcess(port, expanded_command, process, working_directory)
            self._processes[port] = managed
            return managed

        raise ProcessManagerError(
            "Failed to launch after %d attempts. Last error: %s"
            % (LAUNCH_RETRIES, last_error)
        )

    def get(self, port):
        """Get a managed process by port.

        Returns:
            ManagedProcess or None if not found.
        """
        return self._processes.get(port)

    def list_all(self):
        """List all managed processes."""
        return list(self._processes.values())

    def stop(self, port):
        """Stop a managed process by port.

        Returns:
            The stopped ManagedProcess.

        Raises:
            ProcessManagerError: If no process is managed on this port.
        """
        managed = self._processes.pop(port, None)
        if managed is None:
            raise ProcessManagerError("No managed process on port %d" % port)
        managed.stop()
        return managed

    def stop_all(self):
        """Stop all managed processes."""
        for managed in list(self._processes.values()):
            try:
                managed.stop()
            except Exception:
                logger.debug("Error stopping process on port %d", managed.port, exc_info=True)
        self._processes.clear()
