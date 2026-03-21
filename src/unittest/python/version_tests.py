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

from karellen_jdb_mcp.version import (
    parse_jdk_major_version, compute_feature_flags, detect_version,
)
from karellen_jdb_mcp.types import VersionInfo


class ParseJdkMajorVersionTests(unittest.TestCase):
    def test_jdk21(self):
        self.assertEqual(parse_jdk_major_version(
            "This is jdb version 21.0.4"), 21)

    def test_jdk17(self):
        self.assertEqual(parse_jdk_major_version(
            "This is jdb version 17.0.12"), 17)

    def test_jdk11(self):
        self.assertEqual(parse_jdk_major_version(
            "This is jdb version 11.0.24"), 11)

    def test_jdk8_old_format(self):
        self.assertEqual(parse_jdk_major_version(
            "This is com.sun.tools.example.debug.tty.TTY version 1.8.0_392"), 8)

    def test_jdk8_with_minor_zero(self):
        self.assertEqual(parse_jdk_major_version(
            "This is jdb version 1.8.0"), 8)

    def test_jdk24(self):
        self.assertEqual(parse_jdk_major_version(
            "This is jdb version 24"), 24)

    def test_jdk9(self):
        self.assertEqual(parse_jdk_major_version(
            "This is jdb version 9.0.4"), 9)

    def test_invalid_version_raises(self):
        with self.assertRaises(ValueError):
            parse_jdk_major_version("no version info here")

    def test_empty_string_raises(self):
        with self.assertRaises(ValueError):
            parse_jdk_major_version("")


class ComputeFeatureFlagsTests(unittest.TestCase):
    def test_jdk8_flags(self):
        flags = compute_feature_flags(8)
        self.assertFalse(flags["has_stop_modifiers"])
        self.assertFalse(flags["has_repeat_command"])
        self.assertFalse(flags["has_threadgroup_reset"])
        self.assertFalse(flags["has_track_all_threads"])

    def test_jdk13_flags(self):
        flags = compute_feature_flags(13)
        self.assertTrue(flags["has_stop_modifiers"])
        self.assertFalse(flags["has_repeat_command"])
        self.assertFalse(flags["has_threadgroup_reset"])
        self.assertFalse(flags["has_track_all_threads"])

    def test_jdk18_flags(self):
        flags = compute_feature_flags(18)
        self.assertTrue(flags["has_stop_modifiers"])
        self.assertTrue(flags["has_repeat_command"])
        self.assertFalse(flags["has_threadgroup_reset"])
        self.assertFalse(flags["has_track_all_threads"])

    def test_jdk19_flags(self):
        flags = compute_feature_flags(19)
        self.assertTrue(flags["has_stop_modifiers"])
        self.assertTrue(flags["has_repeat_command"])
        self.assertTrue(flags["has_threadgroup_reset"])
        self.assertFalse(flags["has_track_all_threads"])

    def test_jdk21_flags(self):
        flags = compute_feature_flags(21)
        self.assertTrue(flags["has_stop_modifiers"])
        self.assertTrue(flags["has_repeat_command"])
        self.assertTrue(flags["has_threadgroup_reset"])
        self.assertTrue(flags["has_track_all_threads"])

    def test_jdk24_flags(self):
        flags = compute_feature_flags(24)
        self.assertTrue(flags["has_stop_modifiers"])
        self.assertTrue(flags["has_repeat_command"])
        self.assertTrue(flags["has_threadgroup_reset"])
        self.assertTrue(flags["has_track_all_threads"])


class DetectVersionTests(unittest.TestCase):
    @patch("karellen_jdb_mcp.version.subprocess.run")
    def test_detect_jdk21(self, mock_run):
        mock_run.return_value = MagicMock(
            stdout="This is jdb version 21.0.4\n",
            stderr="",
        )
        result = detect_version("/usr/bin/jdb")
        self.assertIsInstance(result, VersionInfo)
        self.assertEqual(result.jdk_major_version, 21)
        self.assertTrue(result.has_stop_modifiers)
        self.assertTrue(result.has_track_all_threads)
        mock_run.assert_called_once_with(
            ["/usr/bin/jdb", "-version"],
            capture_output=True, text=True, timeout=10,
        )

    @patch("karellen_jdb_mcp.version.subprocess.run")
    def test_detect_jdk8(self, mock_run):
        mock_run.return_value = MagicMock(
            stdout="This is com.sun.tools.example.debug.tty.TTY version 1.8.0_392\n",
            stderr="",
        )
        result = detect_version()
        self.assertEqual(result.jdk_major_version, 8)
        self.assertFalse(result.has_stop_modifiers)
        self.assertFalse(result.has_repeat_command)
        self.assertFalse(result.has_track_all_threads)

    @patch("karellen_jdb_mcp.version.subprocess.run")
    def test_detect_version_from_stderr(self, mock_run):
        mock_run.return_value = MagicMock(
            stdout="",
            stderr="This is jdb version 17.0.12",
        )
        result = detect_version()
        self.assertEqual(result.jdk_major_version, 17)

    @patch("karellen_jdb_mcp.version.subprocess.run")
    def test_detect_empty_output_raises(self, mock_run):
        mock_run.return_value = MagicMock(stdout="", stderr="")
        with self.assertRaises(ValueError):
            detect_version()

    @patch("karellen_jdb_mcp.version.subprocess.run")
    def test_detect_not_found_raises(self, mock_run):
        mock_run.side_effect = FileNotFoundError("jdb not found")
        with self.assertRaises(FileNotFoundError):
            detect_version("/nonexistent/jdb")
