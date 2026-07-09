#!/bin/bash
# ~/.hermes/scripts/notes-sync.sh
# 自动 commit + push ~/notes/ 的变更到 GitHub

set -e

cd /home/ubuntu/notes

# 检查是否有变更
if [ -z "$(git status --porcelain)" ]; then
    exit 0  # 没变更，静默退出
fi

# 添加所有变更
git add -A

# 自动 commit，带上时间戳
git commit -m "📝 笔记自动同步 $(date '+%Y-%m-%d %H:%M')"

# push 到 GitHub
git push origin main 2>&1

echo "✅ Notes synced: $(date)"
