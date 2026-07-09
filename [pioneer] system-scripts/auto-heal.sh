#!/usr/bin/env bash
# ============================================================
# auto-heal.sh — 自动检测异常 → 回滚到最近快照
# 
# 逻辑：
#   1. 运行 health-check.sh
#   2. 如果健康 → 重置失败计数
#   3. 如果不健康 → 累加失败计数
#   4. 连续失败 N 次 → 自动回滚到最近快照
# ============================================================
set -u

FAIL_FILE="/home/ubuntu/.hermes/scripts/.autoheal_fail_count"
MAX_FAILS=3
SNAPSHOT_DIR="/home/ubuntu/.hermes-snapshots"
ROLLBACK_LOG="/home/ubuntu/.hermes-snapshots/autoheal.log"

# 读取当前失败计数
CURRENT_FAILS=0
if [ -f "$FAIL_FILE" ]; then
    CURRENT_FAILS=$(cat "$FAIL_FILE" 2>/dev/null || echo 0)
fi

# 运行健康检查
HEALTH_OUTPUT=$(bash /home/ubuntu/.hermes/scripts/health-check.sh 2>&1)
HEALTHY=$(echo "$HEALTH_OUTPUT" | grep '"healthy"' | grep -c 'true' || true)

if [ "$HEALTHY" -gt 0 ]; then
    # ✅ 健康 → 重置计数
    echo 0 > "$FAIL_FILE"
    exit 0
fi

# ❌ 不健康 → 累加
NEW_FAILS=$((CURRENT_FAILS + 1))
echo "$NEW_FAILS" > "$FAIL_FILE"

echo "[$(date -Iseconds)] 健康检查失败 #$NEW_FAILS/$MAX_FAILS" >> "$ROLLBACK_LOG"

if [ "$NEW_FAILS" -ge "$MAX_FAILS" ]; then
    echo "[$(date -Iseconds)] ⚠️  连续 $MAX_FAILS 次失败，触发自动回滚!" >> "$ROLLBACK_LOG"

    # 找到最近快照
    LATEST=$(ls -1d "$SNAPSHOT_DIR"/snapshot_* 2>/dev/null | sort | tail -1)
    if [ -z "$LATEST" ]; then
        echo "[$(date -Iseconds)] ❌ 没有可用快照，无法回滚" >> "$ROLLBACK_LOG"
        exit 2
    fi

    echo "[$(date -Iseconds)] 🔄 回滚到: $LATEST" >> "$ROLLBACK_LOG"

    # 回滚关键路径
    RESTORE_COUNT=0
    if [ -d "$LATEST/data/python-learning" ]; then
        rsync -a --delete "$LATEST/data/python-learning/" "/home/ubuntu/python-learning/"
        RESTORE_COUNT=$((RESTORE_COUNT + 1))
        echo "[$(date -Iseconds)]   ✓ python-learning 已恢复" >> "$ROLLBACK_LOG"
    fi
    if [ -f "$LATEST/data/.hermes/SOUL.md" ]; then
        cp "$LATEST/data/.hermes/SOUL.md" "/home/ubuntu/.hermes/SOUL.md"
        RESTORE_COUNT=$((RESTORE_COUNT + 1))
        echo "[$(date -Iseconds)]   ✓ SOUL.md 已恢复" >> "$ROLLBACK_LOG"
    fi
    if [ -d "$LATEST/data/.hermes/skills" ]; then
        rsync -a --delete "$LATEST/data/.hermes/skills/" "/home/ubuntu/.hermes/skills/"
        RESTORE_COUNT=$((RESTORE_COUNT + 1))
        echo "[$(date -Iseconds)]   ✓ skills 已恢复" >> "$ROLLBACK_LOG"
    fi

    echo "[$(date -Iseconds)] ✅ 回滚完成，恢复了 $RESTORE_COUNT 个路径" >> "$ROLLBACK_LOG"

    # 重置失败计数
    echo 0 > "$FAIL_FILE"

    # 输出报告供 cron 投递
    echo "🛡️ 自动回滚已触发"
    echo "   原因: 连续 $MAX_FAILS 次健康检查失败"
    echo "   快照: $(basename $LATEST)"
    echo "   恢复路径: $RESTORE_COUNT 个"
fi
