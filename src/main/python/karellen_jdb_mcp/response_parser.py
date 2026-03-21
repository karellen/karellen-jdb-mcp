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

"""Parse JDB text output into structured domain types."""

import re

from karellen_jdb_mcp.types import (
    BreakpointInfo, ExceptionBreakInfo, WatchpointInfo,
    StackFrame, ThreadInfo, ThreadGroupInfo, Variable,
    ClassInfo, MethodInfo, FieldInfo, LockInfo, ThreadLockInfo,
    MonitorInfo, EvalResult, StopEvent,
)


def is_error(output):
    """Check if JDB output contains error lines.

    JDB error lines look like: '** command not valid', '** Invalid expression'.
    They start with '** ' and do NOT end with '**' (which would be informational
    headers like '** methods list **'). Lines that are purely decorative markers
    (starting and ending with **) are not errors.
    """
    for line in output.splitlines():
        stripped = line.strip()
        if stripped.startswith("** ") and not stripped.endswith("**"):
            return True
    return False


def get_error_message(output):
    """Extract error message from JDB output."""
    for line in output.splitlines():
        stripped = line.strip()
        if stripped.startswith("** ") and not stripped.endswith("**"):
            return stripped.lstrip("* ").strip()
    return output.strip() if output.strip() else "Unknown error"


# --- Stop Event Parsing ---

# "Breakpoint hit: "thread=main", com.example.Main.method(), line=42 bci=0"
# "Step completed: "thread=main", com.example.Main.method(), line=43 bci=5"
# "Exception occurred: java.lang.NullPointerException (uncaught)"
#   "thread=main", com.example.Main.method(), line=42 bci=0
STOP_HIT_RE = re.compile(
    r'^(Breakpoint hit|Step completed|Method (entered|exited)):\s+'
    r'"thread=([^"]+)",\s+'
    r'([\w.$<>]+)\.([\w$<>]+)\(\),\s+'
    r'line=(\d+)\s+bci=(\d+)',
    re.MULTILINE,
)

EXCEPTION_RE = re.compile(
    r'^Exception occurred:\s+([\w.$]+)\s+\((\w+)\)',
    re.MULTILINE,
)

EXCEPTION_LOCATION_RE = re.compile(
    r'^\s+"thread=([^"]+)",\s+'
    r'([\w.$<>]+)\.([\w$<>]+)\(\),\s+'
    r'line=(\d+)\s+bci=(\d+)',
    re.MULTILINE,
)

APPLICATION_EXITED_RE = re.compile(
    r'^The application (exited|has been disconnected)',
    re.MULTILINE,
)


def parse_stop_event(output):
    """Parse a JDB stop event from command output.

    Returns a StopEvent or None if no stop event is found.
    """
    m = STOP_HIT_RE.search(output)
    if m:
        reason = m.group(1).lower().replace(" ", "_")
        return StopEvent(
            reason=reason,
            thread=m.group(3),
            class_name=m.group(4),
            method=m.group(5),
            line=int(m.group(6)),
            location="%s.%s:%d" % (m.group(4), m.group(5), int(m.group(6))),
        )

    m = EXCEPTION_RE.search(output)
    if m:
        event = StopEvent(
            reason="exception",
            exception_type=m.group(1),
        )
        loc = EXCEPTION_LOCATION_RE.search(output)
        if loc:
            event.thread = loc.group(1)
            event.class_name = loc.group(2)
            event.method = loc.group(3)
            event.line = int(loc.group(4))
            event.location = "%s.%s:%d" % (loc.group(2), loc.group(3), int(loc.group(4)))
        return event

    m = APPLICATION_EXITED_RE.search(output)
    if m:
        return StopEvent(reason="application_exited")

    return None


# --- Stack Trace Parsing ---

# "  [1] com.example.Main.method (Main.java:42)"
# "  [2] com.example.Main.main (Main.java:10)"
# "  [3] java.lang.Thread.sleep (native method)"
FRAME_RE = re.compile(
    r'^\s*\[(\d+)\]\s+'
    r'([\w.$]+)\.([\w$<>]+)\s+'
    r'\(([^)]*)\)',
    re.MULTILINE,
)


