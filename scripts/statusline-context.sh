#!/bin/sh
# Claude Code status line: context-window usage, always visible.
# Claude Code has one statusLine slot and Orca's forwarder already owns it.
# That forwarder prints nothing, so this script chains it and prints the meter.
payload=$(cat)
[ -n "$payload" ] || exit 0

ORCA_STATUSLINE="$HOME/.orca/agent-hooks/claude-statusline.sh"
if [ -x "$ORCA_STATUSLINE" ]; then
  printf '%s' "$payload" | /bin/sh "$ORCA_STATUSLINE" >/dev/null 2>&1 &
fi

# Prints "<percent> <window size in thousands>", or nothing before the first API response.
set -- $(printf '%s' "$payload" | jq -r '
  .context_window
  | select(.used_percentage != null)
  | "\(.used_percentage | floor) \((.context_window_size // 0) / 1000 | floor)"' 2>/dev/null)
[ -n "${1-}" ] || exit 0

if [ "$1" -ge 80 ]; then color=31
elif [ "$1" -ge 60 ]; then color=33
else color=32
fi
printf '\033[%smctx %s%%\033[0m of %sk' "$color" "$1" "${2:-?}"
