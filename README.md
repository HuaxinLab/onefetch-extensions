# onefetch-extensions

External site bundles for OneFetch (`adapter + expander`).

This repository is the extension source for OneFetch. The core repo can install/update bundles by id.

## Install from OneFetch

```bash
.venv/bin/python -m onefetch.cli ext list --remote --repo https://github.com/HuaxinLab/onefetch-extensions
.venv/bin/python -m onefetch.cli ext install <ext_id> --repo https://github.com/HuaxinLab/onefetch-extensions
.venv/bin/python -m onefetch.cli ext update <ext_id> --repo https://github.com/HuaxinLab/onefetch-extensions
```

## Available Extensions

| id | Domains | Provides | Status | Notes |
|---|---|---|---|---|
| `geekbang` | `b.geekbang.org` | `adapter`, `expander` | active | Course intro/detail parsing and URL expansion |

## Development Template

`sites/example` is kept as a local template/reference and is **not** listed in `index.json`.
Only entries in `index.json` are installable by `onefetch ext install`.

## Repository Structure

```text
index.json
sites/
  geekbang/
    manifest.json
    adapter.py
    expander.py
  example/                # template only, not installable
    manifest.json
    adapter.py
    expander.py
```
