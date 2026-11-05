#!/usr/bin/env bash
#
# ms-python.sh — print a python interpreter that can import pymilvus, or exit 1.
#
# memsearch is installed differently per machine: on macOS it lives in the pyenv
# python3 (pip install memsearch), so python3 imports pymilvus directly. On Linux
# the system python3 is externally managed (PEP 668), so memsearch is a
# `uv tool install` with its own venv, and python3 cannot see pymilvus. That
# venv's interpreter is the shebang of the `memsearch` entry point.
#
# Usage:  py="$(scripts/memsearch/ms-python.sh)" && "$py" prune-orphans.py
#
if python3 -c 'import pymilvus' >/dev/null 2>&1; then
  command -v python3; exit 0
fi
ms="$(command -v memsearch 2>/dev/null)" || exit 1
py="$(head -1 "$ms" | sed -n 's/^#!\([^ ]*python[^ ]*\)$/\1/p')"
[ -n "$py" ] && [ -x "$py" ] && "$py" -c 'import pymilvus' >/dev/null 2>&1 || exit 1
printf '%s\n' "$py"
