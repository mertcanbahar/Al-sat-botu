#!/usr/bin/env python3
"""Mirror the dashboard's data files from `data/` into `docs/`.

`docs/index.html` fetches five files with relative paths:

    watchlist.json, data/portfolio.json, data/signals.jsonl,
    data/health.json, data/equity.jsonl

`data/` remains the single source of truth -- nothing is authored here.
But the mirror has to be **committed**, not generated at deploy time:
GitHub Pages serves this repository with "Deploy from a branch"
(main / docs), so a file that only exists inside a workflow run is never
published and the dashboard gets a 404 for every fetch. Generating them
in pages.yml alone was exactly the bug that left the panel blank -- the
branch build overwrote that deployment with the committed tree.

Run it after anything that writes `data/` (see
.github/workflows/manual-portfolio.yml), and commit whatever changes.

Usage:
    python scripts/sync_docs_data.py [--check]

    --check  exit 1 if the mirror is stale instead of writing it
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from alsatbotu.config import WATCHLIST  # noqa: E402

DATA_DIR = REPO_ROOT / "data"
DOCS_DIR = REPO_ROOT / "docs"
DOCS_DATA_DIR = DOCS_DIR / "data"

# Dashboard'ın okuduğu dosyalar. evaluation.db burada yok: panel onu
# okumuyor ve 70 KB'lık ikili dosyayı her koşuda kopyalamanın anlamı yok.
MIRRORED_FILES = ("portfolio.json", "signals.jsonl", "health.json", "equity.jsonl")


def watchlist_payload() -> str:
    data = [{"symbol": entry["symbol"], "category": entry["category"]} for entry in WATCHLIST]
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


def sync(check: bool = False) -> list[str]:
    """Write (or, with `check`, just report) the stale mirror entries."""
    stale: list[str] = []

    def write(target: Path, content: bytes) -> None:
        current = target.read_bytes() if target.exists() else None
        if current == content:
            return
        stale.append(str(target.relative_to(REPO_ROOT)))
        if check:
            return
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)

    write(DOCS_DIR / "watchlist.json", watchlist_payload().encode("utf-8"))

    for name in MIRRORED_FILES:
        source = DATA_DIR / name
        if not source.exists():
            # Henüz hiç koşmamış bir kurulumda dosya olmayabilir; panel o
            # kaynağı "okunamadı" diye gösterir, bu bir hata değil.
            print(f"{name}: data/ içinde yok, atlanıyor")
            continue
        write(DOCS_DATA_DIR / name, source.read_bytes())

    return stale


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Yazma; docs/ kopyası data/ ile uyumsuzsa 1 ile çık",
    )
    args = parser.parse_args(argv)

    stale = sync(check=args.check)
    if not stale:
        print("docs/ kopyası güncel.")
        return 0

    if args.check:
        print("docs/ kopyası bayat:")
        for path in stale:
            print(f"  {path}")
        print("Düzeltmek için: python scripts/sync_docs_data.py")
        return 1

    print("Güncellendi:")
    for path in stale:
        print(f"  {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
