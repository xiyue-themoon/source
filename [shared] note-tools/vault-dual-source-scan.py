#!/usr/bin/env python3
"""
vault-dual-source-scan.py — Obsidian 笔记库全量扫描

双源链接图构建（body [[wikilinks]] + YAML frontmatter relations:），
输出真实孤儿笔记（入链为零）和断链报告。

用法:
  python vault-dual-source-scan.py                    # 扫 ~/hermes-notes
  python vault-dual-source-scan.py /path/to/vault     # 扫指定目录

依赖: stdlib only (yaml 用正则 fallback，不强制装 PyYAML)
"""

import os
import re
import sys
from collections import defaultdict


# ── config ──────────────────────────────────────────────
VAULT = os.path.expanduser(sys.argv[1] if len(sys.argv) > 1 else "~/hermes-notes")

# ── frontmatter 解析（纯正则，不依赖 PyYAML） ────────────
def parse_relations_from_fm(content):
    """从 YAML frontmatter 提取所有 target 值。"""
    if not content.startswith('---'):
        return []
    parts = content.split('---', 2)
    if len(parts) < 3:
        return []
    fm_text = parts[1]
    # 提取 relations 块中的 target: "xxx" 行
    # 匹配缩进 - target: "值" 或 - target: 值
    targets = re.findall(r'^\s*-\s+target:\s*"([^"]+)"', fm_text, re.MULTILINE)
    if not targets:
        targets = re.findall(r'^\s*-\s+target:\s*(\S+)', fm_text, re.MULTILINE)
    return targets


def extract_tags_from_fm(content):
    """从 frontmatter 提取 tags 列表。"""
    if not content.startswith('---'):
        return []
    parts = content.split('---', 2)
    if len(parts) < 3:
        return []
    fm_text = parts[1]
    # format: tags: [tag1, tag2] 或 tags: ["#tag1", "#tag2"]
    match = re.search(r'tags:\s*\[([^\]]*)\]', fm_text)
    if not match:
        return []
    raw = match.group(1)
    tags = re.findall(r'["\']?([^"\'\[\],\s]+)["\']?', raw)
    # strip leading # 
    return [t.lstrip('#').strip('"').strip("'") for t in tags if t.strip()]


# ── wikilink 提取 ────────────────────────────────────────
WIKILINK_RE = re.compile(r'\[\[([^\]|]+?)(?:\|[^\]]*?)?(?:\#[^\]]*?)?\]\]')
MDLINK_RE = re.compile(r'\[([^\]]+)\]\(([^)]+\.md)\)')


def resolve_link(link_target, all_stems):
    """Try to match a [[link]] or markdown link to a vault note path."""
    t = link_target.strip()
    # direct match (without .md)
    if t in all_stems:
        # find the actual path
        for stem_path in all_stems:
            if stem_path == t:
                return stem_path
    # with .md appended
    t_md = t + '.md'
    if t_md in all_stems:
        return t_md
    # basename match
    for stem_path in all_stems:
        base = os.path.basename(stem_path)
        base_stem = os.path.splitext(base)[0]
        if base_stem == t or base == t:
            return stem_path
    return None


# ── 主流程 ──────────────────────────────────────────────
print(f"📂 Vault: {VAULT}")

# Step 1: collect all notes
all_notes = {}
for root, dirs, files in os.walk(VAULT):
    dirs[:] = [d for d in dirs if not d.startswith('.') and d != '_resources']
    for f in files:
        if f.endswith('.md'):
            fpath = os.path.join(root, f)
            rel = os.path.relpath(fpath, VAULT).replace('\\', '/')
            with open(fpath, 'r', encoding='utf-8', errors='replace') as fh:
                all_notes[rel] = fh.read()

print(f"📄 Total notes: {len(all_notes)}")

# Stems for link resolution
all_stems = set(all_notes.keys())

# Step 2: build dual-source link graph
outgoing_body = defaultdict(set)
outgoing_fm = defaultdict(set)
outgoing = defaultdict(set)
incoming = defaultdict(set)

for note_path, content in all_notes.items():
    # Source A: body [[wikilinks]] and [markdown](links)
    for m in WIKILINK_RE.finditer(content):
        target = resolve_link(m.group(1), all_stems)
        if target and target != note_path:
            outgoing_body[note_path].add(target)
            outgoing[note_path].add(target)
            incoming[target].add(note_path)
    for m in MDLINK_RE.finditer(content):
        target = resolve_link(m.group(2), all_stems)
        if target and target != note_path:
            outgoing_body[note_path].add(target)
            outgoing[note_path].add(target)
            incoming[target].add(note_path)

    # Source B: frontmatter relations
    for raw_target in parse_relations_from_fm(content):
        target = resolve_link(raw_target, all_stems)
        if target and target != note_path:
            outgoing_fm[note_path].add(target)
            outgoing[note_path].add(target)
            incoming[target].add(note_path)

