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

from dataclasses import dataclass, field
from typing import Optional, List


@dataclass
class BreakpointInfo:
    location: str
    type: str = "breakpoint"
    enabled: bool = True
    class_name: Optional[str] = None
    method: Optional[str] = None
    line: Optional[int] = None
    thread_filter: Optional[str] = None
    suspend_policy: Optional[str] = None


@dataclass
class ExceptionBreakInfo:
    class_pattern: str
    filter_type: str = "all"


@dataclass
class WatchpointInfo:
    class_name: str
    field_name: str
    access_type: str = "modification"


@dataclass
class StackFrame:
    index: int
    class_name: str
    method: str
    line: Optional[int] = None
    native: bool = False
    source_file: Optional[str] = None
    bytecode_index: Optional[int] = None


@dataclass
class ThreadInfo:
    name: str
    id: Optional[str] = None
    status: Optional[str] = None
    is_daemon: bool = False
    thread_class: Optional[str] = None
    priority: Optional[int] = None
    current: bool = False


@dataclass
class ThreadGroupInfo:
    name: str
    threads: List[ThreadInfo] = field(default_factory=list)
    subgroups: List[str] = field(default_factory=list)


@dataclass
class Variable:
    name: str
    value: str
    type: Optional[str] = None


@dataclass
class ClassInfo:
    name: str
    superclass: Optional[str] = None
    interfaces: List[str] = field(default_factory=list)
    class_loader: Optional[str] = None
    is_interface: bool = False


@dataclass
class MethodInfo:
    name: str
    signature: str
    class_name: Optional[str] = None


@dataclass
class FieldInfo:
    name: str
    type: str
    class_name: Optional[str] = None
    is_static: bool = False


@dataclass
class LockInfo:
    object_description: str
    owner_thread: Optional[str] = None
    waiting_threads: List[str] = field(default_factory=list)


@dataclass
class ThreadLockInfo:
    thread_name: str
    owned_monitors: List[str] = field(default_factory=list)
    waiting_on: Optional[str] = None


@dataclass
class MonitorInfo:
    number: int
    command: str


@dataclass
class EvalResult:
    expression: str
    value: str


@dataclass
class StopEvent:
    reason: str
    thread: Optional[str] = None
    class_name: Optional[str] = None
    method: Optional[str] = None
    line: Optional[int] = None
    exception_type: Optional[str] = None
    location: Optional[str] = None


@dataclass
class ConnectStatus:
    host: str
    port: int
    message: str
    jdb_version: Optional[str] = None
    jdk_major_version: Optional[int] = None


@dataclass
class SessionInfo:
    port: int
    connected: bool
    jdb_version: Optional[str] = None
    jdk_major_version: Optional[int] = None


@dataclass
class StringResult:
    result: str


@dataclass
class LaunchResult:
    port: int
    pid: int
    command: List[str]


@dataclass
class ProcessStatus:
    port: int
    pid: int
    command: List[str]
    running: bool
    exit_code: Optional[int] = None


@dataclass
class VersionInfo:
    jdb_version_string: str
    jdk_major_version: int
    has_stop_modifiers: bool
    has_repeat_command: bool
    has_track_all_threads: bool
    has_threadgroup_reset: bool
