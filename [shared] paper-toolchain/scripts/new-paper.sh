#!/usr/bin/env bash
# new-paper.sh — scaffold a new paper project from template (Cloud/Linux 版)
# Usage: bash new-paper.sh "Paper Title" "Author Name" [target-dir]

set -euo pipefail

TITLE="${1:?Usage: new-paper.sh \"Title\" \"Author\" [dir]}"
AUTHOR="${2:?Usage: new-paper.sh \"Title\" \"Author\" [dir]}"
DIR="${3:-"$(echo "$TITLE" | tr '[:upper:]' '[:lower:]' | tr -cs 'a-z0-9' '-' | sed 's/-$//')"}"

TEMPLATE_DIR="${HOME}/.paper-toolchain/templates"
PAPER_DIR="$(pwd)/${DIR}"

if [ -d "$PAPER_DIR" ]; then
    echo "ERROR: $PAPER_DIR already exists"
    exit 1
fi

SHORT=$(echo "$TITLE" | sed 's/^\(.\{40\}\).*/\1.../')

# Copy template
mkdir -p "$PAPER_DIR/src" "$PAPER_DIR/output"
cp "$TEMPLATE_DIR/academic-template.tex" "$PAPER_DIR/src/paper.tex"
# Provide a starter references.bib if none exists in templates
if [ -f "$TEMPLATE_DIR/references.bib" ]; then
    cp "$TEMPLATE_DIR/references.bib" "$PAPER_DIR/src/"
else
    touch "$PAPER_DIR/src/references.bib"
fi
# Copy verify.py and .gitignore from the toolchain
if [ -f "${HOME}/python-learning/paper-mendel-mamba/verify.py" ]; then
    cp "${HOME}/python-learning/paper-mendel-mamba/verify.py" "$PAPER_DIR/"
    cp "${HOME}/python-learning/paper-mendel-mamba/.gitignore" "$PAPER_DIR/"
fi

# Write Makefile
cat > "$PAPER_DIR/Makefile" << 'MAKEEOF'
NAME := paper
SRC  := src/$(NAME)
OUT  := output
BLD  := build
.PHONY: all clean verify
all: $(OUT)/$(NAME).pdf
$(OUT)/$(NAME).pdf: $(SRC).tex src/references.bib | $(OUT) $(BLD)
	xelatex -interaction=nonstopmode -output-directory=$(BLD) $(SRC).tex
	biber $(BLD)/$(NAME)
	xelatex -interaction=nonstopmode -output-directory=$(BLD) $(SRC).tex
	xelatex -interaction=nonstopmode -output-directory=$(BLD) $(SRC).tex
	cp $(BLD)/$(NAME).pdf $(OUT)/$(NAME).pdf
	@echo "=== BUILD COMPLETE: $(OUT)/$(NAME).pdf ==="
$(OUT): ; mkdir -p $(OUT)
$(BLD): ; mkdir -p $(BLD)
clean: ; rm -rf $(BLD) $(OUT)/$(NAME).pdf
verify: all
	python3 verify.py --src $(SRC).tex --keep
MAKEEOF

# Patch template with actual title/author/short
sed -i "s/Paper Title Here/$TITLE/g" "$PAPER_DIR/src/paper.tex"
sed -i "s/Author Name/$AUTHOR/g" "$PAPER_DIR/src/paper.tex"
sed -i "s/\\\\newcommand{\\\\shortauthor}{Author}/\\\\newcommand{\\\\shortauthor}{$AUTHOR}/" "$PAPER_DIR/src/paper.tex"
sed -i "s/\\\\newcommand{\\\\shorttitle}{Short Title}/\\\\newcommand{\\\\shorttitle}{$SHORT}/" "$PAPER_DIR/src/paper.tex"

echo "=== NEW PAPER CREATED ==="
echo "  Title:   $TITLE"
echo "  Author:  $AUTHOR"
echo "  Dir:     $PAPER_DIR"
echo ""
echo "  Commands:"
echo "    cd $PAPER_DIR && make          # build PDF"
echo "    cd $PAPER_DIR && make verify   # build + CI check"
echo "    cd $PAPER_DIR && make clean    # remove artifacts"
