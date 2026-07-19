"""
notes-health-scan.py — 全量笔记库健康检查

Scan all .md files and report:
  ▶ YAML frontmatter integrity
  ▶ Tags presence & format (list of quoted "#xxx")
  ▶ Relation type validity against ALLOWED_TYPES
  ▶ Body wikilink section presence (for struct-* notes)
  ▶ Dead [[wikilinks]] (target file not found)
  ▶ Missing reverse relations (A→B but B→A missing)

Usage:
    python notes-health-scan.py
"""

import os, re, sys

NOTES = os.path.expanduser(r"~/hermes-notes")
ALLOWED_TYPES = {
    '依赖','协作','继承','核心算法','组件',
    '维护','修复','重启','创建','废弃','升级','扩容','还原',
    '同层','拓展','实例化','跟踪对象',
    '父节点','上一天','下一天','映射→系统',
}
KNOWN_PARENTS = {
    'README', '系统实现', '学习路线图', '学习笔记',
    '废弃归档', '路线图', '工作日志索引',
}


def scan(notes_dir):
    all_notes = {}
    for root, dirs, files in os.walk(notes_dir):
        dirs[:] = [d for d in dirs if d != '.git']
        for f in files:
            if not f.endswith('.md'): continue
            name = f[:-3]
            rel = os.path.relpath(os.path.join(root, f), notes_dir)
            all_notes[name] = rel

    issues = {
        'bad_yaml': [], 'no_tags': [], 'bad_tag_fmt': [],
        'no_rels': [], 'bad_type': [], 'no_body_wl': [],
        'dead_wl': [], 'missing_reverse': [],
    }

    for name, relpath in sorted(all_notes.items()):
        fpath = os.path.join(notes_dir, relpath)
        with open(fpath, encoding='utf-8', errors='replace') as fh:
            content = fh.read()
        if not content.startswith('---'): continue
        parts = content.split('---', 2)
        if len(parts) < 3:
            issues['bad_yaml'].append(name); continue
        front, body = parts[1], parts[2]

        tm = re.search(r'tags:\s*\[([^\]]*)\]', front)
        if not tm: issues['no_tags'].append(name)
        elif not re.search(r'\"#', tm.group(1)): issues['bad_tag_fmt'].append(name)

        rel_targets = re.findall(r'target:\s*\"([^\"]+)\"', front)
        for m in re.finditer(r'type:\s*\"([^\"]+)\"', front):
            if m.group(1) not in ALLOWED_TYPES:
                issues['bad_type'].append((name, m.group(1)))

        if name.startswith('struct-') and not rel_targets:
            issues['no_rels'].append(name)
        if name.startswith('struct-'):
            # Also match numbered headers like '## 七、边关系', '## 4. 边关系'
            if not re.search(r'边关系', body) and '关联笔记' not in body:
                issues['no_body_wl'].append(name)

        for target in set(re.findall(r'\[\[([^\]|#]+)', body)):
            t = target.strip()
            if not t or t.startswith('http') or '.' in t: continue
            if t in KNOWN_PARENTS: continue
            if t not in all_notes: issues['dead_wl'].append((name, t))

        for t in rel_targets:
            # Check all note types for bidirectional relations, not just struct/worklog
            REVERSE_TARGET_PREFIXES = ('struct-', '工作日志-', '计划-', '情报-', '智库-')
            if t.startswith(REVERSE_TARGET_PREFIXES) and t in all_notes and t != name:
                with open(os.path.join(notes_dir, all_notes[t]), encoding='utf-8', errors='replace') as tfh:
                    if f'target: "{name}"' not in tfh.read():
                        issues['missing_reverse'].append((name, t))

    return issues, len(all_notes)


if __name__ == '__main__':
    issues, total = scan(NOTES)
    print(f"Total: {total}")
    sections = [
        ("YAML broken", 'bad_yaml'), ("Missing tags", 'no_tags'),
        ("Tags format", 'bad_tag_fmt'), ("Non-standard type", 'bad_type'),
        ("Struct no relations", 'no_rels'), ("Struct no body wl", 'no_body_wl'),
        ("Dead wikilinks", 'dead_wl'), ("Missing reverse", 'missing_reverse'),
    ]
    for label, key in sections:
        items = issues[key]
        print(f"\n{label} ({len(items)})")
        if items:
            for item in items[:6]: print(f"  ❌ {item}")
            if len(items) > 6: print(f"  ... +{len(items)-6}")
    n = sum(len(v) for v in issues.values())
    print(f"\nTotal issues: {n}")
    sys.exit(1 if n else 0)
