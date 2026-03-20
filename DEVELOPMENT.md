# Extension Development Guide

This repo hosts external OneFetch site bundles (`adapter + expander`).

## Principles

- `index.json` is the installable source of truth.
- `sites/example` is template-only by default (do not list in `index.json`).
- One site bundle = one folder under `sites/<id>/`.
- Keep bundle-level compatibility in `manifest.json` (`min_core_version`, optional `max_core_version`).

## Bundle Layout

```text
sites/<site_id>/
  manifest.json
  adapter.py
  expander.py
```

## `manifest.json` Contract

Required fields:
- `id`
- `name`
- `version`
- `domains`
- `provides`
- `entry`
- `min_core_version`

`entry` format:
- `entry.adapter`: `adapter.py:<symbol>`
- `entry.expander`: `expander.py:<symbol>`

## Release Checklist

1. Update site bundle code under `sites/<id>/`
2. Keep `index.json` in sync (new id/version/path)
3. Run checks:
   - `bash scripts/release_extensions_check.sh`
4. Run migrated adapter regression tests (from OneFetch core):
   - `PYTHONPATH=<onefetch_core_path> .venv/bin/python -m pytest -q tests/test_geekbang_adapter.py`
5. Update `README.md` extension list/status if needed
6. Commit and push

## Notes

- Extension tests depend on OneFetch core modules (`onefetch.*`).
- Keep extension tests here; keep core repo focused on extension framework + smoke workflow.
