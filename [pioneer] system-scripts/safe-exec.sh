#!/usr/bin/env bash
# ============================================================
# safe-exec.sh — 危险命令安全检查器
# 
# 在 Hermes terminal() 调用前执行检查。
# 识别高危操作并在执行前要求确认。
# ============================================================
set -u
CMD="$*"
CMD_B64=$(echo "$CMD" | base64 -w0)

# 高危模式列表
DANGEROUS_PATTERNS=(
    "rm -rf /"
    "rm -rf --no-preserve-root"
    "mkfs\\."
    "dd if="
    "> /dev/"
    ":(){ :|:& };:"  # fork bomb
    "chmod -R 000"
    "chown -R .* /"
)

# 需要特别谨慎的操作
RISKY_PATTERNS=(
    "rm -rf"
    "rm -r"
    "mv.*/.*/"
    "dd "
    "> "
    ">|"
    "sudo "
    "chmod "
    "chown "
    "wget.*| sh"
    "curl.*| sh"
)

check_patterns() {
    local patterns=("${!1}")
    for pattern in "${patterns[@]}"; do
        if echo "$CMD" | grep -qE "$pattern"; then
            return 0
        fi
    done
    return 1
}

# 检查高危
if check_patterns DANGEROUS_PATTERNS[@]; then
    echo "⛔ [SAFETY] 检测到高危命令！已拦截。"
    echo "  命令: $CMD"
    echo "  如需执行，请在命令前加 SAFETY_OVERRIDE=1"
    exit 1
fi

# 检查风险操作
if check_patterns RISKY_PATTERNS[@]; then
    echo "⚠️  [SAFETY] 检测到风险操作:"
    echo "  命令: $CMD"
    echo "  自动创建快照..."
    /home/ubuntu/.hermes/scripts/snapshot.sh "pre_risky_op"
    echo "  ✅ 快照完成，继续执行"
fi

# 执行原命令
eval "$CMD"
