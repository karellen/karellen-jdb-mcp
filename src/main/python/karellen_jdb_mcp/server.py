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

"""FastMCP server with tool definitions for JDB (Java Debugger)."""

import atexit
import functools
import logging
import os
import signal
import traceback

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError

from karellen_jdb_mcp.jdb_session import JdbSession, JdbSessionError
from karellen_jdb_mcp import response_parser as parser
from karellen_jdb_mcp.types import (
    BreakpointInfo, ExceptionBreakInfo, WatchpointInfo,
    StackFrame, ThreadGroupInfo, Variable,
    ClassInfo, MethodInfo, FieldInfo, LockInfo, ThreadLockInfo,
    MonitorInfo, EvalResult, StopEvent, ConnectStatus,
    StringResult, VersionInfo,
)

logger = logging.getLogger(__name__)

mcp = FastMCP("karellen-jdb-mcp", instructions=(
    "JDB (Java Debugger) MCP server. Use jdb_connect to attach to a "
    "running JVM (started with -agentlib:jdwp=transport=dt_socket,server=y,"
    "suspend=y,address=*:<port>), then use execution control and inspection "
    "tools to debug. Supports breakpoints, watchpoints, exception breakpoints, "
    "thread inspection, expression evaluation, and class introspection."
))

# Module-level singleton session state
_jdb_session = None


def _cleanup():
    global _jdb_session
    if _jdb_session is not None:
        try:
            _jdb_session.close()
        except Exception:
            pass
        _jdb_session = None


atexit.register(_cleanup)


def _handle_signal(signum, frame):
    _cleanup()
    os._exit(0)


signal.signal(signal.SIGINT, _handle_signal)
signal.signal(signal.SIGTERM, _handle_signal)


def _require_session():
    if _jdb_session is None or not _jdb_session.is_connected():
        raise JdbSessionError("No active JDB session. Call jdb_connect first.")
    return _jdb_session