def parse_where(output):
    """Parse 'where' command output into a list of StackFrame."""
    frames = []
    for m in FRAME_RE.finditer(output):
        index = int(m.group(1))
        class_name = m.group(2)
        method = m.group(3)
        source_info = m.group(4)

        native = source_info.lower() == "native method"
        source_file = None
        line = None
        bci = None

        if not native:
            # "Main.java:42" or "Main.java:42 bci=10" or just "Main.java"
            parts = source_info.split(",")
            file_line = parts[0].strip()
            if ":" in file_line:
                file_part, line_part = file_line.rsplit(":", 1)
                source_file = file_part.strip()
                try:
                    line = int(line_part.strip())
                except ValueError:
                    source_file = file_line
            else:
                source_file = file_line if file_line else None

            for part in parts[1:]:
                part = part.strip()
                if part.startswith("bci="):
                    try:
                        bci = int(part[4:])
                    except ValueError:
                        pass

        frames.append(StackFrame(
            index=index,
            class_name=class_name,
            method=method,
            line=line,
            native=native,
            source_file=source_file,
            bytecode_index=bci,
        ))
    return frames


# --- Thread Listing Parsing ---

# "Group system:"
# "  (java.lang.ref.Reference$ReferenceHandler)0x1a7 Reference Handler cond. waiting"
# "Group main:"
# "  (java.lang.Thread)0x1a8 main                          running"
GROUP_RE = re.compile(r'^Group\s+(.+):', re.MULTILINE)
THREAD_RE = re.compile(
    r'^\s+\(([^)]+)\)(0x[\da-fA-F]+)\s+(.*?)\s+'
    r'(running|sleeping|waiting|cond\.\s*waiting|zombie|not started|monitor|unknown)',
    re.MULTILINE,
)


def parse_threads(output):
    """Parse 'threads' command output into a list of ThreadGroupInfo."""
    groups = []
    group_positions = [(m.start(), m.group(1)) for m in GROUP_RE.finditer(output)]

    if not group_positions:
        threads = _parse_thread_lines(output)
        if threads:
            groups.append(ThreadGroupInfo(name="default", threads=threads))
        return groups

    for i, (pos, name) in enumerate(group_positions):
        end = group_positions[i + 1][0] if i + 1 < len(group_positions) else len(output)
        section = output[pos:end]
        threads = _parse_thread_lines(section)
        groups.append(ThreadGroupInfo(name=name, threads=threads))

    return groups


def _parse_thread_lines(text):
    """Parse individual thread lines from a section of 'threads' output."""
    threads = []
    for m in THREAD_RE.finditer(text):
        type_name = m.group(1)
        thread_id = m.group(2)
        name = m.group(3).strip()
        status = m.group(4).strip()
        threads.append(ThreadInfo(
            name=name,
            id=thread_id,
            status=status,
            thread_class=type_name,
        ))
    return threads


# --- Locals Parsing ---

# "Method arguments:"
# "  this = instance of com.example.Main (id=1001)"
# "  arg0 = "hello""
# "Local variables:"
# "  x = 42"
# "  name = "world""
LOCAL_VAR_RE = re.compile(r'^\s+([\w$]+)\s+=\s+(.*)', re.MULTILINE)


def parse_locals(output):
    """Parse 'locals' command output into a list of Variable."""
    if "No local variables" in output or "is not a valid" in output:
        return []

    variables = []
    for m in LOCAL_VAR_RE.finditer(output):
        name = m.group(1)
        value = m.group(2).strip()
        var_type = None
        if value.startswith("instance of "):
            type_match = re.match(r'instance of ([\w.$]+)', value)
            if type_match:
                var_type = type_match.group(1)
        variables.append(Variable(name=name, value=value, type=var_type))
    return variables


# --- Breakpoint Parsing ---

# "Set breakpoint com.example.Main:42"
# "Deferring breakpoint com.example.Main:42.\nIt will be set after the class is loaded."
# "Set deferred breakpoint com.example.Main.method"
BREAKPOINT_SET_RE = re.compile(
    r'^(?:Set\s+(?:deferred\s+)?|Deferring\s+)breakpoint\s+'
    r'([\w.$]+(?::(\d+)|\.[\w$<>]+(?:\([\w.$,\s]*\))?))',
    re.MULTILINE,
)


def parse_breakpoint_set(output):
    """Parse breakpoint set response."""
    m = BREAKPOINT_SET_RE.search(output)
    if m:
        location = m.group(1)
        deferred = "Deferring" in output or "deferred" in output
        line = int(m.group(2)) if m.group(2) else None

        class_name = None
        method = None
        if ":" in location:
            class_name = location.split(":")[0]
        elif "." in location:
            parts = location.rsplit(".", 1)
            if parts[1][0].islower() or parts[1].startswith("<"):
                class_name = parts[0]
                method = parts[1].split("(")[0]
            else:
                class_name = location

        bp_type = "deferred breakpoint" if deferred else "breakpoint"
        return BreakpointInfo(
            location=location,
            type=bp_type,
            class_name=class_name,
            method=method,
            line=line,
        )

    if is_error(output):
        return None
    return BreakpointInfo(location=output.strip(), type="breakpoint")


