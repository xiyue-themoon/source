#!/usr/bin/env python3
"""qw — local LLM CLI: qwen2.5:7b (fast) | qwen3:8b (fast/think)."""

import argparse
import json
import sys
import time
import requests

OLLAMA_URL = "http://localhost:11434/api/generate"
MODELS = {
    "qwen3": "qwen3:8b",
    "qwen2.5": "qwen2.5:7b",
    "qwen25": "qwen2.5:7b",
}


def chat(prompt: str, model: str, think: bool = False, stream: bool = True):
    """Send prompt and stream response."""
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": stream,
        "options": {},
    }
    if "qwen3" in model:
        payload["options"]["enable_thinking"] = think

    t0 = time.time()
    resp = requests.post(OLLAMA_URL, json=payload, stream=stream, timeout=300)
    resp.raise_for_status()

    token_count = 0
    think_token_count = 0
    first_token_ts = None
    model_short = model.replace(":8b", "").replace(":7b", "")

    for line in resp.iter_lines(decode_unicode=True):
        if not line:
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue

        if data.get("done", False):
            elapsed = time.time() - t0
            eval_count = data.get("eval_count", token_count)
            gen_time = elapsed - (first_token_ts - t0 if first_token_ts else 0)
            tps = eval_count / max(gen_time, 0.01)
            tag = f"{model_short} | {'think' if think else 'fast'}"
            print(f"\n─ {tag} │ {eval_count} tokens │ {elapsed:.1f}s │ {tps:.0f} tok/s ─")
            break

        content = data.get("response", "")
        if content:
            if first_token_ts is None:
                first_token_ts = time.time()
            thinking = data.get("thinking", "")
            if thinking:
                think_token_count += 1
                if think_token_count == 1:
                    print("\n🧠 思考中...", end="", flush=True)
                if think_token_count <= 3:
                    print(f"\n  {thinking.strip()[:120]}", end="", flush=True)
                elif think_token_count == 4:
                    print("\n  ...", end="", flush=True)
            else:
                if think and think_token_count > 0 and token_count == 0:
                    print("\n\n💬 回答:\n", end="", flush=True)
                print(content, end="", flush=True)
                token_count += 1


def main():
    parser = argparse.ArgumentParser(description="local LLM CLI: qwen2.5 / qwen3")
    parser.add_argument("prompt", nargs="?", help="Your question (omit for interactive mode)")
    parser.add_argument("-m", "--model", choices=["qwen3", "qwen2.5", "qwen25"], default="qwen3",
                        help="Model: qwen3 (default) or qwen2.5")
    parser.add_argument("-t", "--think", action="store_true",
                        help="Enable deep thinking (qwen3 only)")
    parser.add_argument("--no-stream", action="store_true", help="Disable streaming output")
    args = parser.parse_args()

    model = MODELS[args.model]
    think = args.think if "qwen3" in model else False

    if args.prompt:
        chat(args.prompt, model, think=think, stream=not args.no_stream)
    else:
        model_short = model.replace(":8b", "").replace(":7b", "")
        has_think = "qwen3" in model
        print(f"{model_short} — type 'quit' to exit", end="")
        if has_think:
            print(", '/think' to toggle, '/model <name>' to switch")
        else:
            print(", '/model <name>' to switch")
        print()

        try:
            while True:
                prompt = input(">>> ").strip()
                if prompt.lower() in ("quit", "exit", "q"):
                    break
                if prompt == "/think":
                    if not has_think:
                        print("  ⚠ qwen2.5 has no thinking mode. Switch to qwen3 first (/model qwen3)")
                        continue
                    think = not think
                    print(f"  → {'🧠 thinking' if think else '⚡ fast'}\n")
                    continue
                if prompt.startswith("/model "):
                    name = prompt.split()[1]
                    if name in MODELS:
                        model = MODELS[name]
                        has_think = "qwen3" in model
                        think = False
                        model_short = model.replace(":8b", "").replace(":7b", "")
                        print(f"  → switched to {model_short}\n")
                    else:
                        print(f"  ⚠ unknown model. choices: qwen3, qwen2.5\n")
                    continue
                if not prompt:
                    continue
                print()
                chat(prompt, model, think=think, stream=not args.no_stream)
                print()
        except (KeyboardInterrupt, EOFError):
            print("\nbye")


if __name__ == "__main__":
    main()
