# onefetch-extensions

Optional OneFetch site bundles (`adapter + expander`).

## Structure

```text
index.json
sites/
  <site_id>/
    manifest.json
    adapter.py
    expander.py
```

## Use from OneFetch

```bash
.venv/bin/python -m onefetch.cli ext list --remote --repo <your_git_repo_url>
.venv/bin/python -m onefetch.cli ext install <site_id> --repo <your_git_repo_url>
.venv/bin/python -m onefetch.cli ext update <site_id> --repo <your_git_repo_url>
.venv/bin/python -m onefetch.cli ext remove <site_id>
```
