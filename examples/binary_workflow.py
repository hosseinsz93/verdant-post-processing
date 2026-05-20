#!/usr/bin/env python3
"""Minimal example: binary .plt -> Zarr -> slice."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from tecplot_binary import TecplotBinaryDataset  # noqa: E402
from wake_store import WakeStore  # noqa: E402

PLT = ROOT / "flood-log-7" / "Result015000-avg.plt"
ZARR = ROOT / "flood-log-7" / "Result015000-avg.zarr"


def main() -> None:
    # 1) Inspect binary (no full load)
    ds = TecplotBinaryDataset(PLT, read_data=False)
    print(ds.summary())

    # 2) Open Zarr store (create via scripts/ingest_plt_to_zarr.py first)
    store = WakeStore.open(ZARR)
    print("\n" + store.summary())

    # 3) Horizontal slice at mid height
    k_mid = store.ijk[2] // 2
    sl = store.slice_plane("XY", k_mid, variables=["X", "Y", "U", "K"])
    print(f"\nSlice XY @ K={k_mid}: grid {sl.grid_shape}")
    for name in sl.variables:
        a = sl.arrays[name]
        print(f"  {name}: {a.shape}  range [{a.min():.4g}, {a.max():.4g}]")


if __name__ == "__main__":
    main()
