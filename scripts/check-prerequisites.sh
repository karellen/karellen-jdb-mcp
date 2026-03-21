#!/bin/bash
# Check that karellen-jdb-mcp prerequisites are available.
# Runs once on SessionStart. Reports missing dependencies via JSON output.

WARNINGS=""

check_command() {
  local cmd="$1"
  local install_hint="$2"
  local path
  path=$(command -v "$cmd" 2>/dev/null)
  if [ -z "$path" ]; then
    WARNINGS="${WARNINGS}- ${cmd} is not installed. ${install_hint}"$'\n'
  elif [ ! -x "$path" ]; then
    WARNINGS="${WARNINGS}- ${cmd} found at ${path} but is not executable. Run: chmod +x ${path}"$'\n'
  fi
}

check_command "karellen-jdb-mcp" "Run: pip install karellen-jdb-mcp"
check_command "jdb" "Install a JDK (e.g. apt install default-jdk, brew install openjdk)."
check_command "java" "Install a JDK (e.g. apt install default-jdk, brew install openjdk)."

[ -z "$WARNINGS" ] && exit 0

jq -n --arg warnings "$WARNINGS" '{
  systemMessage: ("karellen-jdb-mcp plugin: missing prerequisites:\n" + $warnings),
  hookSpecificOutput: {
    hookEventName: "SessionStart",
    additionalContext: ("karellen-jdb-mcp plugin prerequisites are missing:\n" + $warnings + "The JDB debugging tools will not work until these are resolved.")
  }
}'
