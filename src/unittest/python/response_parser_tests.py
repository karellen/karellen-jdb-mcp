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

from karellen_jdb_mcp import response_parser as parser


class IsErrorTests(unittest.TestCase):
    def test_error_line(self):
        self.assertTrue(parser.is_error("** command not valid\n"))

    def test_error_with_leading_spaces(self):
        self.assertTrue(parser.is_error("  ** error occurred"))

    def test_no_error(self):
        self.assertFalse(parser.is_error("Breakpoint hit: main"))

    def test_empty_string(self):
        self.assertFalse(parser.is_error(""))

    def test_informational_star_line_not_error(self):
        self.assertFalse(parser.is_error("** methods list **"))

    def test_decorative_header_not_error(self):
        self.assertFalse(parser.is_error("** Thread-1 breakpoint hit **"))


class GetErrorMessageTests(unittest.TestCase):
    def test_extracts_message(self):
        msg = parser.get_error_message("** command 'foo' is not valid\n")
        self.assertEqual(msg, "command 'foo' is not valid")

    def test_multiple_error_lines_returns_first(self):
        output = "** first error\n** second error\n"
        msg = parser.get_error_message(output)
        self.assertEqual(msg, "first error")

    def test_no_error_returns_output(self):
        msg = parser.get_error_message("some output")
        self.assertEqual(msg, "some output")

    def test_empty_returns_unknown(self):
        msg = parser.get_error_message("")
        self.assertEqual(msg, "Unknown error")


class ParseStopEventTests(unittest.TestCase):
    def test_breakpoint_hit(self):
        output = ('Breakpoint hit: "thread=main", com.example.Main.doSomething(), '
                  'line=42 bci=0\n')
        event = parser.parse_stop_event(output)
        self.assertIsNotNone(event)
        self.assertEqual(event.reason, "breakpoint_hit")
        self.assertEqual(event.thread, "main")
        self.assertEqual(event.class_name, "com.example.Main")
        self.assertEqual(event.method, "doSomething")
        self.assertEqual(event.line, 42)
        self.assertEqual(event.location, "com.example.Main.doSomething:42")

    def test_step_completed(self):
        output = ('Step completed: "thread=main", com.example.Main.run(), '
                  'line=55 bci=10\n')
        event = parser.parse_stop_event(output)
        self.assertIsNotNone(event)
        self.assertEqual(event.reason, "step_completed")
        self.assertEqual(event.line, 55)

    def test_exception_with_location(self):
        output = ('Exception occurred: java.lang.NullPointerException (uncaught)\n'
                  '  "thread=main", com.example.Main.process(), line=100 bci=5\n')
        event = parser.parse_stop_event(output)
        self.assertIsNotNone(event)
        self.assertEqual(event.reason, "exception")
        self.assertEqual(event.exception_type, "java.lang.NullPointerException")
        self.assertEqual(event.thread, "main")
        self.assertEqual(event.class_name, "com.example.Main")
        self.assertEqual(event.method, "process")
        self.assertEqual(event.line, 100)

    def test_exception_without_location(self):
        output = 'Exception occurred: java.io.IOException (caught)\n'
        event = parser.parse_stop_event(output)
        self.assertIsNotNone(event)
        self.assertEqual(event.reason, "exception")
        self.assertEqual(event.exception_type, "java.io.IOException")
        self.assertIsNone(event.thread)

    def test_application_exited(self):
        output = 'The application exited\n'
        event = parser.parse_stop_event(output)
        self.assertIsNotNone(event)
        self.assertEqual(event.reason, "application_exited")

    def test_application_disconnected(self):
        output = 'The application has been disconnected\n'
        event = parser.parse_stop_event(output)
        self.assertIsNotNone(event)
        self.assertEqual(event.reason, "application_exited")

    def test_no_event(self):
        output = 'some random output\n'
        event = parser.parse_stop_event(output)
        self.assertIsNone(event)

    def test_method_entered(self):
        output = ('Method entered: "thread=main", com.example.Main.init(), '
                  'line=10 bci=0\n')
        event = parser.parse_stop_event(output)
        self.assertIsNotNone(event)
        self.assertEqual(event.reason, "method_entered")


