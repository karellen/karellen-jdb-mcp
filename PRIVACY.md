# Privacy Policy

**karellen-jdb-mcp** — MCP Server for JDB (Java Debugger)

*Last updated: 2026-03-20*

## Summary

karellen-jdb-mcp does not collect, transmit, or store any personal data. It runs
entirely on your local machine.

## Data Collection

This software does **not**:

- Collect or transmit any personal information
- Send telemetry, analytics, or usage data
- Make any network connections (other than the local TCP communication
  between the MCP server and JDB via JDWP, all on localhost)
- Store any data beyond what JDB itself produces

## Data Processing

All debugging operations (attaching, stepping, inspecting program state) are
performed locally using JDB. The MCP server acts as a local bridge between
the MCP client (e.g. Claude Code) and JDB. No data leaves your machine
through this software.

## Third-Party Services

This software does not integrate with any third-party services or APIs.

## Changes to This Policy

If this policy changes, the updated version will be published in the project
repository at
[https://github.com/karellen/karellen-jdb-mcp](https://github.com/karellen/karellen-jdb-mcp).

## Contact

If you have questions about this privacy policy, please open an issue at
[https://github.com/karellen/karellen-jdb-mcp/issues](https://github.com/karellen/karellen-jdb-mcp/issues)
or contact [supervisor@karellen.co](mailto:supervisor@karellen.co).
