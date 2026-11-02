# Contributing

Thanks for helping. Small fixes, new ideas and bug reports are all welcome.

## Setup

```bash
git clone https://github.com/kooroshkz/holland2stay-alerts
cd holland2stay-alerts
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest
ruff check src tests
```

`h2s-alerts demo` shows the dashboard with sample data, so you can work on the UI without
touching Holland2Stay.

## A few rules

- Tests never call Holland2Stay. Use the fake in `tests/conftest.py`.
- Be polite to their site: one request per check, no lower minimum interval, no pretending
  to be a browser, no booking. Pull requests that change this won't be merged.
- Keep messages and UI text short and plain.

## When the site changes

Most breakage looks like `doctor` failing or "Alerts may be broken". Please open an issue
with the `doctor` output (without your notification links) and the log lines around it.