class ParseWhereTests(unittest.TestCase):
    def test_multiple_frames(self):
        output = ('  [1] com.example.Main.doSomething (Main.java:42)\n'
                  '  [2] com.example.Main.main (Main.java:10)\n')
        frames = parser.parse_where(output)
        self.assertEqual(len(frames), 2)
        self.assertEqual(frames[0].index, 1)
        self.assertEqual(frames[0].class_name, "com.example.Main")
        self.assertEqual(frames[0].method, "doSomething")
        self.assertEqual(frames[0].source_file, "Main.java")
        self.assertEqual(frames[0].line, 42)
        self.assertFalse(frames[0].native)
        self.assertEqual(frames[1].index, 2)
        self.assertEqual(frames[1].line, 10)

    def test_native_method(self):
        output = '  [1] java.lang.Thread.sleep (native method)\n'
        frames = parser.parse_where(output)
        self.assertEqual(len(frames), 1)
        self.assertTrue(frames[0].native)
        self.assertIsNone(frames[0].line)

    def test_empty_output(self):
        frames = parser.parse_where("")
        self.assertEqual(len(frames), 0)

    def test_frame_without_line(self):
        output = '  [1] com.example.Main.doSomething (Main.java)\n'
        frames = parser.parse_where(output)
        self.assertEqual(len(frames), 1)
        self.assertEqual(frames[0].source_file, "Main.java")
        self.assertIsNone(frames[0].line)


class ParseThreadsTests(unittest.TestCase):
    def test_grouped_threads(self):
        output = ('Group system:\n'
                  '  (java.lang.ref.Reference$ReferenceHandler)0x1a7 '
                  'Reference Handler cond. waiting\n'
                  'Group main:\n'
                  '  (java.lang.Thread)0x1a8 main running\n'
                  '  (java.lang.Thread)0x1a9 worker sleeping\n')
        groups = parser.parse_threads(output)
        self.assertEqual(len(groups), 2)
        self.assertEqual(groups[0].name, "system")
        self.assertEqual(len(groups[0].threads), 1)
        self.assertEqual(groups[0].threads[0].name, "Reference Handler")
        self.assertEqual(groups[0].threads[0].status, "cond. waiting")
        self.assertEqual(groups[1].name, "main")
        self.assertEqual(len(groups[1].threads), 2)
        self.assertEqual(groups[1].threads[0].name, "main")
        self.assertEqual(groups[1].threads[0].status, "running")
        self.assertEqual(groups[1].threads[1].name, "worker")

    def test_empty_output(self):
        groups = parser.parse_threads("")
        self.assertEqual(len(groups), 0)


class ParseLocalsTests(unittest.TestCase):
    def test_multiple_locals(self):
        output = ('Method arguments:\n'
                  '  this = instance of com.example.Main (id=1001)\n'
                  '  arg0 = "hello"\n'
                  'Local variables:\n'
                  '  x = 42\n'
                  '  name = "world"\n')
        variables = parser.parse_locals(output)
        self.assertGreaterEqual(len(variables), 4)
        names = [v.name for v in variables]
        self.assertIn("x", names)
        self.assertIn("name", names)

    def test_no_locals(self):
        output = 'No local variables\n'
        variables = parser.parse_locals(output)
        self.assertEqual(len(variables), 0)

    def test_instance_type_detection(self):
        output = '  obj = instance of com.example.Foo (id=1002)\n'
        variables = parser.parse_locals(output)
        self.assertEqual(len(variables), 1)
        self.assertEqual(variables[0].name, "obj")
        self.assertEqual(variables[0].type, "com.example.Foo")


class ParseBreakpointSetTests(unittest.TestCase):
    def test_set_line_breakpoint(self):
        output = 'Set breakpoint com.example.Main:42\n'
        bp = parser.parse_breakpoint_set(output)
        self.assertIsNotNone(bp)
        self.assertEqual(bp.location, "com.example.Main:42")
        self.assertEqual(bp.class_name, "com.example.Main")
        self.assertEqual(bp.line, 42)
        self.assertEqual(bp.type, "breakpoint")

    def test_deferred_breakpoint(self):
        output = ('Deferring breakpoint com.example.MyClass:10.\n'
                  'It will be set after the class is loaded.\n')
        bp = parser.parse_breakpoint_set(output)
        self.assertIsNotNone(bp)
        self.assertEqual(bp.type, "deferred breakpoint")
        self.assertEqual(bp.class_name, "com.example.MyClass")
        self.assertEqual(bp.line, 10)

    def test_method_breakpoint(self):
        output = 'Set breakpoint com.example.Main.myMethod\n'
        bp = parser.parse_breakpoint_set(output)
        self.assertIsNotNone(bp)
        self.assertEqual(bp.class_name, "com.example.Main")
        self.assertEqual(bp.method, "myMethod")
        self.assertIsNone(bp.line)

    def test_error_returns_none(self):
        output = '** Invalid location\n'
        bp = parser.parse_breakpoint_set(output)
        self.assertIsNone(bp)


