#!/bin/bash
# Failure injection and retries for completion and decision writes.
here="$(cd "$(dirname "$0")" && pwd)"
python3 "$here/test_done_recovery.py" "$1/where-were-we/scripts/status.py" "$2"
