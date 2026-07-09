# [builder] paper-toolchain

> 学术论文写作与逆向重建工具链。  
> 配套 skill: `paper-writing-workflow`

## 架构

```
paper-project/
├── src/
│   ├── paper.tex          ← 核心源文件（LaTeX + biblatex）
│   └── references.bib     ← BibLaTeX 引用数据库
├── verify.py              ← CI 校验脚本（编译 + 10 项内容检查）
├── new-paper.sh           ← 脚手架（从模板创建新论文项目）
├── Makefile               ← make / make verify / make clean
├── PROVENANCE.md          ← 证据链（源文件丢失重建时使用）
└── .gitignore
```

## 依赖

| 工具 | 版本 | 验证 |
|:-----|:----:|:-----|
| xelatex (MiKTeX) | 25.12 | `which xelatex` |
| biber | 2.21+ | `which biber` |
| pdftotext | — | `which pdftotext` |
| Python | 3.12+ | `python --version` |

## 验证入口

```bash
cd [builder] paper-toolchain/
make verify
```

预期输出：`PASS: 17p 114KB 10/10 sections OK`

## 模板位置

- `.tex` 模板: `~/AppData/Local/hermes/skills/productivity/paper-writing-workflow/templates/academic-template.tex`
- `new-paper.sh` 脚本: `~/AppData/Local/hermes/skills/productivity/paper-writing-workflow/scripts/new-paper.sh`

## 参考

- `hermes-notes/其他/论文工具链.md`
- `hermes-notes/学习/Mamba-状态空间模型.md`
- skill: `paper-writing-workflow`