class ParseBreakpointListTests(unittest.TestCase):
    def test_multiple_breakpoints(self):
        output = ('Breakpoints set:\n'
                  '  breakpoint com.example.Main:42\n'
                  '  breakpoint com.example.Main.method\n')
        bps = parser.parse_breakpoint_list(output)
        self.assertEqual(len(bps), 2)
        self.assertEqual(bps[0].location, "com.example.Main:42")
        self.assertEqual(bps[0].line, 42)
        self.assertEqual(bps[1].location, "com.example.Main.method")

    def test_no_breakpoints(self):
        output = 'No breakpoints set.\n'
        bps = parser.parse_breakpoint_list(output)
        self.assertEqual(len(bps), 0)


class ParseCatchTests(unittest.TestCase):
    def test_catch_all(self):
        output = 'Set all java.lang.NullPointerException\n'
        result = parser.parse_catch(output)
        self.assertIsNotNone(result)
        self.assertEqual(result.class_pattern, "java.lang.NullPointerException")
        self.assertEqual(result.filter_type, "all")

    def test_catch_uncaught(self):
        output = 'Set uncaught java.io.IOException\n'
        result = parser.parse_catch(output)
        self.assertIsNotNone(result)
        self.assertEqual(result.filter_type, "uncaught")

    def test_error_returns_none(self):
        output = '** Unknown class\n'
        result = parser.parse_catch(output)
        self.assertIsNone(result)


class ParseWatchTests(unittest.TestCase):
    def test_modification_watch(self):
        output = 'Set watch com.example.Main.counter\n'
        result = parser.parse_watch(output)
        self.assertIsNotNone(result)
        self.assertEqual(result.class_name, "com.example.Main")
        self.assertEqual(result.field_name, "counter")
        self.assertEqual(result.access_type, "modification")

    def test_access_watch(self):
        output = 'Set access watch com.example.Main.counter\n'
        result = parser.parse_watch(output)
        self.assertIsNotNone(result)
        self.assertEqual(result.access_type, "access")

    def test_error_returns_none(self):
        output = '** Field not found\n'
        result = parser.parse_watch(output)
        self.assertIsNone(result)


class ParseEvalTests(unittest.TestCase):
    def test_simple_value(self):
        output = '  myVar = 42\n'
        result = parser.parse_eval(output, "myVar")
        self.assertEqual(result.expression, "myVar")
        self.assertEqual(result.value, "42")

    def test_string_value(self):
        output = '  name = "hello world"\n'
        result = parser.parse_eval(output, "name")
        self.assertEqual(result.value, '"hello world"')

    def test_multiline_dump(self):
        output = ('  obj = {\n'
                  '    field1: 42\n'
                  '    field2: "hello"\n'
                  '  }\n')
        result = parser.parse_eval(output, "obj")
        self.assertIn("field1", result.value)
        self.assertIn("field2", result.value)

    def test_no_equals(self):
        output = 'some raw value\n'
        result = parser.parse_eval(output, "expr")
        self.assertEqual(result.expression, "expr")
        self.assertEqual(result.value, "some raw value")


class ParseClassInfoTests(unittest.TestCase):
    def test_with_extends_and_implements(self):
        output = ('Class: com.example.Main extends java.lang.Object '
                  'implements java.io.Serializable, java.lang.Comparable\n')
        info = parser.parse_class_info(output, "com.example.Main")
        self.assertEqual(info.name, "com.example.Main")
        self.assertEqual(info.superclass, "java.lang.Object")
        self.assertEqual(len(info.interfaces), 2)
        self.assertIn("java.io.Serializable", info.interfaces)
        self.assertIn("java.lang.Comparable", info.interfaces)

    def test_interface(self):
        output = 'interface com.example.MyInterface extends java.io.Serializable\n'
        info = parser.parse_class_info(output, "com.example.MyInterface")
        self.assertTrue(info.is_interface)
        self.assertEqual(info.superclass, "java.io.Serializable")


