#!/bin/bash
# Detect Java exception stack traces in Bash tool output and suggest JDB debugging.
# Runs on PostToolUse and PostToolUseFailure for Bash commands.
# Reads the hook input JSON from stdin.

# Bail early if dependencies missing or karellen-jdb-mcp not installed
command -v jq &>/dev/null || exit 0
command -v jdb &>/dev/null || exit 0
command -v karellen-jdb-mcp &>/dev/null || exit 0

INPUT=$(cat)

EXCEPTION_DETECTED=""

EVENT=$(echo "$INPUT" | jq -r '.hook_event_name // empty' 2>/dev/null)

# Get text to check from tool_response or error
TEXT=""
if [ "$EVENT" = "PostToolUse" ]; then
  TEXT=$(echo "$INPUT" | jq -r '.tool_response // empty' 2>/dev/null)
elif [ "$EVENT" = "PostToolUseFailure" ]; then
  TEXT=$(echo "$INPUT" | jq -r '.error // empty' 2>/dev/null)
fi

[ -n "$TEXT" ] || exit 0

# Check for Java exception patterns
MATCH=$(echo "$TEXT" | grep -oE \
  'Exception in thread|java\.[a-z]+\.[A-Z]\w*Exception|java\.[a-z]+\.[A-Z]\w*Error|javax?\.\w+\.\w+Exception|at [a-z][\w.]+\([A-Z][\w]+\.java:[0-9]+\)|Caused by:|java\.lang\.(NullPointerException|ArrayIndexOutOfBoundsException|ClassCastException|IllegalArgumentException|IllegalStateException|StackOverflowError|OutOfMemoryError|UnsupportedOperationException|ConcurrentModificationException|NoSuchElementException)' \
  2>/dev/null | head -1)

[ -n "$MATCH" ] || exit 0

EXCEPTION_DETECTED="$MATCH"

# Emit suggestion
jq -n --arg exc "$EXCEPTION_DETECTED" --arg event "$EVENT" '{
  hookSpecificOutput: {
    hookEventName: $event,
    additionalContext: ("Java exception detected: " + $exc + ". This is a good candidate for JDB debugging. Use the jdb-investigator agent or /karellen-jdb-mcp:jdb-debug to attach to the JVM and debug with breakpoints, expression evaluation, and thread inspection to find the exact root cause.")
  }
}'
