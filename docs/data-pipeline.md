# Data Pipeline

Reproducible commands. A fresh environment reproduces every processed layer.

```bash
pip install -r requirements.txt
pip install holidays openpyxl pypdf        # pipeline-only extras

# 1 · download raw datasets (idempotent; records sha256 + provenance)
python data_pipeline/acquire.py

# 1b · copy user-collected local files into raw layers (sha256 recorded)
python data_pipeline/acquire_user.py

# 2 · fetch real India context (weather + holidays)
python data_pipeline/context_fetch.py

# 3 · normalize into canonical layers + quality reports + metadata
python -m data_pipeline.normalize

# 4 · build the operational dataset (real context drives the simulator)
python scripts/run_pipeline.py             # generate -> validate -> train -> run

# 5 · redistribution scenarios (deterministic, labelled)
python data_pipeline/scenarios.py

# 6 · honest ablation: real vs synthetic context effect on forecast MAE
python data_pipeline/ablation_context.py
```

## Directory contract (never overwrite raw)

```
data/
├── raw/
│   ├── official/      HCES zip + layout/readme/questionnaire, UNEP csv
│   ├── research/      IFCT compositions
│   ├── community/     Swiggy listings
│   └── _provenance.json           download records: url/date/sha256
├── processed/
│   ├── consumption/   canonical HCES layers
│   ├── restaurant/    normalized Swiggy
│   ├── waste/         UNEP India rows
│   ├── weather/       ERA5 Bengaluru daily
│   ├── metadata/      IFCT foods, verified item-code table
│   └── context/       Indian holiday calendar
├── synthetic/operational/         scenario frames (is_synthetic=true)
└── provenance/        dataset_metadata.json + quality_reports.json
```

## Quality gates applied on every import (`data/provenance/quality_reports.json`)

* schema: expected columns, row/column counts;
* missing-value percentages per column;
* duplicate keys (e.g., Swiggy `id`);
* negative / impossible values in numeric columns;
* distribution stats: min/max/mean/std/quartiles;
* unmapped item codes are LISTED as issues — never silently dropped or guessed.

## Outlier policy

Outliers are investigated and classified (winsorisation at per-series 99.5th
percentile happens only in the *operational* cleaning step, and is reported).
Festival/event spikes are signal, not noise.