def _tag_errors(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except JdbSessionError as e:
            raise ToolError("jdb: %s" % e) from e
        except ToolError:
            raise
        except Exception as e:
            tb = traceback.extract_tb(e.__traceback__)
            tb_lines = ["%s:%d in %s" % (f.filename, f.lineno, f.name) for f in tb[-3:]]
            raise ToolError("internal: %s: %s\n  %s" % (
                type(e).__name__, e, "\n  ".join(tb_lines))) from e
    return wrapper


def _check_error(output):
    """Check JDB output for errors and raise if found."""
    if parser.is_error(output):
        raise JdbSessionError(parser.get_error_message(output))


def _parse_stop(output):
    """Parse a stop event from execution output.

    Unlike rr-mcp's _require_stop (which raises on missing stop events), JDB's
    text protocol can produce valid execution results without a structured stop
    event pattern. In that case, a synthetic StopEvent with the raw output is
    returned so the caller always gets a result.
    """
    event = parser.parse_stop_event(output)
    if event is None:
        logger.debug("No structured stop event in output: %s", output[:200])
        return StopEvent(reason="completed", location=output.strip()[:200] if output else "")
    return event


# --- Session Lifecycle Tools ---

@mcp.tool()
@_tag_errors
def jdb_connect(jdb_path: str = "jdb", host: str = "localhost",
                port: int = 5005, sourcepath: str = None,
                classpath: str = None,
                trackallthreads: bool = False) -> ConnectStatus:
    """Connect to a running JVM via JDWP. The JVM must be started with:
    java -agentlib:jdwp=transport=dt_socket,server=y,suspend=y,address=*:<port> ...

    Args:
        jdb_path: Path to the jdb executable (default: "jdb" from PATH).
        host: Host where the JVM is listening (default: localhost).
        port: JDWP debug port (default: 5005).
        sourcepath: Colon-separated source directories for source listing.
        classpath: Colon-separated class directories.
        trackallthreads: Track all threads including virtual threads (JDK 20+).
    """
    global _jdb_session
    if _jdb_session is not None:
        raise ToolError("jdb: A JDB session is already active. Call jdb_disconnect first.")

    session = JdbSession()
    try:
        session.connect(jdb_path, host, port, sourcepath=sourcepath,
                        classpath=classpath, trackallthreads=trackallthreads)
    except (JdbSessionError, FileNotFoundError, ValueError):
        try:
            session.close()
        except Exception:
            pass
        raise

    _jdb_session = session
    vi = session.version_info
    return ConnectStatus(
        host=host,
        port=port,
        message="Connected to %s:%d. JDB is ready." % (host, port),
        jdb_version=vi.jdb_version_string if vi else None,
        jdk_major_version=vi.jdk_major_version if vi else None,
    )


@mcp.tool()
@_tag_errors
def jdb_disconnect() -> StringResult:
    """Disconnect from the JVM and clean up the JDB session."""
    if _jdb_session is None:
        return StringResult(result="No active JDB session.")
    _cleanup()
    return StringResult(result="JDB session closed.")


@mcp.tool()
@_tag_errors
def jdb_version() -> VersionInfo:
    """Get JDB version information and available features."""
    session = _require_session()
    return session.version_info


# --- Execution Control Tools ---

@mcp.tool()
@_tag_errors
def jdb_run(class_name: str = None, args: str = None) -> StopEvent:
    """Start execution of the application's main class.

    Args:
        class_name: Main class to run (usually auto-detected from JVM).
        args: Command-line arguments for the application.
    """
    session = _require_session()
    output = session.run(class_name=class_name, args=args)
    _check_error(output)
    return _parse_stop(output)


@mcp.tool()
@_tag_errors
def jdb_cont() -> StopEvent:
    """Continue execution until the next breakpoint, exception, or program exit."""
    session = _require_session()
    output = session.cont()
    _check_error(output)
    return _parse_stop(output)


@mcp.tool()
@_tag_errors
def jdb_step() -> StopEvent:
    """Step into: execute current line, stepping into method calls."""
    session = _require_session()
    output = session.step()
    _check_error(output)
    return _parse_stop(output)


@mcp.tool()
@_tag_errors
def jdb_next() -> StopEvent:
    """Step over: execute current line, stepping over method calls."""
    session = _require_session()
    output = session.next_()
    _check_error(output)
    return _parse_stop(output)


@mcp.tool()
@_tag_errors
def jdb_step_up() -> StopEvent:
    """Step out: execute until the current method returns to its caller."""
    session = _require_session()
    output = session.step_up()
    _check_error(output)
    return _parse_stop(output)


# --- Breakpoint Tools ---

@mcp.tool()
@_tag_errors
def jdb_breakpoint_set(location: str, thread_id: str = None,
                       suspend_policy: str = None) -> BreakpointInfo:
    """Set a breakpoint at a class:line or class.method location.

    Args:
        location: Breakpoint location. Use "com.example.MyClass:42" for a line
            breakpoint, or "com.example.MyClass.myMethod" (or with arg types:
            "com.example.MyClass.myMethod(int,java.lang.String)") for a method breakpoint.
        thread_id: Only stop in this thread (JDK 13+ only).
        suspend_policy: "go" (don't suspend), "thread" (suspend only event thread),
            or omit for default (suspend all). JDK 13+ only.
    """
    session = _require_session()
    if thread_id or suspend_policy:
        vi = session.version_info
        if vi and not vi.has_stop_modifiers:
            raise ToolError("jdb: thread_id and suspend_policy require JDK 13+ "
                            "(current: JDK %d)" % vi.jdk_major_version)
    output = session.breakpoint_set(location, thread_id=thread_id,
                                    suspend_policy=suspend_policy)
    _check_error(output)
    result = parser.parse_breakpoint_set(output)
    if result is None:
        raise JdbSessionError("Failed to parse breakpoint response: %s" % output)
    return result


@mcp.tool()
@_tag_errors
def jdb_breakpoint_clear(location: str) -> StringResult:
    """Clear a breakpoint at a class:line or class.method location.

    Args:
        location: Same format as jdb_breakpoint_set.
    """
    session = _require_session()
    output = session.breakpoint_clear(location)
    _check_error(output)
    return StringResult(result=output.strip() if output else "Breakpoint cleared.")


@mcp.tool()
@_tag_errors
def jdb_breakpoint_list() -> list[BreakpointInfo]:
    """List all currently set breakpoints."""
    session = _require_session()
    output = session.breakpoint_list()
    return parser.parse_breakpoint_list(output)


@mcp.tool()
@_tag_errors
def jdb_catch(class_pattern: str,
              filter_type: str = "all") -> ExceptionBreakInfo:
    """Break when a specified exception is thrown.

    Args:
        class_pattern: Exception class name or pattern (e.g. "java.lang.NullPointerException",
            "java.io.*"). Use "*" for all exceptions.
        filter_type: "caught", "uncaught", or "all" (default).
    """
    session = _require_session()
    output = session.catch(class_pattern, filter_type=filter_type)
    _check_error(output)
    result = parser.parse_catch(output)
    if result is None:
        raise JdbSessionError("Failed to set exception breakpoint: %s" % output)
    return result


@mcp.tool()
@_tag_errors
def jdb_ignore(class_pattern: str,
               filter_type: str = "all") -> StringResult:
    """Cancel a previous exception breakpoint set with jdb_catch.

    Args:
        class_pattern: Exception class name or pattern to stop catching.
        filter_type: "caught", "uncaught", or "all" (default).
    """
    session = _require_session()
    output = session.ignore(class_pattern, filter_type=filter_type)
    _check_error(output)
    return StringResult(result=output.strip() if output else "Exception breakpoint removed.")


# --- Watchpoint Tools ---

@mcp.tool()
@_tag_errors
def jdb_watch(class_field: str,
              access_type: str = "modification") -> WatchpointInfo:
    """Watch access or modifications to a field.

    Args:
        class_field: Fully qualified field (e.g. "com.example.MyClass.myField").
        access_type: "modification" (default, write only), "access" (read only),
            or "all" (both read and write).
    """
    session = _require_session()
    output = session.watch(class_field, access_type=access_type)
    _check_error(output)
    result = parser.parse_watch(output)
    if result is None:
        raise JdbSessionError("Failed to set watchpoint: %s" % output)
    return result


@mcp.tool()
@_tag_errors
def jdb_unwatch(class_field: str,
                access_type: str = "modification") -> StringResult:
    """Remove a field watchpoint.

    Args:
        class_field: Fully qualified field (e.g. "com.example.MyClass.myField").
        access_type: Must match the type used when the watchpoint was set.
    """
    session = _require_session()
    output = session.unwatch(class_field, access_type=access_type)
    _check_error(output)
    return StringResult(result=output.strip() if output else "Watchpoint removed.")


# --- Thread Management Tools ---

@mcp.tool()
@_tag_errors
def jdb_threads(thread_group: str = None) -> list[ThreadGroupInfo]:
    """List all threads, grouped by thread group.

    Args:
        thread_group: Show only threads in this group. If omitted, shows all.
    """
    session = _require_session()
    output = session.threads(thread_group=thread_group)
    _check_error(output)
    return parser.parse_threads(output)


@mcp.tool()
@_tag_errors
def jdb_thread(thread_id: str) -> StringResult:
    """Set the default thread for subsequent commands.

    Args:
        thread_id: Thread ID (from jdb_threads output, e.g. "0x1a8" or a number).
    """
    session = _require_session()
    output = session.thread(thread_id)
    _check_error(output)
    return StringResult(result=output.strip() if output else "Thread set to %s." % thread_id)


@mcp.tool()
@_tag_errors
def jdb_suspend(thread_ids: list[str] = None) -> StringResult:
    """Suspend threads. If no thread IDs given, suspends all threads.

    Args:
        thread_ids: List of thread IDs to suspend. Omit to suspend all.
    """
    session = _require_session()
    output = session.suspend(thread_ids=thread_ids)
    _check_error(output)
    return StringResult(result=output.strip() if output else "Threads suspended.")


@mcp.tool()
@_tag_errors
def jdb_resume(thread_ids: list[str] = None) -> StringResult:
    """Resume threads. If no thread IDs given, resumes all threads.

    Args:
        thread_ids: List of thread IDs to resume. Omit to resume all.
    """
    session = _require_session()
    output = session.resume(thread_ids=thread_ids)
    _check_error(output)
    return StringResult(result=output.strip() if output else "Threads resumed.")


# --- Stack Navigation Tools ---

@mcp.tool()
@_tag_errors
def jdb_where(thread_id: str = None) -> list[StackFrame]:
    """Get the call stack (stack trace) for a thread.

    Args:
        thread_id: Thread ID. If omitted, shows current thread's stack.
            Use "all" to show all threads' stacks.
    """
    session = _require_session()
    if thread_id and thread_id.lower() == "all":
        output = session.where_all()
    else:
        output = session.where(thread_id=thread_id)
    _check_error(output)
    return parser.parse_where(output)


@mcp.tool()
@_tag_errors
def jdb_up(count: int = 1) -> StringResult:
    """Move up the call stack (toward the caller).

    Args:
        count: Number of frames to move up (default: 1).
    """
    session = _require_session()
    output = session.up(count=count)
    _check_error(output)
    return StringResult(result=output.strip() if output else "Moved up %d frame(s)." % count)


@mcp.tool()
@_tag_errors
def jdb_down(count: int = 1) -> StringResult:
    """Move down the call stack (toward the callee).

    Args:
        count: Number of frames to move down (default: 1).
    """
    session = _require_session()
    output = session.down(count=count)
    _check_error(output)
    return StringResult(result=output.strip() if output else "Moved down %d frame(s)." % count)


# --- Inspection Tools ---

@mcp.tool()
@_tag_errors
def jdb_print(expression: str) -> EvalResult:
    """Print the value of an expression. Supports fields, locals, method calls,
    arithmetic, and new expressions.

    Args:
        expression: Java expression to evaluate (e.g. "myVar", "obj.field",
            "obj.method()", "arr[0]", "i + j").
    """
    session = _require_session()
    output = session.print_(expression)
    _check_error(output)
    return parser.parse_eval(output, expression)


@mcp.tool()
@_tag_errors
def jdb_dump(expression: str) -> EvalResult:
    """Dump an object, showing all its fields (both static and instance).
    More detailed than jdb_print for object inspection.

    Args:
        expression: Expression that evaluates to an object.
    """
    session = _require_session()
    output = session.dump(expression)
    _check_error(output)
    return parser.parse_eval(output, expression)


@mcp.tool()
@_tag_errors
def jdb_eval(expression: str) -> EvalResult:
    """Evaluate a Java expression (alias for jdb_print).

    Args:
        expression: Java expression to evaluate.
    """
    session = _require_session()
    output = session.eval_(expression)
    _check_error(output)
    return parser.parse_eval(output, expression)


@mcp.tool()
@_tag_errors
def jdb_set(lvalue: str, expression: str) -> StringResult:
    """Assign a new value to a variable, field, or array element.

    Args:
        lvalue: Target to assign to (e.g. "myVar", "obj.field", "arr[0]").
        expression: Value expression (e.g. "42", '"hello"', "new Object()").
    """
    session = _require_session()
    output = session.set_(lvalue, expression)
    _check_error(output)
    return StringResult(result=output.strip() if output else "%s set." % lvalue)


@mcp.tool()
@_tag_errors
def jdb_locals() -> list[Variable]:
    """List all local variables and their values in the current stack frame."""
    session = _require_session()
    output = session.locals_()
    _check_error(output)
    return parser.parse_locals(output)


# --- Class Introspection Tools ---

@mcp.tool()
@_tag_errors
def jdb_classes() -> list[str]:
    """List all currently loaded classes in the JVM."""
    session = _require_session()
    output = session.classes()
    _check_error(output)
    return parser.parse_classes(output)


@mcp.tool()
@_tag_errors
def jdb_class_info(class_id: str) -> ClassInfo:
    """Show details of a class (superclass, interfaces, etc.).

    Args:
        class_id: Fully qualified class name (e.g. "com.example.MyClass").
    """
    session = _require_session()
    output = session.class_info(class_id)
    _check_error(output)
    return parser.parse_class_info(output, class_id=class_id)


@mcp.tool()
@_tag_errors
def jdb_methods(class_id: str) -> list[MethodInfo]:
    """List all methods of a class.

    Args:
        class_id: Fully qualified class name.
    """
    session = _require_session()
    output = session.methods(class_id)
    _check_error(output)
    return parser.parse_methods(output, class_name=class_id)


@mcp.tool()
@_tag_errors
def jdb_fields(class_id: str) -> list[FieldInfo]:
    """List all fields of a class.

    Args:
        class_id: Fully qualified class name.
    """
    session = _require_session()
    output = session.fields(class_id)
    _check_error(output)
    return parser.parse_fields(output, class_name=class_id)


# --- Source Tools ---

@mcp.tool()
@_tag_errors
def jdb_list(location: str = None) -> StringResult:
    """List source code around the current execution point or a specific location.

    Args:
        location: Optional line number or method name to list around.
    """
    session = _require_session()
    output = session.list_(location=location)
    _check_error(output)
    return StringResult(result=output if output else "No source available.")


@mcp.tool()
@_tag_errors
def jdb_sourcepath(path: str = None) -> StringResult:
    """Display or change the source path for finding .java source files.

    Args:
        path: New source path (colon-separated directories). If omitted, shows current.
    """
    session = _require_session()
    output = session.sourcepath(path=path)
    _check_error(output)
    return StringResult(result=output.strip() if output else "Source path updated.")


@mcp.tool()
@_tag_errors
def jdb_classpath() -> StringResult:
    """Print the classpath information from the target JVM."""
    session = _require_session()
    output = session.classpath()
    _check_error(output)
    return StringResult(result=output.strip() if output else "No classpath info.")


# --- Concurrency Tools ---

@mcp.tool()
@_tag_errors
def jdb_lock(expression: str) -> LockInfo:
    """Print lock/monitor information for an object (owner, waiting threads).
    Useful for deadlock analysis.

    Args:
        expression: Expression evaluating to an object to inspect.
    """
    session = _require_session()
    output = session.lock(expression)
    _check_error(output)
    return parser.parse_lock_info(output)


@mcp.tool()
@_tag_errors
def jdb_threadlocks(thread_id: str = None) -> ThreadLockInfo:
    """Print lock information for a thread (owned monitors, lock being waited on).
    Useful for deadlock analysis.

    Args:
        thread_id: Thread ID. If omitted, shows current thread's locks.
    """
    session = _require_session()
    output = session.threadlocks(thread_id=thread_id)
    _check_error(output)
    return parser.parse_thread_locks(output, thread_name=thread_id or "current")


# --- Frame Manipulation Tools ---

@mcp.tool()
@_tag_errors
def jdb_pop() -> StringResult:
    """Pop the current stack frame (discard it and return to caller).
    Allows re-executing the calling code with potentially modified state."""
    session = _require_session()
    output = session.pop()
    _check_error(output)
    return StringResult(result=output.strip() if output else "Frame popped.")


@mcp.tool()
@_tag_errors
def jdb_reenter() -> StringResult:
    """Re-enter the current method from the beginning.
    Like pop, but re-executes the current method."""
    session = _require_session()
    output = session.reenter()
    _check_error(output)
    return StringResult(result=output.strip() if output else "Method re-entered.")


# --- Tracing Tools ---

@mcp.tool()
@_tag_errors
def jdb_trace(what: str = "methods", thread: str = None) -> StringResult:
    """Trace method entries and exits.

    Args:
        what: What to trace: "methods" (entries+exits), "method exit" or
            "method exits". Prefix with "go" to not suspend (e.g. "go methods").
        thread: Optional thread ID to restrict tracing to.
    """
    session = _require_session()
    output = session.trace(what=what, thread=thread)
    _check_error(output)
    return StringResult(result=output.strip() if output else "Tracing enabled.")


@mcp.tool()
@_tag_errors
def jdb_untrace() -> StringResult:
    """Stop tracing method entries and exits."""
    session = _require_session()
    output = session.untrace()
    _check_error(output)
    return StringResult(result=output.strip() if output else "Tracing disabled.")


# --- Monitor Tools ---

@mcp.tool()
@_tag_errors
def jdb_monitor(command: str) -> MonitorInfo:
    """Set a command to execute automatically each time the program stops
    (at breakpoints, after steps, etc.). Useful for auto-printing variables.

    Args:
        command: JDB command to execute on each stop (e.g. "locals", "where",
            "print myVar").
    """
    session = _require_session()
    output = session.monitor(command)
    _check_error(output)
    result = parser.parse_monitor_set(output)
    if result is None:
        return MonitorInfo(number=0, command=command)
    return result


@mcp.tool()
@_tag_errors
def jdb_monitor_list() -> list[MonitorInfo]:
    """List all active monitors (commands that auto-execute on stop)."""
    session = _require_session()
    output = session.monitor_list()
    return parser.parse_monitor_list(output)


@mcp.tool()
@_tag_errors
def jdb_unmonitor(monitor_number: int) -> StringResult:
    """Remove a monitor by its number (from jdb_monitor_list).

    Args:
        monitor_number: The monitor number to remove.
    """
    session = _require_session()
    output = session.unmonitor(monitor_number)
    _check_error(output)
    return StringResult(result=output.strip() if output else "Monitor %d removed." % monitor_number)


# --- Configuration Tools ---

@mcp.tool()
@_tag_errors
def jdb_exclude(class_patterns: list[str] = None) -> StringResult:
    """Set or display the step exclusion filter. Excluded classes are skipped
    when stepping. Default excludes java.*, javax.*, sun.*, com.sun.*, jdk.*.

    Args:
        class_patterns: List of class patterns to exclude (e.g. ["java.*", "javax.*"]).
            Use ["none"] to clear the filter. Omit to display current filter.
    """
    session = _require_session()
    output = session.exclude(class_patterns=class_patterns)
    _check_error(output)
    return StringResult(result=output.strip() if output else "Exclusion filter updated.")


def _watch_parent():
    """Background thread: exit when parent process dies.

    anyio.run() overrides SIGTERM handling, so os.kill(SIGTERM) would be
    swallowed. Instead, call _cleanup() directly and use os._exit(0) to
    force a clean exit that bypasses the blocked event loop.
    """
    import threading
    import time

    ppid = os.getppid()

    def _monitor():
        while True:
            time.sleep(2)
            if os.getppid() != ppid:
                _cleanup()
                os._exit(0)

    t = threading.Thread(target=_monitor, daemon=True)
    t.start()


def main():
    _watch_parent()
    mcp.run(transport="stdio")
