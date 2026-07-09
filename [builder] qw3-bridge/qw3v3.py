#!/usr/bin/env python3
"""
qw3.v3 — 三方协作终端
你 (驾驶员) + Builder (本地 Hermes Agent) + Pioneer (云端 Hermes)

设计哲学：你驾驶，AI 是工具。阶段锁 + 工程模式，不改主循环。

Usage:
  python qw3v3.py

Commands:
  @pioneer <msg>    → Pioneer (云端 DeepSeek)
  @builder <msg>    → Builder (本地 Hermes Agent)
  @hermes <msg>     → 双方按当前模式广播
  <msg>             → 默认 Builder

  /phase <plan|execute|review>  切换阶段
  /pattern <name>               切换工程模式
  /status                       当前阶段/模式/成本
  /help                         帮助
  /quit                         退出
"""

import re
import subprocess
import shlex
import sys
import threading
import os
import copy
import atexit
import json
from enum import Enum
from datetime import datetime

# ── Platform compat ───────────────────────────────────
_CREATION_FLAGS = {}
if sys.platform == "win32":
    _CREATION_FLAGS["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
CLOUD_SSH_HOST = "TencentCloud"
HERMES_CHAT_CMD = "hermes chat -q"
BUILDER_MAX_TURNS = 3
LOG_DIR = os.path.expanduser("~/.hermes/qw3-logs")

# ── Colors ──────────────────────────────────────────
C = {
    "reset": "\033[0m",
    "pioneer": "\033[1;34m",   # blue
    "builder": "\033[1;32m",   # green
    "user": "\033[1;33m",      # yellow
    "system": "\033[1;35m",    # magenta
    "hermes": "\033[1;36m",    # cyan
    "dim": "\033[2m",
    "bold": "\033[1m",
    "red": "\033[1;31m",
}


# ══════════════════════════════════════════════════════
#  三阶段状态机
# ══════════════════════════════════════════════════════

class Phase(Enum):
    PLAN = "plan"
    EXECUTE = "execute"
    REVIEW = "review"


# 工程模式定义
PATTERNS = {
    "监督编码": {
        Phase.PLAN:    {"routes": ["@pioneer", "@builder", "@hermes"], "broadcast": "parallel"},
        Phase.EXECUTE: {"routes": ["@builder"],                        "broadcast": "serial"},
        Phase.REVIEW:  {"routes": ["@pioneer"],                        "broadcast": "serial"},
    },
    "平权讨论": {
        Phase.PLAN:    {"routes": ["@pioneer", "@builder", "@hermes"], "broadcast": "parallel"},
        Phase.EXECUTE: {"routes": ["@pioneer", "@builder"],            "broadcast": "serial"},
        Phase.REVIEW:  {"routes": ["user"],                            "broadcast": "serial"},
    },
    "快速试错": {
        Phase.PLAN:    {"routes": ["@builder"], "broadcast": "serial"},
        Phase.EXECUTE: {"routes": ["@builder"], "broadcast": "serial"},
        Phase.REVIEW:  {"routes": ["@builder"], "broadcast": "serial"},
    },
}


# ══════════════════════════════════════════════════════
#  活动日志 + 成本追踪
# ══════════════════════════════════════════════════════

class ActivityLog:
    def __init__(self):
        self.entries = []

    def add(self, turn, agent=None, action=None, cost=None, tool=None, user=False, **kw):
        """追加一条日志，turn 由调用方（route）传入"""
        entry = {"turn": turn, "action": action}
        if agent:
            entry["agent"] = agent
        if cost:
            entry["cost"] = cost
        if tool:
            entry["tool"] = tool
        if user:
            entry["user"] = True
        entry.update(kw)
        self.entries.append(entry)


class CostTracker:
    def __init__(self):
        self.acc = {
            "pioneer": {"tokens": 0, "cost": 0.0},
            "builder": {"tokens": 0, "cost": 0.0},
        }

    def record(self, agent, tokens, cost):
        self.acc[agent]["tokens"] += tokens
        self.acc[agent]["cost"] += cost

    def snapshot(self):
        return copy.deepcopy(self.acc)


# ══════════════════════════════════════════════════════
#  Builder 行为契约（每次 @builder 注入）
#  优先从 skill references 加载，硬编码兜底
# ══════════════════════════════════════════════════════

def _load_contract() -> str:
    """加载行为契约，优先从 skill references 加载，硬编码兜底"""
    # 从脚本所在目录的上级 references/ 定位
    script_dir = os.path.realpath(os.path.dirname(__file__))
    path = os.path.join(script_dir, "..", "references", "builder-contract.md")
    path = os.path.abspath(path)
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read().strip()
            # 去掉 YAML frontmatter（如果有）
            if text.startswith("---"):
                parts = text.split("---", 2)
                if len(parts) >= 3:
                    text = parts[2].strip()
            # 提取 ``` 代码块中的契约内容
            import re as _re
            m = _re.search(r"```(.*?)```", text, _re.DOTALL)
            if m:
                text = m.group(1).strip()
            return text
    except (FileNotFoundError, IOError):
        return _FALLBACK_CONTRACT

_FALLBACK_CONTRACT = """[Builder 约束]
你是一个工程执行 Agent，职责是写代码、跑测试、改配置。遵守以下规则：

1. 【危险命令安全】遇到 rm -rf /（或任何根目录递归删除）、dd if=、chmod -R 777、
   删除 /etc /boot /var/log 等系统目录、关闭防火墙/安全策略等操作 →
   汇报操作内容和风险，交给主会话决定。不自行执行。

2. 【受保护文件】不修改以下文件：
   - config.yaml（Hermes 主配置）
   - .env（环境变量/密钥）
   - SOUL.md / USER.md / MEMORY.md（个人 Agent 行为准则）
   - state.db（会话状态数据库）
   如需改动，汇报给主会话。

3. 【代码审查顺序】涉及多个文件的代码审查/修改时：
   步骤一：先扫完所有相关文件，收集完整信息
   步骤二：统一汇报问题清单（文件→问题→建议修复）
   步骤三：等下一步指令再动手改

4. 【禁止编数据】拿不到的确切数字（token 数、费用、时间、基准测试结果等）
   直接说「未知/未能获取」不说假数字。估算必须标注「此为估算」。

5. 【输出格式】每个输出以以下格式开头：
   📁 文件: <当前操作文件路径>
   🎯 目标: <本轮要做什么>
   （如果涉及多个文件，列出清单）

6. 【透明工具调用】每次工具调用（terminal / file 操作）在输出中说明
   「执行了什么 / 返回了什么 / 下一步计划」
"""

BUILDER_CONTRACT = _load_contract()


# ══════════════════════════════════════════════════════
#  协议标记解析
# ══════════════════════════════════════════════════════

MARKS = {
    "REVIEW_OK":      r"\[REVIEW:OK\]",
    "REVIEW_CHANGE":  r"\[REVIEW:CHANGE:(.*?)\]",
    "INPUT_REQUIRED": r"\[INPUT_REQUIRED\]",
    "BLOCKED":        r"\[BLOCKED\]",
}


def parse_response(text: str) -> dict:
    """解析协议标记，返回 {text, marks, clean}"""
    result = {"text": text, "marks": []}
    for name, pattern in MARKS.items():
        if re.search(pattern, text):
            result["marks"].append(name)
            text = re.sub(pattern, "", text)
    result["clean"] = text.strip()
    return result


# ══════════════════════════════════════════════════════
#  核心引擎
# ══════════════════════════════════════════════════════

class QW3Engine:
    def __init__(self):
        self.phase = Phase.PLAN
        self.pattern = "监督编码"
        self.rules = PATTERNS[self.pattern]
        self.log = ActivityLog()
        self.cost = CostTracker()
        self.turn = 0                     # 用户交互轮次计数器
        self._lock = threading.Lock()     # 线程安全锁

    # ── 路由 ──────────────────────────────────────

    def route(self, raw: str) -> str | dict:
        """阶段锁 + 路由转发"""
        self.turn += 1

        if raw.startswith("@"):
            parts = raw.split(" ", 1)
            cmd = parts[0]
            msg = parts[1] if len(parts) > 1 else ""
        else:
            cmd = "@builder"
            msg = raw

        # 阶段锁检查
        allowed = self.rules[self.phase]["routes"]
        if cmd not in allowed:
            return f"[BLOCKED] 当前阶段 {self.phase.value} 不允许 {cmd}"

        # 路由转发
        if cmd == "@pioneer":
            return self._call_pioneer(msg)
        elif cmd == "@builder":
            return self._call_builder(msg)
        elif cmd == "@hermes":
            return self._call_hermes(msg, self.rules[self.phase].get("broadcast", "parallel"))
        else:
            return f"[ERROR] 未知路由: {cmd}"

    # ── 阶段管理 ──────────────────────────────────

    def set_phase(self, new_phase: Phase):
        """阶段流转 → 审批点（成本快照 + 确认）"""
        cost = self.cost.snapshot()
        print(f"\n{C['dim']}📊 成本快照: "
              f"Pioneer {cost['pioneer']['cost']}¥ ({cost['pioneer']['tokens']} tokens) | "
              f"Builder {cost['builder']['cost']}¥ ({cost['builder']['tokens']} tokens){C['reset']}")
        try:
            confirm = input(f"{C['user']}→ 确认进入 [{new_phase.value}] 阶段? [Y/n] {C['reset']}")
        except EOFError:
            confirm = "y"  # 管道模式下自动放行
        except (KeyboardInterrupt, SystemExit):
            print(f"\n{C['system']}[CANCEL] 取消阶段流转{C['reset']}")
            return False
        if confirm.lower() in ("n", "no"):
            print(f"{C['system']}[BLOCKED] 用户拒绝: 留在 {self.phase.value} 阶段{C['reset']}")
            return False
        self.phase = new_phase
        self.log.add(turn=self.turn, user=True, action="phase_transition", to=new_phase.value)
        print(f"{C['system']}✓ 已进入 [{new_phase.value}] 阶段{C['reset']}")
        return True

    def set_pattern(self, name: str):
        """切换工程模式（带校验）"""
        if name not in PATTERNS:
            raise ValueError(f"未知模式: '{name}', 可选: {list(PATTERNS.keys())}")
        self.pattern = name
        self.rules = PATTERNS[name]
        print(f"{C['system']}✓ 已切换到模式: {name}{C['reset']}")

    # ── 成本估算 ──────────────────────────────────

    def _estimate_cost(self, result) -> dict:
        """从 subprocess.run 结果粗略估算 token 消耗"""
        text = (result.stdout or "") + (result.stderr or "")
        return self._estimate_cost_str(text)

    def _estimate_cost_str(self, text: str) -> dict:
        """从文本粗略估算 token 消耗"""
        raw_tokens = len(text) // 4            # 中文约 2 字/token，粗略
        tokens = max(raw_tokens, 100)          # 兜底：至少 100 tokens
        cost = tokens * 0.000002               # DeepSeek Flash ¥2/M tokens
        return {"tokens": tokens, "cost": round(cost, 4)}

    def _fmt_cost(self, cost_dict: dict) -> str:
        """格式化成本显示"""
        return f"{cost_dict['tokens']} tok / {cost_dict['cost']}¥"

    # ── @pioneer ──────────────────────────────────

    def _call_pioneer(self, msg, silent=False):
        """SSH → 云端 Hermes，Popen 逐行输出"""
        # 用 shlex.join 构造远程 shell 命令，确保 -q 参数完整
        remote_cmd = shlex.join(["hermes", "chat", "-q", msg, "-Q"])
        cmd = ["ssh", CLOUD_SSH_HOST, remote_cmd]
        proc = None
        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    text=True, stdin=subprocess.DEVNULL,
                                    **_CREATION_FLAGS)
            output = []
            for line in proc.stdout:
                if not silent:
                    print(f"  {C['pioneer']}☁️ │{C['reset']} {line}", end="", flush=True)
                output.append(line)
            proc.wait(timeout=60)
            proc.stdout.close()
            result = "".join(output)
            cost = self._estimate_cost_str(result)
            with self._lock:
                self.log.add(turn=self.turn, agent="pioneer", action="ask", cost=cost)
                self.cost.record("pioneer", cost["tokens"], cost["cost"])
            return result
        except subprocess.TimeoutExpired:
            if proc:
                proc.kill()
                proc.wait()
            err = "[ERROR] Pioneer 超时 (60s)"
            print(f"  {C['red']}☁️ │ {err}{C['reset']}")
            return err
        except Exception as e:
            err = f"[ERROR] Pioneer 调用失败: {e}"
            print(f"  {C['red']}☁️ │ {err}{C['reset']}")
            return err

    # ── @builder ──────────────────────────────────

    def _call_builder(self, msg, silent=False):
        """本地 Hermes Agent，注入行为契约，阻塞等完成"""
        full_prompt = f"{BUILDER_CONTRACT}\n\n---\n\n用户消息: {msg}"
        try:
            cmd = [HERMES_CHAT_CMD.split()[0], "chat", "-q", full_prompt,
                   "--max-turns", str(BUILDER_MAX_TURNS), "-Q"]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120,
                                    stdin=subprocess.DEVNULL,
                                    **_CREATION_FLAGS)
            output = result.stdout.strip()
            if not silent:
                for line in output.split("\n"):
                    print(f"  {C['builder']}🔧 │{C['reset']} {line}")
            cost = self._estimate_cost(result)
            with self._lock:
                self.log.add(turn=self.turn, agent="builder", action="reply", cost=cost)
                self.cost.record("builder", cost["tokens"], cost["cost"])
            return result.stdout
        except subprocess.TimeoutExpired:
            err = "[ERROR] Builder 超时 (120s)"
            print(f"  {C['red']}🔧 │ {err}{C['reset']}")
            return err
        except Exception as e:
            err = f"[ERROR] Builder 调用失败: {e}"
            print(f"  {C['red']}🔧 │ {err}{C['reset']}")
            return err

    # ── @hermes ───────────────────────────────────

    def _call_hermes(self, msg, mode="parallel"):
        """按广播策略调用"""
        if mode == "parallel":
            return self._broadcast_parallel(msg)
        else:
            return self._broadcast_serial(msg)

    def _broadcast_parallel(self, msg):
        """并行广播：threading 同时调用两边，固定顺序输出"""
        results = {}
        lock = threading.Lock()

        def run_agent(name, fn, silent):
            try:
                r = fn(msg, silent=silent)
                with lock:
                    results[name] = r
            except Exception as e:
                with lock:
                    results[name] = f"[ERROR] {e}"

        threads = [
            threading.Thread(target=run_agent, args=("pioneer", self._call_pioneer, True)),
            threading.Thread(target=run_agent, args=("builder", self._call_builder, True)),
        ]
        for th in threads:
            th.start()
        for th in threads:
            th.join()

        # 固定顺序输出
        pioneer_cost = self._estimate_cost_str(results.get("pioneer", ""))
        builder_cost = self._estimate_cost_str(results.get("builder", ""))
        print(f"\n{C['hermes']}━━━ ☁️  Pioneer ━━━  [{self._fmt_cost(pioneer_cost)}]{C['reset']}")
        print(results.get("pioneer", "(无响应)"))
        print(f"\n{C['hermes']}━━━ 🔧  Builder ━━━  [{self._fmt_cost(builder_cost)}]{C['reset']}")
        print(results.get("builder", "(无响应)"))
        self.log.add(turn=self.turn, agent="hermes", action="broadcast_parallel",
                     cost={"pioneer": pioneer_cost, "builder": builder_cost})
        return results

    def _broadcast_serial(self, msg):
        """串行广播：先 pioneer（静默），再把结果给 builder"""
        pioneer_rsp = self._call_pioneer(msg, silent=True)
        pioneer_cost = self._estimate_cost_str(pioneer_rsp)
        print(f"\n{C['hermes']}━━━ ☁️  Pioneer ━━━  [{self._fmt_cost(pioneer_cost)}]{C['reset']}")
        print(pioneer_rsp)

        builder_msg = f"上文 (Pioneer): {pioneer_rsp}\n\n请回应: {msg}"
        builder_rsp = self._call_builder(builder_msg, silent=True)
        builder_cost = self._estimate_cost_str(builder_rsp)
        print(f"\n{C['hermes']}━━━ 🔧  Builder ━━━  [{self._fmt_cost(builder_cost)}]{C['reset']}")
        print(builder_rsp)

        self.log.add(turn=self.turn, agent="hermes", action="broadcast_serial",
                     cost={"pioneer": pioneer_cost, "builder": builder_cost})
        return {"pioneer": pioneer_rsp, "builder": builder_rsp}