# "Breakpoints set:"
# "  breakpoint com.example.Main:42"
# "  breakpoint com.example.Main.method"
# Or: "No breakpoints set."
BREAKPOINT_LIST_RE = re.compile(
    r'^\s+breakpoint\s+([\w.$]+(?::(\d+)|\.[\w$<>]+(?:\([\w.$,\s]*\))?))',
    re.MULTILINE,
)


def parse_breakpoint_list(output):
    """Parse breakpoint list (from 'clear' or 'stop' with no args)."""
    if "No breakpoints set" in output:
        return []

    breakpoints = []
    for m in BREAKPOINT_LIST_RE.finditer(output):
        location = m.group(1)
        line = int(m.group(2)) if m.group(2) else None
        class_name = None
        method = None
        if ":" in location:
            class_name = location.split(":")[0]
        elif "." in location:
            parts = location.rsplit(".", 1)
            if parts[1][0].islower() or parts[1].startswith("<"):
                class_name = parts[0]
                method = parts[1].split("(")[0]

        breakpoints.append(BreakpointInfo(
            location=location,
            class_name=class_name,
            method=method,
            line=line,
        ))
    return breakpoints


# --- Catch/Ignore Parsing ---

CATCH_SET_RE = re.compile(
    r'^Set\s+(?:(uncaught|caught|all)\s+)?([\w.$*]+)',
    re.MULTILINE,
)


def parse_catch(output):
    """Parse 'catch' command response."""
    m = CATCH_SET_RE.search(output)
    if m:
        filter_type = m.group(1) or "all"
        class_pattern = m.group(2)
        return ExceptionBreakInfo(class_pattern=class_pattern, filter_type=filter_type)
    if is_error(output):
        return None
    return ExceptionBreakInfo(class_pattern=output.strip())


# --- Watch Parsing ---

WATCH_SET_RE = re.compile(
    r'^Set\s+(?:(access|all)\s+)?watch(?:point)?\s+([\w.$]+)\.([\w$]+)',
    re.MULTILINE,
)


def parse_watch(output):
    """Parse 'watch' command response."""
    m = WATCH_SET_RE.search(output)
    if m:
        access_type = m.group(1) or "modification"
        return WatchpointInfo(
            class_name=m.group(2),
            field_name=m.group(3),
            access_type=access_type,
        )
    if is_error(output):
        return None
    return WatchpointInfo(class_name="", field_name=output.strip())


# --- Eval/Print/Dump Parsing ---

def parse_eval(output, expression):
    """Parse print/eval/dump output."""
    lines = output.strip().splitlines()
    if not lines:
        return EvalResult(expression=expression, value="")

    first_line = lines[0].strip()
    if " = " in first_line:
        _, _, value = first_line.partition(" = ")
        if len(lines) > 1:
            value = value + "\n" + "\n".join(lines[1:])
        return EvalResult(expression=expression, value=value.strip())

    return EvalResult(expression=expression, value=output.strip())


# --- Class Introspection Parsing ---

# "Class: com.example.Main"
# "  extends: java.lang.Object"
# "  implements: java.io.Serializable"
# or lines like:
# "com.example.Main extends java.lang.Object implements java.io.Serializable"
CLASS_EXTENDS_RE = re.compile(r'extends\s+([\w.$]+)')
CLASS_IMPLEMENTS_RE = re.compile(r'implements\s+([\w.$,\s]+)')
CLASS_IS_INTERFACE_RE = re.compile(r'\binterface\b')


def parse_class_info(output, class_id=""):
    """Parse 'class' command output."""
    superclass = None
    interfaces = []
    is_interface = False

    m = CLASS_EXTENDS_RE.search(output)
    if m:
        superclass = m.group(1)

    m = CLASS_IMPLEMENTS_RE.search(output)
    if m:
        interfaces = [i.strip() for i in m.group(1).split(",") if i.strip()]

    if CLASS_IS_INTERFACE_RE.search(output):
        is_interface = True

    return ClassInfo(
        name=class_id,
        superclass=superclass,
        interfaces=interfaces,
        is_interface=is_interface,
    )


