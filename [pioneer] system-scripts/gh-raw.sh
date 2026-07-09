#!/usr/bin/env bash
# gh-raw.sh — 通过 GitHub API 下载 raw 文件（替代被墙的 raw.githubusercontent.com）
# 用法: gh-raw <org/repo> <branch> <path>
# 例:   gh-raw ngosang/trackerslist master trackers_all.txt
#       gh-raw d2l-ai/d2l-zh master chapter_linear-networks/linear-regression-scratch.md
set -euo pipefail

if [ $# -lt 3 ]; then
  echo "Usage: gh-raw <org/repo> <branch> <path>" >&2
  exit 1
fi

REPO="$1"
BRANCH="$2"
FILE_PATH="$3"

# 从 .env 读 token
TOKEN_FILE="${HERMES_ENV:-$HOME/.hermes/.env}"
TOKEN=""

if [ -f "$TOKEN_FILE" ]; then
  TOKEN=$(grep '^GITHUB_TOKEN=' "$TOKEN_FILE" | head -1 | cut -d= -f2-)
fi

# URL encode 文件路径中的特殊字符
# GitHub API 需要路径中的斜杠保持原样，但空格和特殊字符需转义
ENCODED_PATH=""
IFS='/' read -ra PARTS <<< "$FILE_PATH"
for i in "${!PARTS[@]}"; do
  if [ $i -gt 0 ]; then
    ENCODED_PATH+="/"
  fi
  # 只转义空格和 # 号（GitHub API 接受的编码）
  PART=$(python3 -c "import urllib.parse; print(urllib.parse.quote('${PARTS[$i]}', safe=''))" 2>/dev/null || echo "${PARTS[$i]}")
  ENCODED_PATH+="$PART"
done

URL="https://api.github.com/repos/${REPO}/contents/${ENCODED_PATH}?ref=${BRANCH}"

if [ -n "$TOKEN" ]; then
  curl -s -H "Authorization: token ${TOKEN}" "$URL" | python3 -c "
import sys, json, base64
d = json.load(sys.stdin)
if 'content' in d:
    print(base64.b64decode(d['content']).decode(), end='')
elif 'message' in d:
    print(f'ERROR: {d[\"message\"]}', file=sys.stderr)
    sys.exit(1)
else:
    print('ERROR: Unexpected API response', file=sys.stderr)
    sys.exit(1)
"
else
  # 未配 token 时仍尝试（有速率限制）
  curl -s "$URL" | python3 -c "
import sys, json, base64
d = json.load(sys.stdin)
if 'content' in d:
    print(base64.b64decode(d['content']).decode(), end='')
elif 'message' in d:
    print(f'ERROR: {d[\"message\"]}', file=sys.stderr)
    sys.exit(1)
else:
    print('ERROR: Unexpected API response', file=sys.stderr)
    sys.exit(1)
"
fi
