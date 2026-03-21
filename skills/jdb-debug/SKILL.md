---
description: Debug a Java application using JDB. Attaches to a running JVM, sets breakpoints, inspects state, and navigates execution to find the root cause of bugs.
---

# JDB Debugging Workflow

Use this skill when the user wants to debug a Java application, investigate an exception,
inspect runtime state, or understand execution flow.

## Prerequisites

- `jdb` must be installed and on PATH (comes with the JDK)
- The target JVM must be started with JDWP debug agent enabled (see below)
- `suspend=y` pauses the JVM until the debugger attaches (recommended for startup debugging)
- `suspend=n` lets the JVM run immediately (for attaching to a live process)

## Launching the JVM with Debug Support

You (Claude) will typically start the JVM yourself before connecting. The JDWP agent stanza
varies by launcher. Pick a free port (e.g. 5005) and use `suspend=y` so the JVM waits for
you to attach.

### Plain `java`
```bash
java -agentlib:jdwp=transport=dt_socket,server=y,suspend=y,address=*:5005 \
     -cp target/classes com.example.Main
```

### Maven (Surefire / Failsafe tests)
```bash
mvn test -Dmaven.surefire.debug="-agentlib:jdwp=transport=dt_socket,server=y,suspend=y,address=*:5005"
```
Or the built-in shorthand (uses port 5005 by default):
```bash
mvn -Dmaven.surefire.debug test
```
For Failsafe integration tests replace `surefire` with `failsafe`.

### Maven (application via exec-maven-plugin)
```bash
MAVEN_OPTS="-agentlib:jdwp=transport=dt_socket,server=y,suspend=y,address=*:5005" \
  mvn exec:java -Dexec.mainClass=com.example.Main
```

### Gradle (tests)
```bash
./gradlew test --debug-jvm   # uses port 5005 by default, suspend=y
```

### Gradle (application via JavaExec)
Add to the task or pass via env:
```bash
JAVA_OPTS="-agentlib:jdwp=transport=dt_socket,server=y,suspend=y,address=*:5005" \
  ./gradlew run
```

### OSGi / Eclipse Tycho (Surefire)
Tycho Surefire uses the same property as Maven Surefire:
```bash
mvn verify -Dmaven.surefire.debug="-agentlib:jdwp=transport=dt_socket,server=y,suspend=y,address=*:5005"
```
Or with the `tycho.testArgLine` property:
```bash
mvn verify -Dtycho.testArgLine="-agentlib:jdwp=transport=dt_socket,server=y,suspend=y,address=*:5005"
```

### Spring Boot
```bash
mvn spring-boot:run -Dspring-boot.run.jvmArguments="-agentlib:jdwp=transport=dt_socket,server=y,suspend=y,address=*:5005"
```
Or with Gradle:
```bash
./gradlew bootRun --args='--debug' # or pass JAVA_OPTS
```

### Generic: JAVA_TOOL_OPTIONS (any launcher)
As a fallback, this environment variable is picked up by every JVM:
```bash
JAVA_TOOL_OPTIONS="-agentlib:jdwp=transport=dt_socket,server=y,suspend=y,address=*:5005" \
  <any-command-that-starts-a-jvm>
```

## Workflow

### 1. Launch the JVM and Connect

Use `jdb_launch` to start the JVM with `${JDB_PORT}` substitution (allocates a random port):
```
jdb_launch(["java", "-agentlib:jdwp=transport=dt_socket,server=y,suspend=y,address=*:${JDB_PORT}",
            "-cp", "target/classes", "com.example.Main"])
```

Or for Maven tests:
```
jdb_launch(["mvn", "test",
            "-Dmaven.surefire.debug=-agentlib:jdwp=transport=dt_socket,server=y,suspend=y,address=*:${JDB_PORT}"])
```

Then connect with `wait_timeout` to wait for the JVM to start. When there is exactly
one launched process, `jdb_connect` auto-resolves the port — no need to pass it:
```
jdb_connect(wait_timeout=30)
```