# ══════════════════════════════════════════════════════
#  主循环
# ══════════════════════════════════════════════════════

HELP_TEXT = f"""
{C['system']}┌─ qw3.v3 三方协作终端 ──────────────────────────────────┐
│                                                      │
│  {C['pioneer']}@pioneer <msg>{C['system']}     → Pioneer (云端 DeepSeek)        │
│  {C['builder']}@builder <msg>{C['system']}     → Builder (本地 Hermes Agent)     │
│  {C['hermes']}@hermes <msg>{C['system']}     → 按当前模式广播                  │
│  {C['user']}<msg>{C['system']}            → 默认 Builder                    │
│                                                      │
│  {C['system']}/phase <plan|execute|review>  切换阶段               │
│  /pattern <监督编码|平权讨论|快速试错> 切换模式     │
│  /status                       当前状态 + 协作成本       │
│  /cost                          每轮成本明细              │
│  /help                          显示此帮助                │
│  /quit                          退出                  │
│                                                      │
└──────────────────────────────────────────────────────┘{C['reset']}
"""


def print_status(engine: QW3Engine):
    """显示当前状态（含各 Agent 成本 + 最近 5 轮协作成本）"""
    cost = engine.cost.snapshot()
    allowed = engine.rules[engine.phase]["routes"]
    
    # 最近 5 轮协作成本
    collab_entries = [e for e in engine.log.entries[-20:] 
                     if e.get("action","") in ("broadcast_parallel","broadcast_serial")]
    collab_summary = ""
    for e in collab_entries[-5:]:
        c = e.get("cost", {})
        if isinstance(c, dict) and "pioneer" in c:
            p = c["pioneer"]
            b = c["builder"]
            collab_summary += f"  · Turn {e['turn']} [{e['action'].replace('broadcast_','')}]  "
            collab_summary += f"Pioneer {p['tokens']}tok  Builder {b['tokens']}tok\n"
    
    print(f"""
{C['system']}═════════════════ qw3.v3 状态 ═════════════════{C['reset']}
  {C['bold']}阶段:{C['reset']}     {engine.phase.value}
  {C['bold']}模式:{C['reset']}     {engine.pattern}
  {C['bold']}广播:{C['reset']}     {engine.rules[engine.phase].get("broadcast", "parallel")}
  {C['bold']}允许路由:{C['reset']}  {', '.join(allowed)}
  {C['bold']}交互轮次:{C['reset']}  {engine.turn}
  {C['bold']}日志条目:{C['reset']}  {len(engine.log.entries)}
  {C['bold']}协作成本 (累计):{C['reset']}
    {C['pioneer']}Pioneer:{C['reset']}  {cost['pioneer']['tokens']} tok / {cost['pioneer']['cost']}¥
    {C['builder']}Builder:{C['reset']}  {cost['builder']['tokens']} tok / {cost['builder']['cost']}¥
    {C['dim']}对比: {_ratio_str(cost)}{C['reset']}
  {C['bold']}最近协作:{C['reset']}
{collab_summary}{C['system']}════════════════════════════════════════════════{C['reset']}
""")

