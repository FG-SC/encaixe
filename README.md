# Encaixe — job matching with open rules

Encaixe matches candidates and recruiters with a public, reconstructable ranking: anyone can see how the ranking decides, why a job or a candidate showed up, why something did not, and what would change the result.

> Status: under construction.

## Development setup

```bash
python -m venv .venv
python tools/heavy.py -- .venv/Scripts/python -m pip install -c constraints.txt -e ".[dev]"
.venv/Scripts/python tools/heavy.py -- .venv/Scripts/python -m pytest
```

`tools/heavy.py` runs one heavy command at a time (installs, the test suite, front builds, batch commands): the MVP is designed for a machine with about 3 GB of free RAM.
