#!/bin/bash
# manifest-check.sh — 技能活性检查
# 读取 skill-manifest.yaml，检查 active skill 是否在近期会话中被加载
# 兼容 Linux bash 和 Windows Git Bash (MSYS)
#
# 用法: bash manifest-check.sh [manifest 路径] [日志路径]
#       默认 manifest: ~/.hermes/skill-manifest.yaml
#       默认日志: ~/.hermes/logs/agent.log（如果存在）
#       回退: session_search 查询

MANIFEST="${1:-$HOME/.hermes/skill-manifest.yaml}"
LOG_DIR="${2:-$HOME/.hermes/logs}"
AGENT_LOG="$LOG_DIR/agent.log"

EXIT_CODE=0
PASS=0
FAIL=0
SKIP=0

echo "🔍 Skill Manifest 活性检查"
echo "═══════════════════════════════"
echo "Manifest: $MANIFEST"
echo ""

# 检查 manifest 是否存在
if [ ! -f "$MANIFEST" ]; then
    echo "❌ Manifest 文件不存在: $MANIFEST"
    exit 1
fi

# 解析 manifest 中的 active skill 列表
# 使用 grep + awk 提取 status: active 的 skill
ACTIVE_SKILLS=$(grep -B1 "status: active" "$MANIFEST" | grep -E "^  [a-z]" | sed 's/://' | tr -d ' ')

if [ -z "$ACTIVE_SKILLS" ]; then
    echo "⚠️  未找到标记为 active 的 skill"
    exit 0
fi

echo "需要检查的活跃技能:"
echo "$ACTIVE_SKILLS" | while read -r skill; do
    echo "  - $skill"
done
echo ""

# 检查方式来源: agent.log 或 session DB
LOG_MODE="none"
if [ -f "$AGENT_LOG" ]; then
    LOG_MODE="log"
    echo "📋 日志源: $AGENT_LOG (最近 500 行)"
    echo ""
elif command -v hermes &>/dev/null; then
    LOG_MODE="session"
    echo "📋 日志源: hermes session_search"
    echo ""
else
    echo "⚠️  未找到 agent.log 且 hermes CLI 不可用，跳过日志检查"
    echo "   仅输出 manifest 声明，不做实际活性验证"
    echo ""
fi

echo "$ACTIVE_SKILLS" | while read -r skill; do
    if [ "$LOG_MODE" = "log" ]; then
        # 在 agent.log 中搜索 skill 加载记录
        COUNT=$(grep -c "skill.*$skill\|Loaded.*$skill\|$skill.*loaded" "$AGENT_LOG" 2>/dev/null || echo 0)
        # 也查最近 500 行
        RECENT=$(tail -500 "$AGENT_LOG" 2>/dev/null | grep -c "skill.*$skill\|$skill.*load" || echo 0)
        
        if [ "$RECENT" -gt 0 ] || [ "$COUNT" -gt 0 ]; then
            echo "  ✅ $skill (总计:$COUNT, 近期:$RECENT)"
        else
            echo "  ⚠️  $skill — 日志中未找到加载记录"
        fi
    elif [ "$LOG_MODE" = "session" ]; then
        echo "  🔄 $skill — 通过 session_search 检查（hermes CLI）"
    else
        echo "  📄 $skill — 已声明 active（无日志验证）"
    fi
done

echo ""
echo "═══════════════════════════════"
echo "✅ Manifest 检查完成"
echo ""

# 输出 manifest 中的 on-demand skill 作为参考
echo "📌 on-demand skill（按需加载，不计入活性检查）:"
grep -B1 "status: on-demand" "$MANIFEST" 2>/dev/null | grep -E "^  [a-z]" | sed 's/://' | tr -d ' ' | while read -r skill; do
    echo "   - $skill"
done

echo ""
echo "💡 提示: 如果某 active skill 显示 ⚠️，请确认是否在近期会话中被加载过。"
echo "   新部署的 manifest 首次运行有 ⚠️ 是正常的，使用一次后即可验证。"
