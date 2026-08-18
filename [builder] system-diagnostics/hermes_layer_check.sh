#!/usr/bin/env bash
# ============================================================
# hermes_layer_check.sh - Hermes layer self-check (Pioneer spec)
# Windows / Git Bash. Pure ASCII, UTF-8 safe.
# Companion to health_check.ps1 (laptop OS layer).
# Run together for the full two-layer audit.
# Sections: version/doctor/config/gateway/cron/memory/git/api/logs/ollama
# ============================================================

HERMES_DIR="/c/Users/ROG/AppData/Local/hermes"
MEM_DIR="$HERMES_DIR/memories"
MEM_LIMIT=7000
USER_LIMIT=4600
NOTE_REPO="/c/Users/ROG/hermes-notes"
SOURCE_REPO="/c/Users/ROG/WORKPLACE/source"
WORKPLACE="/c/Users/ROG/WORKPLACE"

echo "=== Hermes Layer Self-Check (Pioneer spec) ==="
echo

# --- 1. Version ---
echo "[1] Hermes version"
hermes version 2>/dev/null | grep -E "v[0-9]|Python:|Install" | sed 's/^/    /'
echo

# --- 2. Doctor ---
echo "[2] Doctor"
DOC_OUT=$(hermes doctor 2>&1)
echo "$DOC_OUT" | grep -oE "Found [0-9]+ issue" | head -1 | sed 's/^/    /'
echo "$DOC_OUT" | grep -E "^  [0-9]+\." | sed 's/^/      /'
echo

# --- 3. Config ---
echo "[3] Config"
hermes config check 2>/dev/null | grep -E "Config version" | sed 's/^/    /'
echo

# --- 4. Gateway ---
echo "[4] Gateway"
GATEWAY=$(hermes cron status 2>&1)
if echo "$GATEWAY" | grep -q "not running"; then
  echo "    [WARN] Gateway NOT running (cron will NOT fire)"
  echo "    (valid if zero cron jobs + CLI-only mode)"
else
  echo "    [OK] Gateway running"
fi
echo

# --- 5. Cron ---
echo "[5] Cron jobs"
CRON=$(hermes cron list 2>&1)
if echo "$CRON" | grep -q "No scheduled jobs"; then
  echo "    [OK] No scheduled jobs (CLI-only mode)"
else
  echo "$CRON" | grep -E "Job|Next run|Script" | head -20 | sed 's/^/    /'
fi
echo

# --- 6. Memory usage ---
echo "[6] Memory usage (chars vs limit)"
# Native Windows paths (MSYS does not convert heredoc argv for native python)
python - "$MEM_LIMIT" "$USER_LIMIT" <<'PYEOF'
import sys, os
memdir = r"C:/Users/ROG/AppData/Local/hermes/memories"
mem_limit, user_limit = int(sys.argv[1]), int(sys.argv[2])
def usage(name, path, limit):
    try:
        n = len(open(path, encoding='utf-8').read())
        pct = 100.0 * n / limit
        flag = "OK" if pct < 90 else ("WARN" if pct < 98 else "FAIL")
        return "[%s] %s: %d/%d chars (%.0f%%)" % (flag, name, n, limit, pct)
    except Exception as e:
        return "[FAIL] %s: cannot read (%s)" % (name, e)
print("    " + usage("MEMORY", os.path.join(memdir, "MEMORY.md"), mem_limit), end="\n")
print("    " + usage("USER", os.path.join(memdir, "USER.md"), user_limit))
PYEOF
echo

# --- 7. Git repos ---
echo "[7] Git repos"
for repo in "$NOTE_REPO" "$SOURCE_REPO"; do
  if [ -d "$repo/.git" ]; then
    cd "$repo" || continue
    BR=$(git status -sb 2>/dev/null | head -1)
    UNT=$(git status --porcelain 2>/dev/null | wc -l)
    LAST=$(git log -1 --format="%h %ad %s" --date=short 2>/dev/null)
    echo "    repo: $repo"
    echo "      branch: $BR"
    echo "      untracked/modified: $UNT"
    echo "      last commit: $LAST"
  else
    echo "    [WARN] not a git repo: $repo"
  fi
done
if git -C "$WORKPLACE" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  cd "$WORKPLACE"
  UNT=$(git status --porcelain 2>/dev/null | wc -l)
  echo "    WORKPLACE (git repo): $UNT untracked/modified"
  git status --porcelain 2>/dev/null | head -8 | sed 's/^/      /'
else
  echo "    WORKPLACE: not a git repo (source repo checked above)"
fi
echo

# --- 8. API channels ---
echo "[8] API connectivity"
for entry in "api.deepseek.com|https://api.deepseek.com/" "api.github.com|https://api.github.com/" "openrouter.ai|https://openrouter.ai/api/v1/models"; do
  name="${entry%%|*}"; u="${entry#*|}"
  code=$(curl -s --max-time 8 -o /dev/null -w "%{http_code}" "$u" 2>/dev/null)
  t=$(curl -s --max-time 8 -o /dev/null -w "%{time_total}" "$u" 2>/dev/null)
  case "$code" in
    200) echo "    [OK] $name HTTP $code (${t}s)" ;;
    401|403) echo "    [OK] $name HTTP $code (reachable, auth required)" ;;
    *) echo "    [FAIL] $name HTTP $code" ;;
  esac
done
echo

# --- 9. Logs ---
echo "[9] Logs (errors.log, recent non-warning lines)"
RECENT=$(tail -100 "$HERMES_DIR/logs/errors.log" 2>/dev/null | grep -vE "(tools.registry|agent.tool_executor)" | tail -5)
if [ -n "$RECENT" ]; then
  echo "$RECENT" | sed 's/^/    /'
else
  echo "    [OK] no recent errors beyond known noise"
fi
echo

# --- 10. Ollama fallback ---
echo "[10] Ollama fallback"
OV=$(curl -s --max-time 5 http://127.0.0.1:11434/api/version 2>/dev/null)
if [ -n "$OV" ]; then
  echo "    [OK] ollama API: $OV"
else
  echo "    [WARN] ollama not responding on 11434"
fi
echo
echo "=== End of Hermes layer self-check ==="
