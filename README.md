# MCP Server for JDB Java Debugging (karellen-jdb-mcp)

[![Gitter](https://img.shields.io/gitter/room/karellen/lobby?logo=gitter)](https://gitter.im/karellen/Lobby)
[![Build Status](https://img.shields.io/github/actions/workflow/status/karellen/karellen-jdb-mcp/build.yml?branch=master)](https://github.com/karellen/karellen-jdb-mcp/actions/workflows/build.yml)
[![Coverage Status](https://img.shields.io/coveralls/github/karellen/karellen-jdb-mcp/master?logo=coveralls)](https://coveralls.io/r/karellen/karellen-jdb-mcp?branch=master)

[![karellen-jdb-mcp Version](https://img.shields.io/pypi/v/karellen-jdb-mcp?logo=pypi)](https://pypi.org/project/karellen-jdb-mcp/)
[![karellen-jdb-mcp Python Versions](https://img.shields.io/pypi/pyversions/karellen-jdb-mcp?logo=pypi)](https://pypi.org/project/karellen-jdb-mcp/)
[![karellen-jdb-mcp Downloads Per Day](https://img.shields.io/pypi/dd/karellen-jdb-mcp?logo=pypi)](https://pypi.org/project/karellen-jdb-mcp/)
[![karellen-jdb-mcp Downloads Per Week](https://img.shields.io/pypi/dw/karellen-jdb-mcp?logo=pypi)](https://pypi.org/project/karellen-jdb-mcp/)
[![karellen-jdb-mcp Downloads Per Month](https://img.shields.io/pypi/dm/karellen-jdb-mcp?logo=pypi)](https://pypi.org/project/karellen-jdb-mcp/)

## Overview

`karellen-jdb-mcp` is an [MCP](https://modelcontextprotocol.io/) (Model Context Protocol)
server that enables any MCP-compliant LLM client to use [JDB](https://docs.oracle.com/en/java/javase/21/docs/specs/man/jdb.html)
(the Java Debugger) for debugging JVM processes. The LLM can attach to a running JVM,
set breakpoints, step through code, evaluate expressions, inspect threads, and analyze
concurrency issues, all through structured JSON tool calls over the JDWP protocol.

## Requirements

- **Java Development Kit** (JDK) with `jdb` on PATH (JDK 8 through 24+ supported)
- **Python** >= 3.10
- Works on **Linux**, **macOS**, and **Windows** (anywhere JDB runs)

### Installing a JDK

**Fedora / RHEL / CentOS:**
```bash
sudo dnf install java-21-openjdk-devel
```

**Ubuntu / Debian:**
```bash
sudo apt install openjdk-21-jdk
```

**macOS (Homebrew):**
```bash
brew install openjdk@21
```

### Verify the setup

```bash
jdb -version
```

This should print something like `This is jdb version 21.0.4`.

## Installation

```bash
pip install karellen-jdb-mcp
```

Or with pipx for an isolated environment:

```bash
pipx install karellen-jdb-mcp
```

## Claude Code Integration

### Claude Code plugin (recommended)

The plugin automatically configures the MCP server and includes:

- **Exception detection hook** that suggests JDB when a Bash command output contains
  Java exception stack traces (`Exception in thread`, `NullPointerException`, etc.)
- **`/karellen-jdb-mcp:jdb-debug` skill** that walks through the full
  launch-attach-debug workflow step by step, with build-tool-specific JDWP stanzas
- **`jdb-investigator` agent** that Claude can spawn to autonomously investigate
  Java exceptions, deadlocks, and logic bugs using JDB

From the [Karellen plugins marketplace](https://github.com/karellen/claude-plugins):

```bash
claude plugin marketplace add karellen/claude-plugins
claude plugin install karellen-jdb-mcp@karellen-plugins
```

Or from the official Anthropic marketplace (if accepted):

```bash
claude plugin install karellen-jdb-mcp@claude-plugins-official
```

Or load directly from a local checkout for testing:

```bash
claude --plugin-dir /path/to/karellen-jdb-mcp
```

### Manual MCP server configuration

If you prefer not to use the plugin, you can configure the MCP server directly.
This gives you the MCP tools but not the skill, agent, or exception detection hook.

Using the CLI:

```bash
claude mcp add --transport stdio karellen-jdb-mcp -- karellen-jdb-mcp
```

Or manually add to `~/.claude.json` (user scope) or `.mcp.json` in your project root
(project scope, shared via version control):

```json
{
  "mcpServers": {
    "karellen-jdb-mcp": {
      "type": "stdio",
      "command": "karellen-jdb-mcp"
    }
  }
}
```

If installed with pipx:

```bash
claude mcp add --transport stdio karellen-jdb-mcp -- pipx run karellen-jdb-mcp
```

or manually:

```json
{
  "mcpServers": {
    "karellen-jdb-mcp": {
      "type": "stdio",
      "command": "pipx",
      "args": ["run", "karellen-jdb-mcp"]
    }
  }
}
```

### Auto-approve jdb tools

By default Claude Code will prompt for confirmation before each `jdb_*` tool call.
You can approve individually by selecting "Yes, and don't ask again" when prompted.

To auto-approve all tools upfront, add a permission rule to your user settings
(`~/.claude/settings.json`):

```json
{
  "permissions": {
    "allow": [
      "mcp__plugin_karellen-jdb-mcp_karellen-jdb-mcp__*",
      "mcp__karellen-jdb-mcp__*"
    ]
  }
}
```

The first rule covers plugin-loaded tools, the second covers manual MCP configuration.

Or for a project-scoped setting, add the same rule to `.claude/settings.json` in your
project root (this file can be committed to version control so all team members get it).

## Quick Start

### With `jdb_launch` (recommended)

Launch the JVM with `${JDB_PORT}` substitution — a random free port is allocated:

```
jdb_launch(["java", "-agentlib:jdwp=transport=dt_socket,server=y,suspend=y,address=*:${JDB_PORT}",
            "-cp", "target/classes", "com.example.Main"])
```

Connect (port auto-resolves when there's one launched process):

```
jdb_connect(wait_timeout=30)
```

Debug:

```
jdb_breakpoint_set("com.example.Main:42")
jdb_run()
jdb_where()
jdb_locals()
```

Clean up:

```
jdb_disconnect()
jdb_launch_stop(port=<port>)
```

### With a manually started JVM

Start the JVM yourself with JDWP on a known port, then connect:

```
jdb_connect(port=5005, wait_timeout=30)
```

## Available Tools

### Process Launch
| Tool | Description |
|------|-------------|
| `jdb_launch` | Launch a JVM with JDWP on a random port. `${JDB_PORT}` is substituted in the command. |
| `jdb_launch_list` | List all launched JVM processes with status. |
| `jdb_launch_status` | Get status of a launched process by port. |
| `jdb_launch_stop` | Stop a launched process by port. |

### Session Lifecycle
| Tool | Description |
|------|-------------|
| `jdb_connect` | Attach to a running JVM via JDWP. Auto-resolves port from single launched process, or defaults to 5005. |
| `jdb_disconnect` | Disconnect and clean up. Port optional if only one session active. |
| `jdb_session_list` | List all active debug sessions with port, connection status, and JDK version. |
| `jdb_version` | Get JDB version info and available features. |

### Execution Control
| Tool | Description |
|------|-------------|
| `jdb_run` | Start execution of the application's main class. Returns immediately once execution resumes. |
| `jdb_cont` | Continue execution. Returns immediately once the JVM resumes (fire-and-forget). Returns stop event if a breakpoint/exception is hit within `TIMEOUT_RESUME`. |
| `jdb_step` | Step into (enter method calls). Returns stop event on completion or returns immediately if execution resumes. |
| `jdb_next` | Step over (skip method calls). Same return behavior as step. |
| `jdb_step_up` | Step out (run until current method returns). Same return behavior as step. |
| `jdb_wait_for_event` | Wait for a stop event after `jdb_cont`/`jdb_run` returned `reason="resumed"`. Blocks until breakpoint/exception/exit or timeout (default 120s). |

### Breakpoints
| Tool | Description |
|------|-------------|
| `jdb_breakpoint_set` | Set breakpoint at class:line or class.method. Supports thread filters and suspend policy on JDK 13+. |
| `jdb_breakpoint_clear` | Clear a breakpoint. |
| `jdb_breakpoint_list` | List all breakpoints. |
| `jdb_catch` | Break on exception (caught/uncaught/all). Supports wildcard patterns. |
| `jdb_ignore` | Cancel an exception breakpoint. |

### Watchpoints
| Tool | Description |
|------|-------------|
| `jdb_watch` | Watch field access/modifications. |
| `jdb_unwatch` | Remove a field watchpoint. |

### Thread Management
| Tool | Description |
|------|-------------|
| `jdb_threads` | List all threads by group with status. |
| `jdb_thread` | Set default thread for subsequent commands. |
| `jdb_suspend` | Suspend threads (all or specific). |
| `jdb_resume` | Resume threads (all or specific). |

### Stack Navigation
| Tool | Description |
|------|-------------|
| `jdb_where` | Get call stack (stack trace). Use `"all"` for all threads. |
| `jdb_up` | Move up the call stack (toward caller). |
| `jdb_down` | Move down the call stack (toward callee). |

### State Inspection
| Tool | Description |
|------|-------------|
| `jdb_print` | Evaluate Java expression (fields, locals, method calls, arithmetic). |
| `jdb_dump` | Dump object showing all fields (static and instance). |
| `jdb_eval` | Evaluate expression (alias for print). |
| `jdb_set` | Assign value to variable, field, or array element. |
| `jdb_locals` | List local variables with values. |

### Class Introspection
| Tool | Description |
|------|-------------|
| `jdb_classes` | List all loaded classes. |
| `jdb_class_info` | Show class details (superclass, interfaces). |
| `jdb_methods` | List class methods. |
| `jdb_fields` | List class fields. |

### Source
| Tool | Description |
|------|-------------|
| `jdb_list` | List source code at current position or specified location. |
| `jdb_sourcepath` | Display or change source path for .java files. |
| `jdb_classpath` | Print classpath info from target JVM. |

### Concurrency Analysis
| Tool | Description |
|------|-------------|
| `jdb_lock` | Object lock/monitor info (owner thread, waiting threads). |
| `jdb_threadlocks` | Thread lock info (owned monitors, lock being waited on). |

### Frame Manipulation
| Tool | Description |
|------|-------------|
| `jdb_pop` | Pop current frame (return to caller, allows re-execution). |
| `jdb_reenter` | Re-enter current method from the beginning. |

### Tracing
| Tool | Description |
|------|-------------|
| `jdb_trace` | Trace method entries/exits (optionally per-thread). |
| `jdb_untrace` | Stop tracing. |

### Monitors (Auto-execute)
| Tool | Description |
|------|-------------|
| `jdb_monitor` | Auto-execute a command on every stop (e.g. `"locals"`, `"where"`). |
| `jdb_monitor_list` | List active monitors. |
| `jdb_unmonitor` | Remove a monitor. |

### Configuration
| Tool | Description |
|------|-------------|
| `jdb_exclude` | Set/display step exclusion filter (skip library classes when stepping). |

**Note:** All debugging tools accept an optional `port` parameter. When only one session
is active, it auto-resolves. When multiple sessions are active, `port` is required.

## Configuration

### Timeouts

All timeouts are configurable via environment variables (in seconds). Set them in your
MCP server configuration:

```json
{
  "mcpServers": {
    "karellen-jdb-mcp": {
      "type": "stdio",
      "command": "karellen-jdb-mcp",
      "env": {
        "JDB_MCP_TIMEOUT_EXECUTION": "300"
      }
    }
  }
}
```

| Variable | Default | Description |
|----------|---------|-------------|
| `JDB_MCP_TIMEOUT_CONNECT` | 60 | JDB attach and initial prompt |
| `JDB_MCP_TIMEOUT_COMMAND` | 30 | Non-execution commands (breakpoints, inspection, etc.) |
| `JDB_MCP_TIMEOUT_EXECUTION` | 120 | Prompt-based commands (used internally by `send_command`) |
| `JDB_MCP_TIMEOUT_RESUME` | 5 | Execution commands (run, cont, step, next, step up). These return immediately when output arrives or after this timeout if execution resumes with no output (fire-and-forget). |

## Build Tool Debug Stanzas

To debug a JVM process, it must be started with the JDWP agent. The exact syntax
varies by build tool:

| Build Tool | Command |
|---|---|
| Plain `java` | `java -agentlib:jdwp=transport=dt_socket,server=y,suspend=y,address=*:5005 ...` |
| Maven Surefire | `mvn -Dmaven.surefire.debug test` |
| Maven Failsafe | `mvn -Dmaven.failsafe.debug verify` |
| Gradle tests | `./gradlew test --debug-jvm` |
| Tycho Surefire | `mvn verify -Dtycho.testArgLine="-agentlib:jdwp=transport=dt_socket,server=y,suspend=y,address=*:5005"` |
| Spring Boot | `mvn spring-boot:run -Dspring-boot.run.jvmArguments="-agentlib:jdwp=transport=dt_socket,server=y,suspend=y,address=*:5005"` |
| Any (fallback) | `JAVA_TOOL_OPTIONS="-agentlib:jdwp=transport=dt_socket,server=y,suspend=y,address=*:5005" <command>` |

## License

Apache-2.0

## Privacy

See [PRIVACY.md](PRIVACY.md). This software does not collect or transmit any data.