def _ratio_str(cost) -> str:
    """Pioneer vs Builder 消耗比例"""
    p = cost['pioneer']['tokens']
    b = cost['builder']['tokens']
    total = p + b
    if total == 0:
        return "尚无数据"
    return f"Pioneer {p/total*100:.0f}% / Builder {b/total*100:.0f}%"

def print_cost_detail(engine: QW3Engine):
    """显示每轮成本明细"""
    if not engine.log.entries:
        print(f"  {C['dim']}尚无成本数据{C['reset']}")
        return
    print(f"\n{C['system']}━━━ 每轮成本明细 ━━━{C['reset']}")
    for e in engine.log.entries:
        c = e.get("cost")
        if not c:
            continue
        agent = e.get("agent", "?")
        action = e.get("action", "?")
        turn = e.get("turn", "?")
        if isinstance(c, dict) and "tokens" in c:
            print(f"  · Turn {turn}  {agent:<10} {action:<20}  {c['tokens']:>5} tok  {c['cost']}¥")
        elif isinstance(c, dict) and "pioneer" in c:
            p = c["pioneer"]
            b = c["builder"]
            print(f"  · Turn {turn}  {agent:<10} {action:<20}  P:{p['tokens']}tok  B:{b['tokens']}tok")
    print()


def _dump_log(engine: QW3Engine):
    """退出时将日志写入 JSON Lines 文件"""
    if not engine.log.entries:
        return
    os.makedirs(LOG_DIR, exist_ok=True)
    fname = datetime.now().strftime("%Y-%m-%d-%H%M%S") + ".q3log"
    fpath = os.path.join(LOG_DIR, fname)
    try:
        with open(fpath, "w", encoding="utf-8") as f:
            for entry in engine.log.entries:
                # turn 转 int 确保 JSON 可序列化
                entry["turn"] = int(entry.get("turn", 0))
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        print(f"{C['dim']}📝 日志已保存: {fpath}{C['reset']}")
    except Exception as e:
        print(f"{C['red']}⚠️ 日志写入失败: {e}{C['reset']}")


