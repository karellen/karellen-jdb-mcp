# karellen-jdb-mcp

MCP Server for JDB (Java Debugger) — enables Claude Code to debug JVM processes
via the Java Platform Debugger Architecture (JPDA).

## Overview

karellen-jdb-mcp wraps JDB as a Model Context Protocol (MCP) server, exposing
structured debugging tools that Claude Code can use to attach to running JVMs,
set breakpoints, inspect state, evaluate expressions, and navigate execution.

## Features

- Attach to any JVM with JDWP enabled
- Breakpoints (line, method, conditional), exception breakpoints, field watchpoints
- Execution control: step into/over/out, continue, run
- State inspection: locals, expression evaluation, object dumps
- Thread management and concurrency analysis (lock/monitor info)
- Class introspection: classes, methods, fields, class hierarchy
- Source code listing, tracing, monitors (auto-execute on stop)
- Frame manipulation (pop, reenter)
- JDK version detection with feature flags (JDK 8 through 24+)

## Installation

```bash
pip install karellen-jdb-mcp
```

Requires Python 3.10+ and a JDK with `jdb` on PATH.

## Usage

### As an MCP server

Add to your Claude Code MCP configuration:

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

### Debugging a Java application

1. Start the target JVM with JDWP:
   ```bash
   java -agentlib:jdwp=transport=dt_socket,server=y,suspend=y,address=*:5005 \
        -cp target/classes com.example.Main
   ```

2. Connect JDB via the MCP tool:
   ```
   jdb_connect(host="localhost", port=5005)
   ```

3. Set breakpoints and debug:
   ```
   jdb_breakpoint_set("com.example.Main:42")
   jdb_run()
   jdb_where()
   jdb_locals()
   ```

4. Clean up:
   ```
   jdb_disconnect()
   ```

## Build Tool Debug Stanzas

| Build Tool | Command |
|---|---|
| Maven Surefire | `mvn -Dmaven.surefire.debug test` |
| Maven Failsafe | `mvn -Dmaven.failsafe.debug verify` |
| Gradle tests | `./gradlew test --debug-jvm` |
| Tycho Surefire | `mvn verify -Dtycho.testArgLine="-agentlib:jdwp=..."` |
| Spring Boot | `mvn spring-boot:run -Dspring-boot.run.jvmArguments="-agentlib:jdwp=..."` |
| Any (fallback) | `JAVA_TOOL_OPTIONS="-agentlib:jdwp=..." <command>` |

## License

Apache License 2.0

## Privacy

See [PRIVACY.md](PRIVACY.md). This software does not collect or transmit any data.
