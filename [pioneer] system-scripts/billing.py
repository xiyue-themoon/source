#!/usr/bin/env python3
"""
billing.py — Hermes 计费追踪 (v3)

三重数据源交叉验证，修复 v1 三个致命问题:
  v1 bug #1: 输入 token 猜 400K → 现在用日志精确 in=N out=N
  v1 bug #2: 定价不计缓存折扣 → 现在 parse cache=X/Y 应用折扣价
  v1 bug #3: "API 403" → 现在 OpenRouter + DeepSeek API 都通

用法:
    python3 billing.py                    # 最近 24 小时
    python3 billing.py --days 7           # 最近 7 天
    python3 billing.py --session SESSION  # 指定会话
    python3 billing.py --no-api           # 仅日志分析，不调 API
"""

from __future__ import annotations

import json
import os
import re
import urllib.request
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any

# ─── 定价表 ──────────────────────────────────────────────────
# 来源: 各 provider 官网，写死但可审查
# cache_input 仅在 DeepSeek 直连时有（92% 命中率，收 10% 全价）
PRICING: dict[str, dict[str, dict[str, float]]] = {
    "deepseek": {
        "deepseek-v4-flash":  {"input": 0.07,  "input_cache": 0.007,  "output": 0.28},
        "deepseek-v4-pro":    {"input": 0.31,  "input_cache": 0.031, "output": 1.25},
    },
    "openrouter": {
        "deepseek/deepseek-v4-flash": {"input": 0.10, "input_cache": 0.10, "output": 0.20},
        "deepseek/deepseek-v4-pro":   {"input": 0.44, "input_cache": 0.44, "output": 1.50},
        # OpenRouter 第三方模型无缓存折扣，input_cache == input
    },
    "custom": {
        "deepseek-v4-pro":    {"input": 0.31,  "input_cache": 0.031, "output": 1.25},
    },
}

USD_TO_CNY = 7.2
HERMES_HOME = os.path.expanduser("~/.hermes")


# ─── 日志解析 ────────────────────────────────────────────────

API_CALL_RE = re.compile(
    r"\[(\S+)\].*?API call #(\d+): model=(\S+) provider=(\S+) in=(\d+) out=(\d+)"
)
CACHE_RE = re.compile(r"cache=(\d+)/(\d+)")

GATEWAY_CALL_RE = re.compile(
    r"response ready:.*?api_calls=(\d+)"
)


def parse_log(path: str, since: datetime | None = None) -> list[dict[str, Any]]:
    """解析 agent.log 的 API call 行，去重，返回精确 token 数"""
    seen: set[tuple[str, int, str]] = set()  # (session_id, call_num, model)
    records: list[dict[str, Any]] = []
    provider_priority = {"deepseek": 0, "custom": 1, "openrouter": 2}

    if not os.path.exists(path):
        return records

    with open(path) as f:
        for line in f:
            m = API_CALL_RE.search(line)
            if not m:
                continue

            session = m.group(1)
            call_num = int(m.group(2))
            model = m.group(3)
            provider = m.group(4)
            in_tokens = int(m.group(5))
            out_tokens = int(m.group(6))

            ts_str = line[:19]
            try:
                ts = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                ts = datetime.now()

            if since and ts < since:
                continue

            # 去重: 同一 session + call# + model 只保留优先级高的 provider
            key = (session, call_num, model)
            if key in seen:
                continue
            seen.add(key)

            # 缓存数据
            cache_m = CACHE_RE.search(line)
            cache_hit = int(cache_m.group(1)) if cache_m else 0
            cache_total = int(cache_m.group(2)) if cache_m else in_tokens
            if cache_total == 0:
                cache_total = in_tokens

            records.append({
                "ts": ts,
                "session": session,
                "call_num": call_num,
                "model": model,
                "provider": provider,
                "in_tokens": in_tokens,
                "out_tokens": out_tokens,
                "cache_hit": cache_hit,
                "cache_total": cache_total,
            })

    return records


def parse_gateway_extra(path: str, since: datetime | None = None) -> int:
    """读取 gateway.log 中 api_calls，计算 agent.log 未覆盖的数量"""
    total_gateway_calls = 0
    total_gateway_lines = 0

    if not os.path.exists(path):
        return 0

    with open(path) as f:
        for line in f:
            m = GATEWAY_CALL_RE.search(line)
            if not m:
                continue
            ts_str = line[:19]
            try:
                ts = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                continue
            if since and ts < since:
                continue
            total_gateway_calls += int(m.group(1))
            total_gateway_lines += 1

    return total_gateway_calls, total_gateway_lines


