#!/bin/sh
# Usage: key-to-clipboard.sh [length]
# Puts a random lowercase-and-digit key on the macOS clipboard.
# Prints only the length of the clipboard value, never the key.
len="${1:-25}"
case "$len" in
  *[!0-9]*|'') echo "length must be a whole number" >&2; exit 1 ;;
esac
python3 -I -c "import secrets,string,sys; a=string.ascii_lowercase+string.digits; sys.stdout.write(''.join(secrets.choice(a) for _ in range($len)))" | pbcopy
pbpaste | wc -c | tr -d ' '
