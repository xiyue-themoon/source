# 云端论文工具链设置

## Infrastructure 目录

```
~/.paper-toolchain/
├── templates/
│   ├── academic-template.tex   ← LaTeX 模板
│   └── academic-template.md   ← Markdown 模板
└── scripts/
    ├── new-paper.sh            ← 脚手架
    └── verify.py               ← CI 校验脚本
```

## 安装命令

```bash
sudo apt-get install -y texlive-xetex texlive-bibtex-extra biber poppler-utils pandoc latexmk
```

## 新建论文

```bash
bash ~/.paper-toolchain/scripts/new-paper.sh "论文标题" "作者名" [目录名]
cd ./目录名 && make verify
```

## 现状

- Mendel→Mamba 论文在 `~/python-learning/paper-mendel-mamba/`
- Makefile: xelatex×2 → biber → xelatex×2 管线
- make verify 已通过（17p 114KB, 9/10 章节匹配）

## vs Win11 版差异

| 项目 | Cloud (Linux) | Win11 (Builder) |
|:-----|:-------------|:-----------------|
| LaTeX 引擎 | TeX Live 2023 (apt) | MiKTeX portable |
| 模板路径 | `~/.paper-toolchain/templates/` | `WORKPLACE/academic-template.tex` |
| 脚手架路径 | `~/.paper-toolchain/scripts/new-paper.sh` | `paper-project/new-paper.sh` |
| verify 命令 | `python3 verify.py` | Windows Python 路径 |
