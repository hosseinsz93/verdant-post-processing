#!/usr/bin/env python3
"""CLI helpers for Zarr wake stores (inspect, slice, line probe)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from wake_store import WakeStore  # noqa: E402


def cmd_info(store: WakeStore) -> None:
    print(store.summary())


def cmd_slice(store: WakeStore, args: argparse.Namespace) -> None:
    vars_ = [v.strip() for v in args.vars.split(",")] if args.vars else None
    result = store.slice_plane(args.plane, args.index, variables=vars_)
    print(
        f"plane={result.plane} index={result.index} (node) cell_index={result.cell_index} "
        f"grid={result.grid_shape}"
    )
    for name in result.variables:
        arr = result.arrays[name]
        print(f"  {name}: shape={arr.shape} min={arr.min():.4g} max={arr.max():.4g}")

    if args.csv:
        df = result.to_dataframe()
        df.to_csv(args.csv, index=False)
        print(f"Wrote {args.csv}")


def cmd_line(store: WakeStore, args: argparse.Namespace) -> None:
    fixed = {}
    if args.i is not None:
        fixed["I"] = args.i
    if args.j is not None:
        fixed["J"] = args.j
    if args.k is not None:
        fixed["K"] = args.k
    vars_ = [v.strip() for v in args.vars.split(",")] if args.vars else None
    data = store.line_probe(args.axis, fixed, variables=vars_)
    for name, arr in data.items():
        if name == "index":
            continue
        print(f"  {name}: len={len(arr)} min={arr.min():.4g} max={arr.max():.4g}")
    if args.csv:
        import pandas as pd

        pd.DataFrame({k: v for k, v in data.items()}).to_csv(args.csv, index=False)
        print(f"Wrote {args.csv}")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("zarr_path", type=Path, help="Zarr store directory")
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("info", help="Print store metadata")

    sp = sub.add_parser("slice", help="Extract a 2D plane")
    sp.add_argument("--plane", choices=["XY", "XZ", "YZ"], default="XY")
    sp.add_argument("--index", type=int, default=0)
    sp.add_argument("--vars", type=str, default="X,Y,Z,U,V,W,K")
    sp.add_argument("--csv", type=Path, default=None)

    lp = sub.add_parser("line", help="Extract a 1D line probe")
    lp.add_argument("--axis", choices=["I", "J", "K"], default="K")
    lp.add_argument("--i", type=int, default=None)
    lp.add_argument("--j", type=int, default=None)
    lp.add_argument("--k", type=int, default=None)
    lp.add_argument("--vars", type=str, default="X,Y,Z,U,V,W,K")
    lp.add_argument("--csv", type=Path, default=None)

    args = p.parse_args()
    store = WakeStore.open(args.zarr_path)

    if args.command == "info":
        cmd_info(store)
    elif args.command == "slice":
        cmd_slice(store, args)
    elif args.command == "line":
        cmd_line(store, args)


if __name__ == "__main__":
    main()
