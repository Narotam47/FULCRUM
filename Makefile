PYTHON   ?= python
DATA_URL := https://archive.ics.uci.edu/ml/machine-learning-databases/00222/bank-additional.zip

.PHONY: all data eda features model pnl clean help

all: pnl  ## Run the full pipeline (default)

# ── Data acquisition ─────────────────────────────────────────────
data/raw/bank-additional-full.csv:
	@mkdir -p data/raw
	curl -L -o data/raw/bank-additional.zip $(DATA_URL)
	unzip -o data/raw/bank-additional.zip -d data/raw
	mv data/raw/bank-additional/bank-additional-full.csv data/raw/
	rm -rf data/raw/bank-additional data/raw/bank-additional.zip

data: data/raw/bank-additional-full.csv  ## Fetch UCI dataset

# ── Pipeline stages ──────────────────────────────────────────────
data/processed/clean.csv: data/raw/bank-additional-full.csv python/01_ingest.py
	$(PYTHON) python/01_ingest.py

data/processed/features.csv: data/processed/clean.csv python/02_feature_eng.py
	$(PYTHON) python/02_feature_eng.py

output/figures/.eda_done: data/processed/features.csv python/03_eda.py
	$(PYTHON) python/03_eda.py
	@touch $@

output/model_metrics.json: data/processed/features.csv python/04_model.py
	$(PYTHON) python/04_model.py

output/reports/pnl_summary.csv: output/model_metrics.json python/05_pnl.py
	$(PYTHON) python/05_pnl.py

# ── Convenience aliases ──────────────────────────────────────────
eda:      output/figures/.eda_done       ## Run through EDA
features: data/processed/features.csv    ## Run through feature engineering
model:    output/model_metrics.json      ## Run through modeling
pnl:      output/reports/pnl_summary.csv ## Run full pipeline through P&L

# ── Housekeeping ─────────────────────────────────────────────────
clean:  ## Remove all generated artifacts (keeps raw data)
	rm -rf data/processed/* output/figures/* output/reports/* output/model_metrics.json

help:  ## Show this help
	@grep -E '^[a-z_-]+:.*## ' $(MAKEFILE_LIST) | \
		awk -F ':.*## ' '{printf "  %-12s %s\n", $$1, $$2}'
