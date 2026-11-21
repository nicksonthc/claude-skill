---
name: rsync-pull
description: Pull a whole directory from an SSH host into ~/Downloads with rsync, password typed in a Terminal window.
disable-model-invocation: true
argument-hint: "[ssh-host] [remote-dir]"
---

Copy every file under a remote directory to `~/Downloads/<dir-name>/` on this Mac. The transfer runs in a new Terminal window so ssh can prompt for the password there — the user types it, never you.

## 1. SSH host

Take it from the first argument if given. Otherwise ask, offering the aliases from `grep -E '^Host ' ~/.ssh/config` (drop `*` and `github.com`); `user@ip` is also accepted.

Done when you have one host string.

## 2. Remote directory

Take it from the second argument if given; otherwise ask for the absolute path. Everything under it is copied, subfolders included.

Done when you have one path.

## 3. Confirm

Show the plan in one line and wait for a yes:

`<host>:<remote-dir>/  →  ~/Downloads/<basename of remote-dir>/`

## 4. Run in Terminal

```bash
rm -f /tmp/rsync-pull.status
osascript \
  -e 'tell application "Terminal" to activate' \
  -e "tell application \"Terminal\" to do script \"'$HOME/.claude/skills/rsync-pull/rsync_pull.sh' '<host>' '<remote-dir>'\""
```

Tell the user: a Terminal window opened — type the SSH password there.

## 5. Report

Wait until `/tmp/rsync-pull.status` reads something other than `running` (Monitor with an until-loop, ~10 min cap). Then:

- `ok <dest>` → report the destination plus file count and size (`find <dest> -type f | wc -l`, `du -sh <dest>`).
- `fail <code> <dest>` → report the exit code and ask the user to check the Terminal window; common causes are a wrong password (code 255), a wrong path (23), or a dropped connection (rerun — `--partial` resumes).
- Status never appears → the Terminal window may still be at the password prompt; ask the user.
