#!/usr/bin/env python3
"""
preproc-emoji.py — Strip/replace emoji from Markdown for clean xelatex compilation.

xelatex with Latin Modern font cannot render most emoji (💡, 🧪, ❌, ✅, etc.).
This script replaces them with plain-text equivalents or removes them entirely,
so the .tex output compiles without "Missing character" warnings.

Also converts 💡-prefixed blockquotes to \\begin{tip}...\\end{tip} LaTeX environments.

Usage:
    python3 preproc-emoji.py input.md output.md

The output.md can then be fed to pandoc:
    pandoc output.md --pdf-engine=xelatex --include-in-header=header.tex -o out.pdf
"""

import re
import sys

def main():
    if len(sys.argv) < 3:
        print("Usage: python3 preproc-emoji.py input.md output.md")
        sys.exit(1)

    src, dst = sys.argv[1], sys.argv[2]

    with open(src, 'r', encoding='utf-8') as f:
        md = f.read()

    # --- Step 1: Convert 💡 blockquotes to LaTeX tip environment ---
    def replace_tip(match):
        content = match.group(0)
        lines = []
        for line in content.split('\n'):
            stripped = re.sub(r'^>\s?', '', line)
            lines.append(stripped)
        body = '\n'.join(lines).strip()
        return '\\begin{tip}\n' + body + '\n\\end{tip}'

    md = re.sub(
        r'(?:^> \U0001f4a1.*(?:\n(?:>.*)?)*)',
        replace_tip,
        md,
        flags=re.MULTILINE
    )

    # --- Step 2: Replace remaining emoji with safe text ---
    # Key: emoji Unicode, Value: replacement string (empty = remove)
    emoji_map = {
        '\U0001f4a1': '',        # 💡
        '\U0001f4d6': '',        # 📖
        '\U0001f516': '',        # 🔖
        '\U0001f4f0': '',        # 📰
        '\U0001f4da': '',        # 📚
        '\u270d\ufe0f': '',      # ✍️
        '\U0001f3a8': '',        # 🎨
        '\u26a1': '',            # ⚡
        '\u26a0\ufe0f': '',      # ⚠️
        '\U0001f9d1': '',        # 🧑
        '\U0001f30d': '',        # 🌍
        '\U0001f4ca': '',        # 📊
        '\U0001f50d': '',        # 🔍
        '\U0001f9ea': '',        # 🧪
        '\U0001f4d9': '',        # 📙
        '\U0001f4d8': '',        # 📘
        '\U0001f4d7': '',        # 📗
        '\u25b8': '>',           # ▸ → plain arrow
        '\u25b6': '>',           # ▶
        '\u274c': '[X]',         # ❌
        '\u2705': '[OK]',        # ✅
        '\u2460': '(1)',         # ①
        '\u2461': '(2)',         # ②
        '\u2462': '(3)',         # ③
        '\u2550': '=',           # ═
    }
    for emoji, repl in emoji_map.items():
        md = md.replace(emoji, repl)

    # Clean up double/multiple spaces
    md = re.sub(r'  +', ' ', md)

    with open(dst, 'w', encoding='utf-8') as f:
        f.write(md)

    tip_count = md.count('\\begin{tip}')
    print(f'Tip blocks converted: {tip_count}')
    print(f'Written: {dst} ({len(md)} chars)')

if __name__ == '__main__':
    main()
