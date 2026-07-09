# [shared] paper-toolchain — 论文写作工具链

> Builder 搭建 + Pioneer 云端适配的双端学术论文流水线。

## 概览

两条路线支持任何学术论文写作：

| 路线 | 引擎 | 适用场景 |
|:-----|:-----|:---------|
| **A: Markdown → pandoc** | `pandoc paper.md --pdf-engine=xelatex -o paper.pdf` | 快速出稿 / Word 兼容 |
| **B: 直接 .tex** | `make` (xelatex ×2 → biber → xelatex ×2) | 正式论文精细排版 |

## 目录结构

```
[shared] paper-toolchain/
├── templates/                      ← 论文模板
│   ├── academic-template.tex      ← LaTeX 模板（正式论文用）
│   └── academic-template.md       ← Markdown 模板（快速出稿用）
├── scripts/                        ← 脚手架 + CI
│   ├── new-paper.sh               ← 从模板新建论文项目
│   └── verify.py                  ← CI 校验脚本（编译 + 关键词检查）
├── examples/                       ← 完整论文示例
│   └── paper-mendel-mamba/        ← Mendel's Factor → Mamba's State
│       ├── src/Ma_Mendel_Mamba_2026.tex   (441 行)
│       ├── src/references.bib             (225 行, 25 篇文献)
│       ├── Makefile                ← 编译管线
│       ├── verify.py               ← CI 校验
│       ├── PROVENANCE.md           ← 证据链
│       └── .gitignore
├── agent-integration/              ← Agent Skill 集成
│   ├── SKILL.md                   ← paper-writing-workflow skill
│   └── cloud-setup.md             ← Cloud 端配置说明
└── README.md
```

## 快速开始

### 安装依赖

```bash
# Linux (Cloud)
sudo apt-get install -y texlive-xetex texlive-bibtex-extra biber poppler-utils pandoc latexmk

# Windows (Builder) — MiKTeX + pandoc
```

### 新建论文

```bash
bash scripts/new-paper.sh "Your Title" "Author Name" [dir-name]
cd ./dir-name && make verify
```

### 编译管线

```bash
make              # 编译 PDF
make verify       # 编译 + CI 校验
make clean        # 清理产物
make watch        # 监听 .tex 变动自动编译
```

## 编译原理

4 遍管线确保交叉引用和文献正确：

```
xelatex paper.tex   # 第 1 遍：生成 .aux
biber paper         # 第 2 遍：生成 .bbl
xelatex paper.tex   # 第 3 遍：嵌入引用
xelatex paper.tex   # 第 4 遍：解析交叉引用
```

## 环境差异

| 项目 | Cloud (Linux) | Builder (Win11) |
|:-----|:-------------|:-----------------|
| LaTeX | TeX Live (apt) | MiKTeX portable |
| 模板路径 | `~/.paper-toolchain/templates/` | `WORKPLACE/` |
| 脚手架 | `~/.paper-toolchain/scripts/new-paper.sh` | Shell 脚本 |
| verify | `python3 verify.py` | Windows Python |

## 维护者

- **Builder**: Win11 端搭建 + 论文撰写
- **Pioneer**: Cloud 端适配 + CI 修复
