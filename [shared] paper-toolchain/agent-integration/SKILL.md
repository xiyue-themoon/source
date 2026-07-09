---
name: paper-writing-workflow
title: paper-writing-workflow
description: 论文写作工具链 — pandoc/xelatex/biber + Makefile + CI 校验 + 脚手架
category: productivity
---

# 论文写作工具链

## 两条路线

| 路线 | 引擎 | 适用场景 |
|:-----|:-----|:---------|
| **A: Markdown → pandoc** | `pandoc paper.md --pdf-engine=xelatex -o paper.pdf` | 快速出稿 / Word 兼容 |
| **B: 直接 .tex** | `make` (xelatex ×2 → biber → xelatex ×2) | 正式论文精细排版 |

## 工具依赖

```bash
# Cloud (Linux) 安装
sudo apt-get install -y texlive-xetex texlive-bibtex-extra biber poppler-utils pandoc latexmk

# Windows (MiKTeX) — 通过 MiKTeX 控制台安装
```

## 项目结构

```
paper-project/
├── src/
│   ├── paper.tex          ← 核心源文件
│   └── references.bib     ← 引用数据库
├── verify.py              ← CI 校验脚本
├── Makefile               ← make / make verify / make clean
├── .gitignore
├── output/                ← 编译产物
└── build/                 ← 中间文件
```

## 常用命令

```bash
make              # 编译 PDF（4 遍管线）
make verify       # 编译 + CI 校验
make clean        # 清理产物
make watch        # 监听 .tex 变动自动编译
```

## 脚手架（新建论文）

```bash
# Cloud 版（模板在 ~/.paper-toolchain/）
bash ~/.paper-toolchain/scripts/new-paper.sh "Title" "Author" [dir]

# 然后进入目录编译
cd ./Title-dir && make verify
```

## CI 校验

`verify.py` 做两件事：
1. 编译完整管线（自动检测错误）
2. 关键词匹配验证（检查论文章节完整性）

```bash
python3 verify.py --src src/paper.tex
```

## 参考项目

- `~/python-learning/paper-mendel-mamba/` — 完整论文示例（Mendel→Mamba）
- `~/.paper-toolchain/templates/` — 模板文件
- `~/.paper-toolchain/scripts/new-paper.sh` — 脚手架
