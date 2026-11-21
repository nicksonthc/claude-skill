#!/usr/bin/env bash
# Pull every file under a remote directory into ~/Downloads/<dir-name>/ over SSH.
# Runs in a visible Terminal window so ssh can prompt for the password.
#
#   rsync_pull.sh <ssh-host> <remote-dir> [status-file]
#
# Writes "ok <dest>" or "fail <exit-code> <dest>" to the status file
# (default /tmp/rsync-pull.status) so the caller can read the outcome.
set -uo pipefail

HOST="${1:?usage: rsync_pull.sh <ssh-host> <remote-dir> [status-file]}"
REMOTE="${2:?usage: rsync_pull.sh <ssh-host> <remote-dir> [status-file]}"
STATUS="${3:-/tmp/rsync-pull.status}"

REMOTE="${REMOTE%/}"
NAME="$(basename "${REMOTE:-root}")"
DEST="$HOME/Downloads/$NAME"
mkdir -p "$DEST"
echo "running" > "$STATUS"

echo "Pulling $HOST:$REMOTE/  →  $DEST/"
echo
# Trailing slash on the source copies the directory's contents into DEST.
# printf %q escapes the path for the remote shell (spaces, quotes).
rsync -avz --progress --partial "$HOST:$(printf %q "$REMOTE")/" "$DEST/"
RC=$?

echo
if (( RC == 0 )); then
  echo "ok $DEST" > "$STATUS"
  echo "✅ Done → $DEST"
else
  echo "fail $RC $DEST" > "$STATUS"
  echo "❌ rsync failed (exit $RC)"
fi
echo "You can close this window."
exit $RC
