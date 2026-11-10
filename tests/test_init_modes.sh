#!/bin/bash
here="$(cd "$(dirname "$0")" && pwd)"
python3 "$here/test_init_modes.py" "$1/where-were-we/scripts/status.py" "$2"
