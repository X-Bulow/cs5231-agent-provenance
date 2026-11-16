# Build the project report.
#
#   make            regenerate the data tables and compile build/report.pdf
#   make figures    reconvert the SVG figures to PDF (needs Google Chrome)
#   make clean      remove everything in build/ except report.pdf
#
# Requires Python 3.10+ and a LaTeX distribution with latexmk.

REPO   := ..
SRC    := src
BUILD  := build
FIGS   := run-001 run-006-backward-slice

.PHONY: all tables pdf figures clean

all: tables pdf

# Tables and numbers quoted in the text, computed from the graphs.
tables:
	cd $(REPO) && python3 report/$(SRC)/gen_tables.py > /dev/null

pdf:
	mkdir -p $(BUILD)
	cd $(SRC) && latexmk -pdf -interaction=nonstopmode -halt-on-error \
		-jobname=report -outdir=../$(BUILD) main.tex

# The figures are drawn as SVG by provenance/render.py; LaTeX needs PDF.
figures:
	for f in $(FIGS); do \
		sh $(SRC)/svg2pdf.sh $(REPO)/figures/$$f.svg $(SRC)/figures/$$f.pdf; \
	done

clean:
	cd $(SRC) && latexmk -c -jobname=report -outdir=../$(BUILD) main.tex