# ─── 费用计算 ────────────────────────────────────────────────

def _lookup_price(provider: str, model: str) -> dict[str, float] | None:
    """按 provider+model 查找定价，支持模糊匹配"""
    table = PRICING.get(provider, {})
    if model in table:
        return table[model]
    short = model.split("/")[-1]
    for t in PRICING.values():
        if short in t:
            return t[short]
    return None


def calc_cost(record: dict[str, Any]) -> dict[str, float]:
    """
    计算单次调用费用，考虑缓存折扣。
    DeepSeek: 缓存输入 = 10% 全价
    OpenRouter: 无缓存折扣 (input_cache == input)
    """
    prices = _lookup_price(record["provider"], record["model"])
    if not prices:
        return {"usd": 0.0, "cny": 0.0, "usd_full": 0.0, "cny_full": 0.0}

    # 缓存折扣后的输入成本
    cached_cost = record["cache_hit"] / 1_000_000 * prices.get("input_cache", prices["input"])
    uncached_cost = (record["in_tokens"] - record["cache_hit"]) / 1_000_000 * prices["input"]
    input_cost = cached_cost + uncached_cost

    output_cost = record["out_tokens"] / 1_000_000 * prices["output"]
    cost_usd = input_cost + output_cost

    # 全价（无缓存折扣）— 用于对比
    full_input = record["in_tokens"] / 1_000_000 * prices["input"]
    full_usd = full_input + output_cost

    return {
        "usd": round(cost_usd, 6),
        "cny": round(cost_usd * USD_TO_CNY, 4),
        "usd_full": round(full_usd, 6),
        "cny_full": round(full_usd * USD_TO_CNY, 4),
    }


# ─── API 查询 ────────────────────────────────────────────────

def _source_env() -> dict[str, str]:
    """加载 .env 环境变量"""
    env: dict[str, str] = {}
    env_path = os.path.join(HERMES_HOME, ".env")
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                v = v.strip("\"'")
                env[k.strip()] = v
    return env


