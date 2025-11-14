# Keyword Combiner

Generate keyword permutations from CSV inputs via an interactive guided flow or a non-interactive CLI. Supports template-driven phrases, stable de-duplication, and Ads match-type formatting.

## Contents
- Overview
- Features
- Requirements
- Quick start (guided)
- CLI usage (non-interactive)
- CSV specs
- Templates
- Output
- Tips
- Development

## Overview
This repository provides two entry points:
- Guided CLI: run.py — interactive flow that detects CSVs, previews output, analyzes duplicates, supports match types, and saves to a file.
- Non-interactive CLI: keyword_builder.py — scriptable interface for pipelines and automation.

## Features
- Template mode: render phrases from templates like "{core} in {city}, {state}" with multiple secondary CSVs and placeholder validation.
- Full-permutation mode: insert the core phrase at every position across each row's fields (and optionally across subsets via --min-fields in CLI mode).
- Stable de-duplication that preserves the first occurrence order.
- Row-grouped generation: preserves natural grouping by secondary rows for deterministic output.
- Match types (guided CLI): broad, phrase, exact formatting.
- Zero external dependencies (standard library only).

## Requirements
- Python 3.8+
- macOS/Linux/Windows supported

## Quick start (guided)
1) Prepare your CSVs in the project directory.
2) Make the guided script executable (optional):

```bash
chmod +x ./run.py
```

3) Run the guided flow:

```bash
./run.py
# or
python3 run.py
```

The flow will prompt you to choose:
- Core CSV and the core column (default "core")
- One or more secondary CSVs
- Optional template CSV (single column with placeholders)
- Duplicate cleanup
- Match type (broad | phrase | exact)
- Output file path (default keywords.txt)

Example CSVs:

core.csv
```csv
core
wedding photographer
event photography
```

venues.csv (with a header row)
```csv
city,state,venue
Baltimore,MD,museum
Annapolis,MD,waterfront
```

template.csv
```csv
{core} in {city}, {state}
{city} {venue} {core}
# comment and blank lines are allowed
```

## CLI usage (non-interactive)
Use the non-interactive CLI for automation and pipelines.

Full-permutation mode:
```bash
python3 keyword_builder.py \
  --core core.csv \
  --secondary venues.csv \
  --output keywords.txt \
  --core-column core \
  --skip-header
```

Template mode (secondary MUST have headers):
```bash
python3 keyword_builder.py \
  --core core.csv \
  --secondary venues.csv \
  --template template.csv \
  --output keywords.txt \
  --core-column core
```

Optional: generate across subsets of fields in full-permutation mode:
```bash
python3 keyword_builder.py \
  --core core.csv \
  --secondary venues.csv \
  --output keywords.txt \
  --core-column core \
  --skip-header \
  --min-fields 2
```

Notes:
- The non-interactive CLI always writes unique keywords (stable de-duplication). Match-type wrapping is part of the guided flow only.

## CSV specs
Core CSV:
- Must have a header row. Use the "core" column by default (override with --core-column).
- Blank values are ignored; extra columns are ignored.

Secondary CSVs:
- Full-permutation mode: may have a header; pass --skip-header if it does. Empty cells are dropped; empty rows are ignored.
- Template mode: must have headers. Each placeholder in templates must be a column name. Empty values prevent rendering for that row/template.

Multiple secondary CSVs (template mode):
- Supported in the guided flow. Rows are combined via Cartesian product.
- Column names must be unique across files; duplicates will cause an error.

## Templates
- Templates are read from a single-column CSV.
- Lines starting with '#' and blank lines are ignored.
- Only rows containing at least one {placeholder} are treated as templates.
- Allowed placeholders are "core" plus the union of secondary column names.

Examples:
```csv
{core} near {venue} in {city}, {state}
best {core} {city}
{venue} {core}
```

## Output
- Guided flow: choose match type (broad, phrase, exact) and output path; duplicates can be removed before saving.
- Non-interactive CLI: writes one unique keyword per line to the specified file.

## Tips
- Permutations grow quickly; prefer Template mode or --min-fields to constrain output size.
- Stable de-duplication preserves the first occurrence order.
- Keep CSVs UTF-8 encoded.

## Development
- No external dependencies.
- Recommended: use a virtual environment.
 
Create and activate a venv:
```bash
python3 -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
```

Run linters or tests (none included by default).

---
Happy combining!