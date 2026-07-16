"""
inspect_xlsx.py — dump columns + sample rows of uploaded xlsx files.

Because the score-sheet column layout is not known until the user uploads their
files, this utility lists every column (with a couple of sample values) for each
xlsx in a directory. Use it to confirm the Candidate column and reviewer score
columns, then set them in config / human_scores if auto-detection needs help.

Usage:
    python inspect_xlsx.py                 # inspect input/scores and input/applications
    python inspect_xlsx.py --dir some/dir  # inspect a specific directory
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from config import APPLICATIONS_DIR, SCORES_DIR


def inspect_dir(d: Path):
    if not d.exists():
        print(f"  (directory does not exist: {d})")
        return
    files = [p for p in sorted(d.glob("*.xlsx")) if not p.name.startswith("~$")]
    if not files:
        print(f"  (no .xlsx files in {d})")
        return
    for path in files:
        print(f"\n=== {path.name} ===")
        try:
            xl = pd.ExcelFile(path, engine="openpyxl")
            for sheet in xl.sheet_names:
                df = xl.parse(sheet)
                print(f"  sheet '{sheet}': {len(df)} rows, {len(df.columns)} columns")
                for col in df.columns:
                    non_null = df[col].dropna()
                    sample = non_null.iloc[0] if len(non_null) else ""
                    sample = str(sample).replace("\n", " ")[:60]
                    print(f"    - {col!r}  e.g. {sample!r}")
        except Exception as e:
            print(f"  ERROR reading {path.name}: {e}")


def main():
    ap = argparse.ArgumentParser(description="Inspect columns of uploaded xlsx files")
    ap.add_argument("--dir", type=str, help="Specific directory to inspect")
    args = ap.parse_args()

    if args.dir:
        inspect_dir(Path(args.dir))
    else:
        print("### SCORES ###")
        inspect_dir(SCORES_DIR)
        print("\n### APPLICATIONS ###")
        inspect_dir(APPLICATIONS_DIR)


if __name__ == "__main__":
    main()