def main():
    engine = QW3Engine()
    atexit.register(_dump_log, engine)

    print(f"{C['system']}")
    print("╔══════════════════════════════════════════╗")
    print("║       qw3.v3 · 三方协作终端              ║")
    print("║   你 + Builder + Pioneer                 ║")
    print("╚══════════════════════════════════════════╝")
    print(f"{C['reset']}")
    print(f"  {C['dim']}阶段: {engine.phase.value} | 模式: {engine.pattern}{C['reset']}")
    print(f"  @pioneer / @builder / @hermes  |  /help 查看命令")
    print()

    while True:
        try:
            raw = input(f"{C['user']}>>> {C['reset']}").strip()
        except (KeyboardInterrupt, EOFError):
            print(f"\n{C['system']}bye{C['reset']}")
            break

        if not raw:
            continue

        # ── 内部命令 ──
        if raw in ("/quit", "/q", "/exit"):
            break
        elif raw in ("/help", "/h"):
            print(HELP_TEXT)
            continue
        elif raw == "/status":
            print_status(engine)
            continue
        elif raw == "/cost":
            print_cost_detail(engine)
            continue
        elif raw.startswith("/phase "):
            name = raw.split(" ", 1)[1].lower()
            phase_map = {"plan": Phase.PLAN, "execute": Phase.EXECUTE, "review": Phase.REVIEW}
            if name not in phase_map:
                print(f"{C['red']}未知阶段: {name} (可选: plan, execute, review){C['reset']}")
                continue
            engine.set_phase(phase_map[name])
            continue
        elif raw.startswith("/pattern "):
            name = raw.split(" ", 1)[1]
            try:
                engine.set_pattern(name)
            except ValueError as e:
                print(f"{C['red']}{e}{C['reset']}")
            continue
        elif raw.startswith("/"):
            print(f"{C['red']}未知命令: {raw}. 输入 /help 查看.{C['reset']}")
            continue

        # ── 路由转发 ──
        print()  # 空行，让输出跟提示分开
        result = engine.route(raw)
        # 如果 route 返回了字符串且不是 @hermes（@hermes 自己打印了），打印它
        if isinstance(result, str) and result.startswith("[BLOCKED]"):
            print(f"  {C['red']}⛔ {result}{C['reset']}")
        elif isinstance(result, str) and result.startswith("[ERROR]"):
            print(f"  {C['red']}{result}{C['reset']}")
        # @hermes parallel/serial 已经自行打印了输出，不需要额外处理
        print()


if __name__ == "__main__":
    main()
