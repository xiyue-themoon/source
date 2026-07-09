#!/usr/bin/env bash
# ============================================================
# health-check.sh — Hermes 核心依赖健康检查
# 返回: exit 0=健康  非0=异常
# 输出: JSON 格式报告
# ============================================================
set -u

FAILED=0
CHECKS=""

check() {
    local name="$1"
    local desc="$2"
    shift 2
    if "$@" >/dev/null 2>&1; then
        CHECKS="${CHECKS}{\"name\":\"$name\",\"status\":\"ok\",\"desc\":\"$desc\"},"
    else
        CHECKS="${CHECKS}{\"name\":\"$name\",\"status\":\"fail\",\"desc\":\"$desc\"},"
        FAILED=$((FAILED + 1))
    fi
}

# ── Python 环境 ──
check "python" "Python 解释器可用" python3 -c "print('ok')"
check "pip" "pip 包管理器可用" pip3 --version
check "trash-cli" "trash-cli 已安装" trash-put --version

# ── Hermes 核心文件 ──
check "hermes-soil" "SOUL.md 存在" test -f /home/ubuntu/.hermes/SOUL.md
check "hermes-skills" "skills 目录存在" test -d /home/ubuntu/.hermes/skills

# ── 工作区 ──
check "workspace" "python-learning 目录存在" test -d /home/ubuntu/python-learning
check "workspace-step" "核心教学文件存在" ls /home/ubuntu/python-learning/step*.py &>/dev/null
check "workspace-d2l" "d2l 目录存在" test -d /home/ubuntu/python-learning/d2l

# ── 系统工具 ──
check "bash" "bash 可用" bash --version
check "rsync" "rsync 可用" rsync --version
check "git" "git 可用" git --version

# ── 快照系统 ──
check "snapshot-dir" "快照目录存在" test -d /home/ubuntu/.hermes-snapshots
check "snapshot-script" "快照脚本存在" test -f /home/ubuntu/.hermes/scripts/snapshot.sh

# ── Hermes 核心依赖检查 ──
check "hermes-pip-core" "hermes 核心依赖 intact" python3 -c "
import sys
for mod in ['json', 'sqlite3', 'os', 'subprocess', 'shlex', 're']:
    __import__(mod)
print('ok')
"

# 输出 JSON
CHECKS="${CHECKS%,}"  # 去掉末尾逗号
echo "{"
echo "  \"timestamp\": \"$(date -Iseconds)\","
echo "  \"total_checks\": $(echo "$CHECKS" | grep -o '"status":"ok"\|"status":"fail"' | wc -l),"
echo "  \"failed\": $FAILED,"
echo "  \"healthy\": $( [ $FAILED -eq 0 ] && echo true || echo false ),"
echo "  \"checks\": [$CHECKS]"
echo "}"

exit $FAILED