# "** methods list **"
# "  void main(java.lang.String[])"
# "  int getValue()"
# "  <init>()"
METHOD_RE = re.compile(
    r'^\s+([\w.$<>\[\]]+(?:\s+[\w.$<>\[\]]+)*)\s*\(([\w.$,\s\[\]]*)\)',
    re.MULTILINE,
)


def parse_methods(output, class_name=""):
    """Parse 'methods' command output."""
    methods = []
    for m in METHOD_RE.finditer(output):
        full_name = m.group(1).strip()
        params = m.group(2).strip()
        signature = "%s(%s)" % (full_name, params)
        name = full_name.split()[-1] if " " in full_name else full_name
        methods.append(MethodInfo(
            name=name,
            signature=signature,
            class_name=class_name,
        ))
    return methods


# "** fields list **"
# "  int x"
# "  static java.lang.String name"
# "  java.util.List items"
FIELD_RE = re.compile(
    r'^\s+(static\s+)?([\w.$\[\]]+)\s+([\w$]+)\s*$',
    re.MULTILINE,
)


def parse_fields(output, class_name=""):
    """Parse 'fields' command output."""
    fields = []
    for m in FIELD_RE.finditer(output):
        is_static = m.group(1) is not None
        field_type = m.group(2)
        field_name = m.group(3)
        fields.append(FieldInfo(
            name=field_name,
            type=field_type,
            class_name=class_name,
            is_static=is_static,
        ))
    return fields


# --- Lock Info Parsing ---

# "Monitor information for com.example.MyObj@0x1a8:"
# "  Owner: main"
# "  Waiting thread: Thread-1"
# "  Waiting thread: Thread-2"
LOCK_OWNER_RE = re.compile(r'Owner:\s+(.+)', re.MULTILINE)
LOCK_WAITING_RE = re.compile(r'Waiting thread:\s+(.+)', re.MULTILINE)


def parse_lock_info(output):
    """Parse 'lock' command output."""
    owner = None
    waiting = []

    m = LOCK_OWNER_RE.search(output)
    if m:
        owner = m.group(1).strip()

    for m in LOCK_WAITING_RE.finditer(output):
        waiting.append(m.group(1).strip())

    return LockInfo(
        object_description=output.splitlines()[0].strip() if output.strip() else "",
        owner_thread=owner,
        waiting_threads=waiting,
    )


# --- Thread Lock Info Parsing ---

# "Monitor information for thread main:"
# "  Owned monitor: instance of java.lang.Object(id=1002)"
# "  Waiting for monitor: instance of java.lang.Object(id=1003)"
OWNED_MONITOR_RE = re.compile(r'Owned monitor:\s+(.+)', re.MULTILINE)
WAITING_FOR_RE = re.compile(r'Waiting for monitor:\s+(.+)', re.MULTILINE)


def parse_thread_locks(output, thread_name=""):
    """Parse 'threadlocks' command output."""
    owned = []
    waiting_on = None

    for m in OWNED_MONITOR_RE.finditer(output):
        owned.append(m.group(1).strip())

    m = WAITING_FOR_RE.search(output)
    if m:
        waiting_on = m.group(1).strip()

    return ThreadLockInfo(
        thread_name=thread_name,
        owned_monitors=owned,
        waiting_on=waiting_on,
    )


# --- Monitor Parsing ---

# "Set monitor 1: locals"
MONITOR_SET_RE = re.compile(r'Set monitor\s+(\d+):\s+(.+)')

# "  1: locals"
# "  2: where"
MONITOR_LIST_RE = re.compile(r'^\s*(\d+):\s+(.+)', re.MULTILINE)


def parse_monitor_set(output):
    """Parse 'monitor' command response."""
    m = MONITOR_SET_RE.search(output)
    if m:
        return MonitorInfo(number=int(m.group(1)), command=m.group(2).strip())
    return None


def parse_monitor_list(output):
    """Parse monitor list output."""
    monitors = []
    for m in MONITOR_LIST_RE.finditer(output):
        monitors.append(MonitorInfo(
            number=int(m.group(1)),
            command=m.group(2).strip(),
        ))
    return monitors


# --- Classes Listing ---

def parse_classes(output):
    """Parse 'classes' command output into list of class names."""
    classes = []
    for line in output.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("**"):
            continue
        if stripped.startswith("(") or stripped.startswith("Group"):
            continue
        classes.append(stripped)
    return classes
