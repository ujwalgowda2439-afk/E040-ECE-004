# ECE-004 Broadband Billing Engine

## Requirements
- Python 3.10 or newer
- No third-party packages

## Run
Place the four input CSV files and `commands.txt` in one directory, then run:

```bash
python broadband_engine.py --input-dir . --output-dir output
```

The program prints a completion summary and creates:
- `output/daily_status.csv`
- `output/bills.csv`
- `output/errors.csv`

The output headers and column order match the evaluation README. Input CSV physical line numbers (including the header) are retained in `errors.csv`.

## Test the supplied sample pack
```bash
python broadband_engine.py --input-dir . --output-dir output
python -m unittest -v test_engine.py
```

## Files
- `broadband_engine.py` — complete engine / CLI
- `DESIGN.md` — BR-01 … BR-10, design decisions, formula, assumptions
- `test_engine.py` — integration tests for planted edge cases
- `plans.csv`, `subscribers.csv`, `previous_bills.csv`, `usage.csv`, `commands.txt` — supplied sample inputs
- `output/` — generated evaluation-format CSVs

See `DESIGN.md` for business-rule definitions and assumptions that are not completely specified by the brief.
