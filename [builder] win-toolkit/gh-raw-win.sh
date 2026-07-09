#!/bin/bash
# gh-raw-win — 通过 GitHub API 下载 raw 文件（Builder Win11 版）
# 替代被墙的 raw.githubusercontent.com
#
# 用法: gh-raw-win <org/repo> <branch> <path>
# 例:   gh-raw-win d2l-ai/d2l-zh master chapter_introduction/index.md

set -euo pipefail

if [ $# -ne 3 ]; then
    echo "用法: $0 <org/repo> <branch> <path>" >&2
    exit 1
fi

REPO="$1"
BRANCH="$2"
FPATH="$3"

# 读取 token — 优先 .env，回退到环境变量
TOKEN=""
if [ -f "$HOME/.hermes/.env" ]; then
    TOKEN=$(grep '^GITHUB_TOKEN=' "$HOME/.hermes/.env" | sed 's/^GITHUB_TOKEN=//' | tr -d '"' || true)
fi
if [ -z "$TOKEN" ]; then
    TOKEN="${GITHUB_TOKEN:-}"
fi
if [ -z "$TOKEN" ]; then
    echo "错误: GITHUB_TOKEN 未在 ~/.hermes/.env 或环境变量中" >&2
    exit 1
fi

# API 调用 — 用 python 解析 JSON（JSON 的 content 字段 base64 可能跨行）
curl -s -H "Authorization: Bearer $TOKEN" \
    "https://api.github.com/repos/$REPO/contents/$FPATH?ref=$BRANCH" | \
    python -c "
import sys, json, base64
try:
    data = json.load(sys.stdin)
    if 'message' in data:
        print(f'GitHub API 错误: {data[\"message\"]}', file=sys.stderr)
        sys.exit(1)
    content = data.get('content', '')
    if not content:
        print('错误: 未找到 content 字段', file=sys.stderr)
        sys.exit(1)
    sys.stdout.buffer.write(base64.b64decode(content))
except json.JSONDecodeError as e:
    print(f'JSON 解析失败: {e}', file=sys.stderr)
    sys.exit(1)
"
