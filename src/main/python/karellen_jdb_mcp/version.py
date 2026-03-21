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

"""JDB version detection and feature flags."""

import re
import subprocess

from karellen_jdb_mcp.types import VersionInfo

# JDK version string examples:
# "This is jdb version 21.0.4"  (JDK 9+)
# "This is com.sun.tools.example.debug.tty.TTY version 1.8.0_392"  (JDK 8)
VERSION_RE = re.compile(r'version\s+(\d+)(?:\.(\d+))?')


def parse_jdk_major_version(version_string):
    """Extract JDK major version number from jdb -version output.

    Returns the major version as an integer (e.g. 8, 11, 17, 21).
    JDK 8 and earlier use the 1.X format, so 1.8.0 returns 8.
    """
    m = VERSION_RE.search(version_string)
    if m is None:
        raise ValueError("Cannot parse JDK version from: %r" % version_string)
    major = int(m.group(1))
    if major == 1 and m.group(2):
        return int(m.group(2))
    return major


def compute_feature_flags(jdk_major_version):
    """Compute feature flags based on JDK major version.

    Returns a dict with boolean feature flags.
    """
    return {
        "has_stop_modifiers": jdk_major_version >= 13,
        "has_repeat_command": jdk_major_version >= 18,
        "has_threadgroup_reset": jdk_major_version >= 19,
        "has_track_all_threads": jdk_major_version >= 20,
    }


def detect_version(jdb_path="jdb"):
    """Detect JDB version by running jdb -version.

    Args:
        jdb_path: Path to the jdb executable.

    Returns:
        VersionInfo with version string, major version, and feature flags.

    Raises:
        FileNotFoundError: If jdb is not found on PATH.
        subprocess.TimeoutExpired: If jdb -version hangs.
        ValueError: If the version output cannot be parsed.
    """
    result = subprocess.run(
        [jdb_path, "-version"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    output = result.stdout.strip() or result.stderr.strip()
    if not output:
        raise ValueError("jdb -version produced no output")

    jdk_major = parse_jdk_major_version(output)
    flags = compute_feature_flags(jdk_major)

    return VersionInfo(
        jdb_version_string=output,
        jdk_major_version=jdk_major,
        **flags,
    )