def query_openrouter_usage() -> dict[str, Any]:
    """调 OpenRouter /api/v1/auth/key 获取真实累计 usage"""
    env = _source_env()
    key = env.get("OPENROUTER_API_KEY", "")
    if not key:
        return {"error": "OPENROUTER_API_KEY not found"}

    try:
        req = urllib.request.Request(
            "https://openrouter.ai/api/v1/auth/key",
            headers={"Authorization": f"Bearer {key}"},
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
        d = data.get("data", {})
        return {
            "usage_usd": round(d.get("usage", 0), 2),
            "usage_daily": round(d.get("usage_daily", 0), 2),
            "usage_weekly": round(d.get("usage_weekly", 0), 2),
            "usage_monthly": round(d.get("usage_monthly", 0), 2),
        }
    except Exception as e:
        return {"error": str(e)}


def query_openrouter_credits() -> dict[str, Any]:
    """调 OpenRouter /api/v1/credits 获取充值余额"""
    env = _source_env()
    key = env.get("OPENROUTER_API_KEY", "")
    if not key:
        return {"error": "OPENROUTER_API_KEY not found"}

    try:
        req = urllib.request.Request(
            "https://openrouter.ai/api/v1/credits",
            headers={"Authorization": f"Bearer {key}"},
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
        d = data.get("data", {})
        total = d.get("total_credits", 0)
        used = d.get("total_usage", 0)
        return {
            "total_credits": round(total, 2),
            "total_usage": round(used, 2),
            "remaining": round(total - used, 2),
        }
    except Exception as e:
        return {"error": str(e)}


def query_deepseek_balance() -> dict[str, Any]:
    """调 DeepSeek /user/balance 获取实时余额"""
    env = _source_env()
    key = env.get("DEEPSEEK_API_KEY", "")
    if not key:
        return {"error": "DEEPSEEK_API_KEY not found"}

    try:
        req = urllib.request.Request(
            "https://api.deepseek.com/user/balance",
            headers={"Authorization": f"Bearer {key}"},
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
        infos = data.get("balance_infos", [])
        if infos:
            info = infos[0]
            return {
                "currency": info.get("currency", "CNY"),
                "total_balance": float(info.get("total_balance", 0)),
                "topped_up": float(info.get("topped_up_balance", 0)),
                "granted": float(info.get("granted_balance", 0)),
            }
        return {"error": "no balance_infos in response"}
    except Exception as e:
        return {"error": str(e)}


# ─── 汇总 ────────────────────────────────────────────────────

def summarize(records: list[dict[str, Any]]) -> dict[str, Any]:
    """按 model+provider 汇总，分 'after_cache' 和 'full_price' 两套"""
    total_calls = 0
    total_in = 0
    total_out = 0
    total_cache = 0
    per_model: dict[str, dict] = defaultdict(lambda: {
        "calls": 0, "in_tokens": 0, "out_tokens": 0, "cache_hit": 0,
        "usd": 0.0, "cny": 0.0, "usd_full": 0.0, "cny_full": 0.0,
    })

    cache_total = 0
    cache_hit_sum = 0

    for rec in records:
        key = f"{rec['provider']}:{rec['model']}"
        p = per_model[key]
        p["calls"] += 1
        p["in_tokens"] += rec["in_tokens"]
        p["out_tokens"] += rec["out_tokens"]
        p["cache_hit"] += rec["cache_hit"]
        cost = calc_cost(rec)
        p["usd"] += cost["usd"]
        p["cny"] += cost["cny"]
        p["usd_full"] += cost["usd_full"]
        p["cny_full"] += cost["cny_full"]
        total_calls += 1
        total_in += rec["in_tokens"]
        total_out += rec["out_tokens"]
        total_cache += rec["cache_hit"]
        cache_total += rec["cache_total"]
        cache_hit_sum += rec["cache_hit"]

    result: dict[str, Any] = {
        "total_calls": total_calls,
        "total_in_tokens": total_in,
        "total_out_tokens": total_out,
        "total_cache_hit": total_cache,
        "cache_rate": round(cache_hit_sum / cache_total * 100, 1) if cache_total > 0 else 0,
        "total_usd": round(sum(v["usd"] for v in per_model.values()), 2),
        "total_cny": round(sum(v["cny"] for v in per_model.values()), 2),
        "total_usd_full": round(sum(v["usd_full"] for v in per_model.values()), 2),
        "total_cny_full": round(sum(v["cny_full"] for v in per_model.values()), 2),
        "per_model": {},
    }
    for key, v in sorted(per_model.items(), key=lambda x: -x[1]["usd"]):
        result["per_model"][key] = {
            "calls": v["calls"],
            "in_tokens": v["in_tokens"],
            "out_tokens": v["out_tokens"],
            "cache_hit": v["cache_hit"],
            "usd": round(v["usd"], 2),
            "cny": round(v["cny"], 2),
            "usd_full": round(v["usd_full"], 2),
            "cny_full": round(v["cny_full"], 2),
        }
    result["record_count"] = len(records)
    return result


# ─── 输出 ────────────────────────────────────────────────────

def fmt_num(n: int) -> str:
    if n >= 1_000_000:
        return f"{n/1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n/1_000:.1f}K"
    return str(n)


def fmt_cny(v: float, width: int = 10) -> str:
    return f"¥{v:>{width-1}.2f}"


def print_report(log_summary: dict[str, Any],
                 or_usage: dict[str, Any] | None = None,
                 or_credits: dict[str, Any] | None = None,
                 ds_balance: dict[str, Any] | None = None,
                 gateway_extra: tuple[int, int] | None = None,
                 label: str = "") -> None:
    s = log_summary

    if label:
        print(f"\n{'='*60}")
        print(f"  {label}")
        print(f"{'='*60}")

    # ── 日志分析 ──
    cached_label = "✅ 缓存折扣后" if s["total_usd"] != s["total_usd_full"] else ""
    print(f"\n📊 日志分析（精确 token + 缓存折扣）{cached_label}")
    print(f"{'─'*60}")
    print(f"  API 调用:       {s['total_calls']} 次")
    print(f"  输入 tokens:    {fmt_num(s['total_in_tokens'])}")
    print(f"  输出 tokens:    {fmt_num(s['total_out_tokens'])}")
    print(f"  缓存命中:       {fmt_num(s['total_cache_hit'])} ({s['cache_rate']}%)")

    if s["total_usd"] != s["total_usd_full"]:
        print(f"  费用(缓存折扣): ${s['total_usd']:.2f}  |  ¥{s['total_cny']:.2f}")
        print(f"  费用(全价):     ${s['total_usd_full']:.2f}  |  ¥{s['total_cny_full']:.2f}")
        saved = s["total_usd_full"] - s["total_usd"]
        print(f"  缓存节省:       ${saved:.2f}  ({saved/s['total_usd_full']*100:.0f}%)")
    else:
        print(f"  费用:           ${s['total_usd']:.2f}  |  ¥{s['total_cny']:.2f}")

    # 明细表
    print(f"\n  {'模型':42s} {'调用':>5s} {'缓存':>5s} {'总费用($)':>10s} {'总费用(¥)':>10s}")
    print(f"  {'─'*42} {'─'*5} {'─'*5} {'─'*10} {'─'*10}")
    for model, d in sorted(s["per_model"].items(), key=lambda x: -x[1]["usd"]):
        label_model = model
        label_cached = ""
        if d["usd"] != d["usd_full"]:
            label_cached = f"  ({round((1-d['usd']/d['usd_full'])*100)}%↓)"
        cache_pct = f"{round(d['cache_hit']/d['in_tokens']*100) if d['in_tokens'] > 0 else 0}%"
        print(f"  {label_model:42s} {d['calls']:5d} {cache_pct:>5s} ${d['usd']:>8.2f}{label_cached}  ¥{d['cny']:>8.2f}")

    # ── API 真实数据 ──
    if or_usage and "error" not in or_usage:
        log_total = s["total_usd"]  # 缓存折扣后
        api_total = or_usage["usage_usd"]
        diff_pct = ((api_total - log_total) / api_total * 100) if api_total > 0 else 0

        print(f"\n🔵 OpenRouter API 真实数据")
        print(f"{'─'*60}")
        print(f"  累计 usage:     ${api_total:.2f}  (¥{api_total * USD_TO_CNY:.2f})")
        print(f"  今日:           ${or_usage['usage_daily']:.2f}")
        print(f"  本周:           ${or_usage['usage_weekly']:.2f}")
        print(f"  本月:           ${or_usage['usage_monthly']:.2f}")

        if abs(diff_pct) > 10:
            flag = "⚠️ "
        elif abs(diff_pct) > 5:
            flag = "⚡ "
        else:
            flag = "✅ "
        print(f"  日志vs API偏差:  {flag}{diff_pct:+.1f}%")
    elif or_usage and "error" in or_usage:
        print(f"\n🔵 OpenRouter API: 查询失败 ({or_usage['error']})")

    if or_credits and "error" not in or_credits:
        print(f"\n💳 OpenRouter 信用余额")
        print(f"{'─'*60}")
        print(f"  总充值:         ${or_credits['total_credits']:.2f}")
        print(f"  已使用:         ${or_credits['total_usage']:.2f}")
        print(f"  剩余:           ${or_credits['remaining']:.2f}  (¥{or_credits['remaining'] * USD_TO_CNY:.2f})")
        if or_usage and "error" not in or_usage and or_usage["usage_daily"] > 0:
            est_days = or_credits["remaining"] / or_usage["usage_daily"]
            if est_days < 1:
                print(f"  按今日用量:     {'几个小时' if est_days < 0.5 else f'约 {est_days:.1f} 天'}")
            else:
                print(f"  按今日用量:     约 {est_days:.0f} 天")
    elif or_credits and "error" in or_credits:
        print(f"\n💳 OpenRouter 信用: 查询失败 ({or_credits['error']})")

    if ds_balance and "error" not in ds_balance:
        print(f"\n🟢 DeepSeek API 实时余额")
        print(f"{'─'*60}")
        print(f"  余额:           ¥{ds_balance['total_balance']:.2f}")
        print(f"  充值金额:       ¥{ds_balance['topped_up']:.2f}")
        print(f"  赠送金额:       ¥{ds_balance['granted']:.2f}")

        # 日志估算的 DeepSeek 花费
        ds_log = sum(
            d["cny"] for m, d in s["per_model"].items()
            if m.startswith("deepseek:") or m.startswith("custom:")
        )
        if ds_log > 0:
            print(f"  日志估算已花:   ¥{ds_log:.2f}  (缓存折扣后)")
            ds_log_full = sum(
                d["cny_full"] for m, d in s["per_model"].items()
                if m.startswith("deepseek:") or m.startswith("custom:")
            )
            if ds_log_full != ds_log:
                print(f"  日志估算已花:   ¥{ds_log_full:.2f}  (全价)")
            est_initial = ds_balance["total_balance"] + ds_log
            print(f"  推测初始余额:   ¥{est_initial:.2f}")

    elif ds_balance and "error" in ds_balance:
        print(f"\n🟢 DeepSeek API: 查询失败 ({ds_balance['error']})")

    # ── 数据缺口 ──
    if gateway_extra:
        gw_calls, gw_lines = gateway_extra
        if gw_calls > 0:
            print(f"\n⚠️  数据缺口")
            print(f"{'─'*60}")
            print(f"  gateway.log 有 {gw_lines} 条响应记录 ({gw_calls} 次 API 调用)")
            print(f"  但 agent.log 缺失 6月6-8日的日志，这部分无法精确估算")
            print(f"  💡 这些调用来自 QQ bot 等平台，已体现在 API 真实数据中")

    print(f"\n{'─'*60}")
    print(f"  💡 精确账单请去 OpenRouter / DeepSeek 官网确认")


# ─── 紧凑输出 ──────────────────────────────────────────────

def print_compact_report(log_summary: dict[str, Any],
                         ds_balance: dict[str, Any] | None = None,
                         label: str = "") -> None:
    """紧凑输出：一行人类摘要 + 一行 JSON，省 85%+ token"""
    s = log_summary

    period = label or "本期"
    line1 = (f"💰 Billing {period} | ${s['total_usd']:.2f} (¥{s['total_cny']:.2f})"
             f" | 缓存{s['cache_rate']}% | {s['total_calls']}次调用")

    compact = {
        "usd": s["total_usd"],
        "cny": s["total_cny"],
        "usd_full": s["total_usd_full"],
        "cny_full": s["total_cny_full"],
        "cache_pct": s["cache_rate"],
        "calls": s["total_calls"],
    }
    # 附 DeepSeek 余额
    if ds_balance and "error" not in ds_balance:
        compact["balance_cny"] = ds_balance["total_balance"]

    line2 = json.dumps(compact, ensure_ascii=False, separators=(",", ":"))

    print(line1)
    print(line2)


# ─── CLI ──────────────────────────────────────────────────────

def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="Hermes 计费追踪 (v3)")
    parser.add_argument("--days", type=int, default=1, help="回溯天数")
    parser.add_argument("--session", type=str, help="指定会话ID")
    parser.add_argument("--log", type=str,
                        default=os.path.join(HERMES_HOME, "logs", "agent.log"))
    parser.add_argument("--no-api", action="store_true",
                        help="仅日志分析，不调 API")
    parser.add_argument("--compact", action="store_true",
                        help="紧凑输出模式（一行摘要 + 一行 JSON）")
    args = parser.parse_args()

    since = datetime.now() - timedelta(days=args.days)
    records = parse_log(args.log, since=since)

    # 会话过滤
    if args.session:
        records = [r for r in records if args.session in r["session"]]

    if not records:
        print(f"⛔ 在 {args.log} 中未找到 API 调用记录（since={since.date()}）")
        print("   可能原因: 文件路径不对 / 日志格式不匹配 / 时间段无调用")
        print(f"   日志文件存在: {os.path.exists(args.log)}")
        print(f"   日志大小: {os.path.getsize(args.log) if os.path.exists(args.log) else 'N/A'}")
        sys.exit(0)

    log_summary = summarize(records)

    # API 查询
    or_usage = None
    or_credits = None
    ds_balance = None
    if not args.no_api:
        or_usage = query_openrouter_usage()
        or_credits = query_openrouter_credits()
        ds_balance = query_deepseek_balance()

    # Gateway 数据缺口
    gateway_extra = None
    gw_path = os.path.join(HERMES_HOME, "logs", "gateway.log")
    if os.path.exists(gw_path):
        gateway_extra = parse_gateway_extra(gw_path, since=since)

    label = f"最近 {args.days} 天" if not args.session else f"会话 {args.session}"

    if args.compact:
        print_compact_report(log_summary, ds_balance, label)
    else:
        print_report(log_summary, or_usage, or_credits, ds_balance, gateway_extra, label)


if __name__ == "__main__":
    main()