If you launched multiple JVMs or are connecting to a manually started JVM, specify the port:
```
jdb_connect(port=5005, wait_timeout=30)
```

Similarly, all debugging tools auto-resolve the port when only one session is active.
When multiple sessions are active, pass `port=` to select which session to use.

Pass `jdb_path` if jdb is not on PATH. Pass `sourcepath` to enable source listing.
Pass `trackallthreads=True` on JDK 20+ to track virtual threads.

### 2. Set Breakpoints

```
jdb_breakpoint_set("com.example.MyClass:42")           # line breakpoint
jdb_breakpoint_set("com.example.MyClass.myMethod")      # method breakpoint
jdb_breakpoint_set("com.example.MyClass.myMethod(int)")  # overloaded method
```

For exception debugging:
```
jdb_catch("java.lang.NullPointerException")             # break on NullPointerException
jdb_catch("*", filter_type="uncaught")                   # break on any uncaught exception
```

For field watchpoints:
```
jdb_watch("com.example.MyClass.myField")                 # break on field write
jdb_watch("com.example.MyClass.myField", access_type="access")  # break on field read
```

### 3. Start or Resume Execution

If the JVM was started with `suspend=y`:
```
jdb_run()      # start execution
```

Or if already running:
```
jdb_cont()     # continue to next breakpoint/exception
```

### 4. Examine State

- `jdb_where()` — see the call stack
- `jdb_locals()` — see all local variables
- `jdb_print("expression")` — evaluate any Java expression
- `jdb_dump("objectRef")` — show all fields of an object
- `jdb_list()` — see source code at current position
- `jdb_threads()` — list all threads

### 5. Navigate Execution

- `jdb_step()` — step into (enter method calls)
- `jdb_next()` — step over (skip over method calls)
- `jdb_step_up()` — step out (run until current method returns)
- `jdb_up()` / `jdb_down()` — navigate the call stack without stepping

### 6. Investigate Deeper

- Use `jdb_classes()` to find loaded classes
- Use `jdb_methods("com.example.MyClass")` to discover available methods
- Use `jdb_fields("com.example.MyClass")` to discover fields
- Use `jdb_class_info("com.example.MyClass")` to see class hierarchy
- Use `jdb_set("variable", "newValue")` to modify state and test hypotheses

### 7. Debug Concurrency Issues

For deadlock analysis:
- `jdb_threads()` — find stuck threads
- `jdb_threadlocks()` — see what locks a thread holds and waits for
- `jdb_lock("objectRef")` — see who owns a lock and who's waiting
- `jdb_thread("threadId")` then `jdb_where()` — inspect each thread's stack

### 8. Managing Sessions and Processes

- `jdb_session_list()` — list all active debug sessions with port and JDK version
- `jdb_launch_list()` — list all launched JVM processes with status
- `jdb_launch_status(port=<port>)` — check if a specific launched process is still running

### 9. Clean Up

```
jdb_disconnect()
jdb_launch_stop(port=<port>)
```

Or when debugging multiple JVMs:
```
jdb_disconnect(port=<port>)
jdb_launch_stop(port=<port>)
```

## Key Rules

- **Use `jdb_launch` to start JVMs** rather than Bash. It handles port allocation,
  `${JDB_PORT}` substitution, and process detachment.
- **Always connect before using any other tools.** All tools except `jdb_connect`,
  `jdb_launch*`, and `jdb_session_list` require an active session.
- **Set breakpoints before running** if you need to stop at a specific point during startup.
- **Use `jdb_catch` for exception debugging** — it's more effective than guessing where to
  set breakpoints.
- **Check `jdb_version` for feature availability.** Thread-filtered breakpoints require
  JDK 13+, virtual thread tracking requires JDK 20+.
- **Use `jdb_exclude` to skip library code** when stepping. By default, JDB skips
  java.*, javax.*, sun.*, com.sun.*, jdk.*.
- **Use `jdb_monitor("locals")` to auto-print locals** at every stop for hands-free
  debugging.