# Step 3: orphan detection
orphans = []
for note_path in sorted(all_notes.keys()):
    count_in = len(incoming.get(note_path, set()))
    if count_in > 0:
        continue

    content = all_notes[note_path]
    lines = content.count('\n') + 1

    has_out_body = bool(outgoing_body.get(note_path))
    has_out_fm = bool(outgoing_fm.get(note_path))
    has_out = has_out_body or has_out_fm

    tags = extract_tags_from_fm(content)

    # body meaningful chars (after frontmatter)
    body = content
    if '---' in content:
        parts = content.split('---', 2)
        body = parts[2] if len(parts) > 2 else parts[-1]
    meaningful = [l for l in body.split('\n')
                  if l.strip() and not l.strip().startswith('#')
                  and not l.strip().startswith('---')
                  and not l.strip().startswith('```')]
    mchars = sum(len(l) for l in meaningful)

    is_template = note_path.startswith('_template-')
    is_index = ('index' in tags or '索引' in tags
                or note_path in ['README.md', '笔记关系图.md', '学习路线图.md', '系统实现目录.md'])
    is_log = '工作日志' in note_path
    is_archived = 'archived' in note_path or note_path == '废弃归档.md'

    orphans.append({
        'path': note_path,
        'lines': lines,
        'mchars': mchars,
        'has_body_out': has_out_body,
        'has_fm_out': has_out_fm,
        'tags': tags,
        'is_template': is_template,
        'is_index': is_index,
        'is_log': is_log,
        'is_archived': is_archived,
    })

# Step 4: broken links in body wikilinks only
broken_links = []
for note_path, content in all_notes.items():
    for m in WIKILINK_RE.finditer(content):
        raw = m.group(1).strip()
        target = resolve_link(raw, all_stems)
        if target is None:
            broken_links.append((note_path, raw))

# Step 5: report
true_orphans_content = [o for o in orphans
                        if not o['is_template'] and not o['is_index']
                        and not o['is_log'] and not o['is_archived']
                        and o['mchars'] >= 50]
true_orphans_stubs = [o for o in orphans
                      if not o['is_template'] and not o['is_index']
                      and not o['is_log'] and not o['is_archived']
                      and o['mchars'] < 50]

print("\n" + "=" * 60)
print(f"🏝️  TRUE ORPHANS — 真实孤立笔记（双源扫描，{len(true_orphans_content)} 篇）")
print("=" * 60)
print(f"   {'Note':<40s} {'c':>5s} {'行':>3s}  {'body→':>4s} {'fm→':>4s} tags")
print(f"   {'----':<40s} {'---':>5s} {'---':>3s}  {'----':>4s} {'----':>4s} ----")
for o in true_orphans_content:
    b = '✓' if o['has_body_out'] else '·'
    f = '✓' if o['has_fm_out'] else '·'
    tag_str = ','.join(o['tags'][:3]) if o['tags'] else '-'
    print(f"   {o['path']:<40s} {o['mchars']:>5d} {o['lines']:>3d}  {b:>4s} {f:>4s} {tag_str}")

if true_orphans_stubs:
    print(f"\n📄 STUBS ({len(true_orphans_stubs)} 篇)")
    for o in true_orphans_stubs:
        print(f"   {o['path']:<40s} {o['mchars']:>5d}c")

# Broken links report
print(f"\n{'─' * 60}")
print(f"💔 BODY WIKILINK 断链 ({len(broken_links)} 条)")
print(f"{'─' * 60}")
by_src = defaultdict(list)
for src, tgt in broken_links:
    by_src[src].append(tgt)
for src in sorted(by_src):
    for t in by_src[src]:
        print(f"   {src} → [[{t}]]")

# Intentional report
print(f"\n{'─' * 60}")
print("🔗 INTENTIONAL（模板/索引/日志/归档 — 预期无入链）")
print(f"{'─' * 60}")
intentional = [o for o in orphans if o['is_template'] or o['is_index'] or o['is_log'] or o['is_archived']]
for o in intentional:
    cat = '模板' if o['is_template'] else ('索引' if o['is_index'] else ('日志' if o['is_log'] else '归档'))
    print(f"   {cat}  {o['path']}")

print(f"\n{'=' * 60}")
print(f"📊 SUMMARY")
print(f"   Total notes:    {len(all_notes)}")
print(f"   True orphans:   {len(true_orphans_content)}")
print(f"   Stubs:          {len(true_orphans_stubs)}")
print(f"   Broken links:   {len(broken_links)}")
print(f"   Intentional:    {len(intentional)}")
print("=" * 60)