class ParseMethodsTests(unittest.TestCase):
    def test_multiple_methods(self):
        output = ('  void main(java.lang.String[])\n'
                  '  int getValue()\n'
                  '  <init>()\n')
        methods = parser.parse_methods(output, "com.example.Main")
        self.assertGreaterEqual(len(methods), 2)
        names = [m.name for m in methods]
        self.assertIn("main", names)
        self.assertIn("getValue", names)

    def test_empty_methods(self):
        methods = parser.parse_methods("", "com.example.Main")
        self.assertEqual(len(methods), 0)


class ParseFieldsTests(unittest.TestCase):
    def test_multiple_fields(self):
        output = ('  int x\n'
                  '  static java.lang.String name\n'
                  '  java.util.List items\n')
        fields = parser.parse_fields(output, "com.example.Main")
        self.assertEqual(len(fields), 3)
        self.assertEqual(fields[0].name, "x")
        self.assertEqual(fields[0].type, "int")
        self.assertFalse(fields[0].is_static)
        self.assertEqual(fields[1].name, "name")
        self.assertTrue(fields[1].is_static)
        self.assertEqual(fields[2].name, "items")

    def test_empty_fields(self):
        fields = parser.parse_fields("", "com.example.Main")
        self.assertEqual(len(fields), 0)


class ParseLockInfoTests(unittest.TestCase):
    def test_with_owner_and_waiters(self):
        output = ('Monitor information for com.example.Lock@0x1a8:\n'
                  '  Owner: main\n'
                  '  Waiting thread: Thread-1\n'
                  '  Waiting thread: Thread-2\n')
        info = parser.parse_lock_info(output)
        self.assertEqual(info.owner_thread, "main")
        self.assertEqual(len(info.waiting_threads), 2)
        self.assertIn("Thread-1", info.waiting_threads)
        self.assertIn("Thread-2", info.waiting_threads)

    def test_no_owner(self):
        output = 'Monitor information for obj@0x100:\n'
        info = parser.parse_lock_info(output)
        self.assertIsNone(info.owner_thread)
        self.assertEqual(len(info.waiting_threads), 0)


class ParseThreadLocksTests(unittest.TestCase):
    def test_with_owned_and_waiting(self):
        output = ('Monitor information for thread main:\n'
                  '  Owned monitor: instance of java.lang.Object(id=1002)\n'
                  '  Owned monitor: instance of java.lang.Object(id=1003)\n'
                  '  Waiting for monitor: instance of java.lang.Object(id=1004)\n')
        info = parser.parse_thread_locks(output, "main")
        self.assertEqual(info.thread_name, "main")
        self.assertEqual(len(info.owned_monitors), 2)
        self.assertIsNotNone(info.waiting_on)

    def test_no_locks(self):
        output = 'Monitor information for thread main:\n'
        info = parser.parse_thread_locks(output, "main")
        self.assertEqual(len(info.owned_monitors), 0)
        self.assertIsNone(info.waiting_on)


class ParseMonitorTests(unittest.TestCase):
    def test_monitor_set(self):
        output = 'Set monitor 1: locals\n'
        result = parser.parse_monitor_set(output)
        self.assertIsNotNone(result)
        self.assertEqual(result.number, 1)
        self.assertEqual(result.command, "locals")

    def test_monitor_set_none(self):
        output = 'some other output\n'
        result = parser.parse_monitor_set(output)
        self.assertIsNone(result)

    def test_monitor_list(self):
        output = '  1: locals\n  2: where\n'
        monitors = parser.parse_monitor_list(output)
        self.assertEqual(len(monitors), 2)
        self.assertEqual(monitors[0].number, 1)
        self.assertEqual(monitors[0].command, "locals")
        self.assertEqual(monitors[1].number, 2)
        self.assertEqual(monitors[1].command, "where")

    def test_empty_monitor_list(self):
        monitors = parser.parse_monitor_list("")
        self.assertEqual(len(monitors), 0)


class ParseClassesTests(unittest.TestCase):
    def test_class_list(self):
        output = ('com.example.Main\n'
                  'com.example.Helper\n'
                  'java.lang.Object\n')
        classes = parser.parse_classes(output)
        self.assertEqual(len(classes), 3)
        self.assertIn("com.example.Main", classes)
        self.assertIn("java.lang.Object", classes)

    def test_empty_output(self):
        classes = parser.parse_classes("")
        self.assertEqual(len(classes), 0)

    def test_skips_error_lines(self):
        output = ('** some error\n'
                  'com.example.Main\n')
        classes = parser.parse_classes(output)
        self.assertEqual(len(classes), 1)
        self.assertEqual(classes[0], "com.example.Main")
