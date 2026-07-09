#!/bin/bash
# soul-selfcheck.sh — SOUL.md 完整性自检
# 检查关键安全禁令和文件边界是否完整
# 兼容 Linux bash 和 Windows Git Bash (MSYS)
#
# 用法: bash soul-selfcheck.sh [SOUL.md 路径]
#       默认路径: ~/.hermes/SOUL.md

SOUL="${1:-$HOME/.hermes/SOUL.md}"
USER_MEM_DIR="${2:-$HOME/.hermes/memories}"

EXIT_CODE=0
PASS=0
FAIL=0
WARN=0

check_contains() {
    local file="$1"
    local pattern="$2"
    local label="$3"
    local severity="${4:-ERROR}"  # ERROR / WARN

    if grep -qi "$pattern" "$file" 2>/dev/null; then
        echo "  ✅ $label"
        ((PASS++))
    else
        if [ "$severity" = "WARN" ]; then
            echo "  ⚠️  $label"
            ((WARN++))
        else
            echo "  ❌ $label"
            ((FAIL++))
            EXIT_CODE=1
        fi
    fi
}

echo "🔍 SOUL.md 自检报告"
echo "═══════════════════════════"
echo "检查文件: $SOUL"
echo ""

# 1. 文件存在性检查
echo "📂 文件存在性"
if [ -f "$SOUL" ]; then
    echo "  ✅ SOUL.md 存在"
    ((PASS++))
else
    echo "  ❌ SOUL.md 不存在!"
    ((FAIL++))
    EXIT_CODE=1
fi

# USER.md 和 MEMORY.md
for f in USER.md MEMORY.md; do
    if [ -f "$USER_MEM_DIR/$f" ]; then
        echo "  ✅ $f 存在 ($(wc -m < "$USER_MEM_DIR/$f" 2>/dev/null || echo 0) chars)"
        ((PASS++))
    else
        echo "  ⚠️  $f 不存在于 $USER_MEM_DIR"
        ((WARN++))
    fi
done

echo ""
echo "🔒 安全禁令段"

check_contains "$SOUL" "公开发布内容或对外上线" "发布禁令: 公开发布/对外上线"
check_contains "$SOUL" "没有我的.*批准.*绝不能执行\|以下事项.*绝不能执行" "执行红线: 未经批准绝不能执行"
check_contains "$SOUL" "删除重要工作或做不可逆修改" "删除禁令: 不可逆修改"
check_contains "$SOUL" "暴露私人信息" "隐私禁令: 暴露私人信息"
check_contains "$SOUL" "购买东西.*注册付费" "付费禁令: 购买/注册付费"
check_contains "$SOUL" "发送消息" "消息禁令: 向真实的人发送"
check_contains "$SOUL" "修改凭证.*安全设置" "安全禁令: 修改凭证/安全设置"

echo ""
echo "📋 文件边界规则"

check_contains "$SOUL" "SOUL.md.*宪法\|SOUL.*行为准则" "文件边界: SOUL.md 宪法地位"
check_contains "$SOUL" "USER.md" "文件边界: USER.md 提及"
check_contains "$SOUL" "MEMORY.md" "文件边界: MEMORY.md 提及"

echo ""
echo "📏 长回复控制"

check_contains "$SOUL" "上下文防爆\|长回复控制\|大于.*屏\|30K token" "长回复控制段" "WARN"
check_contains "$SOUL" "话题切换\|/new 开新会话" "话题切换提醒" "WARN"

echo ""
echo "💸 成本纪律"

check_contains "$SOUL" "T1.*T2.*T3\|供应商等级" "供应商等级体系" "WARN"
check_contains "$SOUL" "成本.*纪律\|成本是硬约束" "成本纪律认定" "WARN"
check_contains "$SOUL" "禁止编造数据" "禁止编造数据规则"

echo ""
echo "═══════════════════════════"
echo "结果: ✅ $PASS 通过 | ⚠️  $WARN 警告 | ❌ $FAIL 失败"
echo ""

if [ $FAIL -gt 0 ]; then
    echo "🔴 存在 $FAIL 项严重缺失，需要修复后重新自检"
else
    echo "🟢 SOUL.md 完整性检查通过"
fi

exit $EXIT_CODE
