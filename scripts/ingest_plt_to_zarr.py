#!/usr/bin/env python3
"""Convert a Tecplot binary (.plt) file to a chunked Zarr store for fast slicing."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import zarr

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from tecplot_binary import TecplotBinaryDataset  # noqa: E402


def _default_chunks(shape: tuple[int, ...]) -> tuple[int, ...]:
    if len(shape) == 3:
        i, j, k = shape
        return (min(128, i), j, min(128, k))
    return tuple(min(1024, s) for s in shape)


def resolve_chunks(shape: tuple[int, ...], chunk_i: int, chunk_k: int) -> tuple[int, ...]:
    if len(shape) != 3:
        return _default_chunks(shape)
    i, j, k = shape
    ci = chunk_i if chunk_i > 0 else min(128, i)
    ck = chunk_k if chunk_k > 0 else min(128, k)
    return (min(ci, i), j, min(ck, k))


def ingest(
    plt_path: Path,
    zarr_path: Path,
    *,
    variables: list[str] | None = None,
    chunk_i: int = 128,
    chunk_k: int = 128,
    overwrite: bool = False,
    compress: bool = True,
) -> None:
    ds = TecplotBinaryDataset(plt_path, read_data=False)
    names = list(variables) if variables else list(ds.variables)

    if zarr_path.exists():
        if not overwrite:
            raise FileExistsError(
                f"{zarr_path} already exists. Pass --overwrite to replace it."
            )
        import shutil

        shutil.rmtree(zarr_path)

    root = zarr.open_group(str(zarr_path), mode="w")
    meta = {
        "source_plt": str(plt_path.resolve()),
        "title": ds.title,
        "zone_title": ds.zone_info.title,
        "ijk": list(ds.zone_info.ijk),
        "variables": names,
        "var_location": {n: ds.zone_info.var_location[n] for n in names},
    }
    root.attrs.update(meta)

    if compress:
        from zarr.codecs.zstd import ZstdCodec

        compressors = [ZstdCodec(level=3)]
    else:
        compressors = None

    print(ds.summary())
    print(f"\nWriting Zarr store: {zarr_path}")

    t0 = time.time()
    for i, name in enumerate(names, 1):
        t_var = time.time()
        arr = ds.read_variable(name)
        var_chunks = resolve_chunks(arr.shape, chunk_i, chunk_k)
        root.create_array(
            name,
            data=arr,
            chunks=var_chunks,
            compressors=compressors,
            overwrite=True,
        )
        print(
            f"  [{i}/{len(names)}] {name:4s}  shape={arr.shape}  "
            f"chunks={var_chunks}  ({time.time() - t_var:.1f}s)"
        )

    sidecar = zarr_path.with_suffix(".zarr.json")
    sidecar.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(f"\nDone in {time.time() - t0:.1f}s -> {zarr_path}")
    print(f"Metadata sidecar: {sidecar}")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("plt_file", type=Path, help="Input Tecplot binary .plt file")
    p.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="Output Zarr directory (default: <plt_stem>.zarr next to input)",
    )
    p.add_argument(
        "--vars",
        nargs="*",
        default=None,
        help="Subset of variables to export (default: all)",
    )
    p.add_argument("--overwrite", action="store_true")
    p.add_argument("--chunk-i", type=int, default=128)
    p.add_argument("--chunk-k", type=int, default=128)
    p.add_argument(
        "--no-compress",
        action="store_true",
        help="Disable Zstd compression (faster ingest, larger store)",
    )
    args = p.parse_args()

    plt_path = args.plt_file.resolve()
    out = (args.output or plt_path.with_suffix(".zarr")).resolve()

    ingest(
        plt_path,
        out,
        variables=args.vars,
        chunk_i=args.chunk_i,
        chunk_k=args.chunk_k,
        overwrite=args.overwrite,
        compress=not args.no_compress,
    )


if __name__ == "__main__":
    main()
