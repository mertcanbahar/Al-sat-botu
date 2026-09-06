#!/usr/bin/env python3
"""Hourly job: fill price_1h/24h/7d outcomes for signals old enough to have them.

See evaluation/outcomes.py. Run every hour (see
.github/workflows/eval-hourly.yml); safe to run more or less often since
it only ever fills a horizon once.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from evaluation.outcomes import fill_due_outcomes

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    count = fill_due_outcomes()
    print(f"Filled {count} outcome price(s).")
