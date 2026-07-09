#!/usr/bin/env bash
# ============================================================
# snapshot.sh — 快照备份（rsync 硬链接式增量备份）
# 用法: ./snapshot.sh [备注]
# ============================================================
set -euo pipefail

SNAPSHOT_DIR="/home/ubuntu/.hermes-snapshots"
SOURCE_DIRS=(
    "/home/ubuntu/python-learning"
    "/home/ubuntu/.hermes/SOUL.md"
    "/home/ubuntu/.hermes/USER.md"
    "/home/ubuntu/.hermes/memories/MEMORY.md"
    "/home/ubuntu/.hermes/review-notes.md"
    "/home/ubuntu/.hermes/skills"
)
MAX_SNAPSHOTS=20
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
NOTE="${1:-auto}"

mkdir -p "$SNAPSHOT_DIR"

# 找到上一次快照做 link-dest
LATEST=$(ls -1 "$SNAPSHOT_DIR" 2>/dev/null | grep '^snapshot_' || true | sort | tail -1)
LINK_DEST=""
if [ -n "$LATEST" ]; then
    LINK_DEST="--link-dest=$SNAPSHOT_DIR/$LATEST/data"
fi

SNAPSHOT_PATH="$SNAPSHOT_DIR/snapshot_${TIMESTAMP}__${NOTE}"
mkdir -p "$SNAPSHOT_PATH/data"

echo "[snapshot] 开始快照: $SNAPSHOT_PATH"

for src in "${SOURCE_DIRS[@]}"; do
    if [ -e "$src" ]; then
        rel=$(echo "$src" | sed 's|^/home/ubuntu||')
        mkdir -p "$SNAPSHOT_PATH/data/$(dirname "$rel")"
        rsync -a --delete $LINK_DEST "$src" "$SNAPSHOT_PATH/data/$rel" 2>/dev/null || true
    fi
done

echo "$TIMESTAMP $NOTE" >> "$SNAPSHOT_DIR/snapshots.log"

# 清理旧快照
COUNT=$(ls -1d "$SNAPSHOT_DIR"/snapshot_* 2>/dev/null | wc -l)
if [ "$COUNT" -gt "$MAX_SNAPSHOTS" ]; then
    ls -1d "$SNAPSHOT_DIR"/snapshot_* 2>/dev/null | sort | head -n $((COUNT - MAX_SNAPSHOTS)) | while read -r old; do
        rm -rf "$old"
        echo "[snapshot] 清理旧快照: $old"
    done
fi

echo "[snapshot] 完成 ✅  剩余快照: $(ls -1 "$SNAPSHOT_DIR" | grep '^snapshot_' | wc -l)"
