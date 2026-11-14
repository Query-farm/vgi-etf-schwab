"""Transport setup and presentation; released worker and SQL own data analysis."""

from __future__ import annotations

import json
import math
import os
from datetime import UTC, datetime
from pathlib import Path

import matplotlib.pyplot as plt
import seaborn as sns
from IPython.display import Markdown, display


def configure(threshold, mode):
    if isinstance(threshold, bool) or not isinstance(threshold, (int, float)):
        raise ValueError("MIN_SHARED_PP must be a finite number from 0 through 5")
    if not math.isfinite(threshold) or not 0 <= threshold <= 5:
        raise ValueError("MIN_SHARED_PP must be a finite number from 0 through 5")
    if mode not in ("recorded", "live"):
        raise ValueError("DATA_MODE must be recorded or live")
    keys = ("NOTEBOOK_SCHWAB_DATA_MODE", "NOTEBOOK_SCHWAB_RECORDINGS", "NOTEBOOK_SCHWAB_AUDIT")
    previous = {k: os.environ.get(k) for k in keys}
    audit = Path("artifacts/page-audit.jsonl").resolve()
    audit.parent.mkdir(parents=True, exist_ok=True)
    audit.write_text("")
    for key, value in zip(keys, [mode, str(Path("recordings").resolve()), str(audit)], strict=True):
        os.environ[key] = value
    return previous, audit, datetime.now(UTC).isoformat()


def stage_audit(connection, audit):
    """Stage transport metadata; page parsing is performed by the released worker."""
    rows = [json.loads(line) for line in audit.read_text().splitlines()]
    connection.execute("""CREATE TABLE page_audit(fund_ticker VARCHAR, page INTEGER, url VARCHAR,
                       ok BOOLEAN, parsed_rows INTEGER, advertised_total DOUBLE, source_date DATE)""")
    connection.executemany(
        "INSERT INTO page_audit VALUES (?,?,?,?,?,?,?)",
        [
            [
                r[k]
                for k in [
                    "fund_ticker",
                    "page",
                    "url",
                    "ok",
                    "parsed_rows",
                    "advertised_total",
                    "source_date",
                ]
            ]
            for r in rows
        ],
    )


def cleanup(previous):
    for key, value in previous.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


def prose(text: str) -> None:
    display(Markdown(text))


def theme() -> None:
    sns.set_theme(
        style="whitegrid",
        rc={
            "figure.dpi": 145,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "grid.color": "#E8EDE9",
            "text.color": "#243B2F",
            "axes.labelcolor": "#405047",
            "text.parse_math": False,
            "legend.frameon": False,
        },
    )


def chart(fig, title: str, subtitle: str, source: str) -> None:
    fig.text(0.08, 0.98, title, ha="left", va="top", fontsize=17, fontweight="semibold")
    fig.text(0.08, 0.90, subtitle, ha="left", va="top", fontsize=10, color="#58685F")
    fig.tight_layout(rect=(0.02, 0.11, 1, 0.82))
    fig.text(0.08, 0.03, source, fontsize=8, color="#6C7D73")
    plt.show()
