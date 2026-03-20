#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
INDEX_FILE="$REPO_ROOT/index.json"

if [[ ! -f "$INDEX_FILE" ]]; then
  echo "[check] missing index.json: $INDEX_FILE"
  exit 1
fi

python3 - <<'PY' "$REPO_ROOT"
import json
import sys
from pathlib import Path

root = Path(sys.argv[1]).resolve()
index_file = root / "index.json"
payload = json.loads(index_file.read_text(encoding="utf-8"))
items = payload.get("items")
if not isinstance(items, list):
    raise SystemExit("[check] index.json: 'items' must be a list")

required_manifest_fields = [
    "id",
    "name",
    "version",
    "domains",
    "provides",
    "entry",
    "min_core_version",
]

seen_ids: set[str] = set()
errors: list[str] = []

for i, item in enumerate(items, start=1):
    if not isinstance(item, dict):
        errors.append(f"items[{i}] is not an object")
        continue
    ext_id = str(item.get("id") or "").strip()
    rel_path = str(item.get("path") or "").strip()
    if not ext_id:
        errors.append(f"items[{i}] missing id")
        continue
    if ext_id in seen_ids:
        errors.append(f"duplicate id in index.json: {ext_id}")
    seen_ids.add(ext_id)
    if not rel_path:
        errors.append(f"{ext_id}: missing path")
        continue

    site_dir = (root / rel_path).resolve()
    if not site_dir.is_dir():
        errors.append(f"{ext_id}: path not found: {rel_path}")
        continue

    manifest = site_dir / "manifest.json"
    if not manifest.is_file():
        errors.append(f"{ext_id}: manifest.json missing in {rel_path}")
        continue

    try:
        m = json.loads(manifest.read_text(encoding="utf-8"))
    except Exception as exc:
        errors.append(f"{ext_id}: invalid manifest json: {exc}")
        continue

    for field in required_manifest_fields:
        if field not in m:
            errors.append(f"{ext_id}: manifest missing field '{field}'")

    mid = str(m.get("id") or "").strip()
    if mid and mid != ext_id:
        errors.append(f"{ext_id}: manifest id mismatch ({mid})")

    entry = m.get("entry") or {}
    if not isinstance(entry, dict):
        errors.append(f"{ext_id}: manifest entry must be object")
        entry = {}

    for key in ("adapter", "expander"):
        if key not in entry:
            continue
        raw = str(entry.get(key) or "").strip()
        if ":" not in raw:
            errors.append(f"{ext_id}: entry.{key} must be '<file>:<symbol>'")
            continue
        file_name, symbol = raw.split(":", 1)
        file_name = file_name.strip()
        symbol = symbol.strip()
        if not file_name or not symbol:
            errors.append(f"{ext_id}: entry.{key} has empty file/symbol")
            continue
        if not (site_dir / file_name).is_file():
            errors.append(f"{ext_id}: entry.{key} file not found: {file_name}")

if errors:
    print("[check] FAILED")
    for line in errors:
        print(f"- {line}")
    raise SystemExit(1)

print(f"[check] OK: {len(items)} extension(s) validated")
PY
