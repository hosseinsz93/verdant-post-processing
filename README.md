# CFD Wake Analysis — Postprocessing Workflow

Python tooling to analyze large CFD wake fields exported from Tecplot **binary** (`.plt`) files. The workflow converts each volume once into a **chunked Zarr store**, then supports fast 2D slices, line probes, and matplotlib contours without re-parsing the original binary file.

Designed for the Verdant flood/wake case study data in `inputs/flood-log-7/`, but applicable to any single-zone structured Tecplot binary grid with the same conventions.

---

## Status (validated)

The following end-to-end path has been tested on `Result015000-avg.plt`:

| Step | What | How |
|------|------|-----|
| 1 | Install deps | `pip install -r requirements.txt` |
| 2 | Ingest | `scripts/ingest_plt_to_zarr.py` → `inputs/flood-log-7/Result015000-avg.zarr` |
| 3 | Inspect store | `WakeStore` / `wake_postprocess.py info` |
| 4 | Map Y → J index | `Y.mean(axis=(0,2))` → nearest `j` to target Y |
| 5 | **W contour on vertical XZ plane** | `slice_plane("XZ", j)` + `node_to_cell_2d` + `contourf` |

**Reference plot:** vertical plane at **Y ≈ 0.65** (spanwise), showing **W** vs **X** and **Z** — see [`wake1.ipynb`](wake1.ipynb) section 6.

---

## Table of contents

- [Why this workflow](#why-this-workflow)
- [Architecture](#architecture)
- [Project layout](#project-layout)
- [Input data](#input-data)
- [Installation](#installation)
- [Quick start](#quick-start)
- [Notebook walkthrough (`wake1.ipynb`)](#notebook-walkthrough-wake1ipynb)
- [Step 1 — Ingest binary to Zarr](#step-1--ingest-binary-to-zarr)
- [Step 2 — Inspect and extract data](#step-2--inspect-and-extract-data)
- [Contour plots (cell-centered fields)](#contour-plots-cell-centered-fields)
- [Python API](#python-api)
- [Grid and indexing conventions](#grid-and-indexing-conventions)
- [Performance and disk usage](#performance-and-disk-usage)
- [Legacy ASCII support](#legacy-ascii-support)
- [Troubleshooting](#troubleshooting)
- [Limitations and roadmap](#limitations-and-roadmap)

---

## Why this workflow

| Format | Typical size (this project) | Read speed | Best use |
|--------|----------------------------|------------|----------|
| Tecplot ASCII (`.dat`) | ~27 GB | Slow (text parsing) | Debugging, tiny exports |
| Tecplot binary (`.plt`) | ~7 GB | Moderate | **Archive / CFD handoff** |
| Zarr store (`.zarr/`) | ~5–8 GB (compressed) | Fast (chunked slices) | **Daily analysis** |

**Recommendation:** Keep `.plt` as the source of truth from CFD/Tecplot. Run ingest once per case, then use the Zarr store in notebooks and scripts.

---

## Architecture

```
  CFD / Tecplot export
         │
         ▼
  ┌──────────────────┐
  │  *.plt (binary)  │  Tecplot 360 TDV112, BLOCK packing
  └────────┬─────────┘
           │  scripts/ingest_plt_to_zarr.py  (one-time, ~3–5 min)
           ▼
  ┌──────────────────┐
  │  *.zarr/         │  Chunked float32 arrays + metadata attrs
  └────────┬─────────┘
           │
     ┌─────┴─────┐
     ▼           ▼
  WakeStore    wake_postprocess CLI
  (Python)     (info / slice / line)
     │
     ▼
  wake1.ipynb — contours, probes, CSV exports
```

**Libraries:**

- **[tecio](https://pypi.org/project/tecio/)** — reads Tecplot binary without a Tecplot license
- **[zarr](https://zarr.dev/)** — chunked on-disk arrays for partial I/O

---

## Project layout

```
cfd-wake-analysis/
├── README.md
├── requirements.txt
├── .vscode/settings.json           # Default: Anaconda interpreter
├── inputs/
│   └── flood-log-7/                # CFD data (*.plt, *.dat gitignored)
│       ├── Result015000-avg.plt    # Main 3D averaged wake (binary)
│       ├── Result015000-avg.zarr/  # After ingest
│       └── Result015000-avg.zarr.json
├── outputs/                        # CSV / figures from notebook (optional)
├── tools/
│   ├── tecplot_binary.py           # Binary .plt reader
│   ├── wake_store.py               # Zarr API, slices, node_to_cell_2d
│   └── tecplot_lazy_reader.py      # Legacy ASCII reader
├── scripts/
│   ├── ingest_plt_to_zarr.py
│   └── wake_postprocess.py
├── examples/
│   └── binary_workflow.py
└── wake1.ipynb                     # Step-by-step post-processing (start here)
```

---

## Input data

All CFD inputs live under **`inputs/flood-log-7/`** (not the project root).

### Primary 3D wake field (`Result015000-avg.plt`)

| Property | Value |
|----------|--------|
| Title | `Averaging` |
| Grid | `I=1325`, `J=73`, `K=1325` (~128M nodes) |
| Packing | `BLOCK` |
| Node variables | `X`, `Y`, `Z` |
| Cell-centered variables | `U`, `V`, `W`, `uu`, `vv`, `ww`, `uv`, `vw`, `uw`, `K`, `Nv` |

Shapes after load:

- Node: `(1325, 73, 1325)`
- Cell: `(1324, 72, 1324)`

On an **XZ slice** at fixed J (vertical plane, Y constant):

- Node coords `X`, `Z`: `(1325, 1325)`
- Cell field `W`: `(1324, 1324)`

### Other files in `inputs/flood-log-7/`

Not handled by the binary ingest pipeline:

- **`Flow0_*.dat` / `Flow1_*.dat`** — plain probe tables
- **`Turbine_*`** — ASCII time series

Use pandas directly for those.

---

## Installation

From the project root, install into the **same Python** used for the notebook kernel:

```bash
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Or with Anaconda (recommended for Jupyter — kernel **`Anaconda 3.12 (cfd-wake)`**):

```bash
python -m pip install -r requirements.txt
```

If `Activate.ps1` fails (PowerShell execution policy), call `.\.venv\Scripts\python.exe` explicitly.

### Requirements

- Python 3.10–3.12 preferred for notebooks (3.13 needs `setuptools` for `tecio`)
- `numpy`, `zarr`, `tecio`, `matplotlib`, `ipykernel` (see `requirements.txt`)

---

## Quick start

```bash
# 1) Ingest (once per case)
python scripts/ingest_plt_to_zarr.py inputs/flood-log-7/Result015000-avg.plt \
  -o inputs/flood-log-7/Result015000-avg.zarr --overwrite

# 2) Inspect
python scripts/wake_postprocess.py inputs/flood-log-7/Result015000-avg.zarr info

# 3) Open wake1.ipynb and run all cells (or use the API below)
```

---

## Notebook walkthrough (`wake1.ipynb`)

Primary guide for interactive work. Run cells **in order** from the top.

| Section | Content |
|---------|---------|
| Setup | Paths (`inputs/flood-log-7/`), imports, `%autoreload` |
| 1 | `pip install -r requirements.txt` |
| 2 | Ingest `.plt` → `.zarr` |
| 3–4 | Inspect binary metadata and Zarr store |
| 5 | Find **J** index for target **Y = 0.65** |
| **6** | **Contour of W on XZ plane** (validated) |
| 7 | XY slice + U contour (mid K) |
| 8–10 | CLI slice / line probe + CSV export |
| 11 | YZ slice example |
| Reference | Plane types (XY / XZ / YZ) |

**Kernel:** use **`Anaconda 3.12 (cfd-wake)`** or a working `.venv` with `ipykernel`. Restart the kernel after pulling code changes to `tools/wake_store.py`.

---

## Step 1 — Ingest binary to Zarr

```bash
python scripts/ingest_plt_to_zarr.py <path/to/file.plt> [options]
```

| Flag | Default | Description |
|------|---------|-------------|
| `-o`, `--output` | `<stem>.zarr` | Output directory |
| `--vars X Y Z ...` | all variables | Subset to export |
| `--overwrite` | off | Replace existing store |
| `--chunk-i` / `--chunk-k` | `128` | Chunk sizes |
| `--no-compress` | off | Skip Zstd (faster ingest, larger store) |

```bash
python scripts/ingest_plt_to_zarr.py inputs/flood-log-7/Result015000-avg.plt \
  -o inputs/flood-log-7/Result015000-avg.zarr --overwrite
```

- Reads **one variable at a time** (~12–17 s per variable on the reference grid).
- Writes group attrs: `source_plt`, `title`, `ijk`, `variables`, `var_location`.
- Sidecar: `Result015000-avg.zarr.json`.

---

## Step 2 — Inspect and extract data

```bash
python scripts/wake_postprocess.py inputs/flood-log-7/Result015000-avg.zarr info

python scripts/wake_postprocess.py inputs/flood-log-7/Result015000-avg.zarr slice \
  --plane XZ --index 63 --vars X,Z,U,K

python scripts/wake_postprocess.py inputs/flood-log-7/Result015000-avg.zarr line \
  --axis K --i 600 --j 63 --vars X,Z,U,W,K --csv outputs/line_probe.csv
```

See `wake_postprocess.py --help` for all options.

---

## Contour plots (cell-centered fields)

Velocity and turbulence variables are **cell-centered**: on an XZ slice they have shape `(1324, 1324)` while node coordinates `X`, `Z` are `(1325, 1325)`.

**Do not** average only along I or only along K — that produces mismatched shapes and `contourf` will fail.

Use `node_to_cell_2d` from `wake_store` to average **both** grid directions:

```python
from wake_store import WakeStore, node_to_cell_2d

store = WakeStore.open("inputs/flood-log-7/Result015000-avg.zarr")

# Physical Y = 0.65 → XZ vertical plane
Y = store.read("Y")
y_at_j = Y.mean(axis=(0, 2))
j_idx = int(np.argmin(np.abs(y_at_j - 0.65)))

sl = store.slice_plane("XZ", j_idx, variables=["X", "Z", "W"])
X, Z, W = sl.arrays["X"], sl.arrays["Z"], sl.arrays["W"]

Xc = node_to_cell_2d(X)   # (1324, 1324)
Zc = node_to_cell_2d(Z)   # (1324, 1324)
assert Xc.shape == W.shape == Zc.shape

import matplotlib.pyplot as plt
fig, ax = plt.subplots(figsize=(10, 4))
cf = ax.contourf(Xc, Zc, W, levels=40, cmap="RdBu_r")
plt.colorbar(cf, ax=ax, label="W")
ax.set_xlabel("X")
ax.set_ylabel("Z")
ax.set_title(f"W at Y ≈ {y_at_j[j_idx]:.3f}")
ax.set_aspect("equal")
plt.show()
```

| Plane | Fixed | Axes in plane | Example use |
|-------|--------|---------------|-------------|
| `XZ` | **J** (Y) | X, Z | **Vertical** slice at spanwise Y |
| `XY` | K (height) | X, Y | Horizontal slice |
| `YZ` | I (streamwise) | Y, Z | Cross-stream slice |

---

## Python API

```python
import sys
sys.path.insert(0, "./tools")

from tecplot_binary import TecplotBinaryDataset
from wake_store import WakeStore, node_to_cell_2d
```

### `WakeStore`

| Method | Description |
|--------|-------------|
| `WakeStore.open(path)` | Open Zarr store |
| `store.read(name)` | Load full variable as NumPy array |
| `store.slice_plane(plane, index, variables=...)` | 2D slice → `SliceResult` |
| `store.line_probe(axis, fixed, variables=...)` | 1D line → `dict` |

### `node_to_cell_2d(node_2d)`

Converts a 2D **node** grid `(I, K)` to **cell centers** `(I-1, K-1)` for `matplotlib.contourf` with cell-centered fields.

### `TecplotBinaryDataset`

Inspect or read `.plt` directly (slower for repeated access than Zarr):

```python
ds = TecplotBinaryDataset("inputs/flood-log-7/Result015000-avg.plt", read_data=False)
print(ds.summary())
```

---

## Grid and indexing conventions

### Tecplot ORDERED layout

Arrays are `(I, J, K)` with **I fastest**, then J, then K.

### Node vs cell-centered

| Location | Variables | 3D shape |
|----------|-----------|----------|
| Node | `X`, `Y`, `Z` | `(I, J, K)` |
| Cell | `U`, `V`, `W`, stresses, `K`, `Nv` | `(I-1, J-1, K-1)` |

`slice_plane` uses a **node index** along the fixed direction; cell fields use the nearest valid cell index (`cell_index` on `SliceResult`).

---

## Performance and disk usage

| Stage | Reference case |
|-------|----------------|
| `.plt` | ~6.7 GB |
| Ingest | ~3–5 min (14 variables) |
| `.zarr` | ~5–8 GB compressed |
| XZ slice + contour | Seconds after ingest |

Run ingest on a **local or offline-synced** copy of `inputs/flood-log-7` (Box can slow multi-GB I/O).

---

## Legacy ASCII support

`tools/tecplot_lazy_reader.py` and `wake.ipynb` target the old ~27 GB ASCII `tecplot-output.dat`. **New work:** binary → Zarr via `wake1.ipynb`.

---

## Troubleshooting

### Data path: `inputs/flood-log-7/`

```powershell
python scripts/ingest_plt_to_zarr.py inputs/flood-log-7/Result015000-avg.plt -o inputs/flood-log-7/Result015000-avg.zarr --overwrite
```

Ensure Box files are **available offline** before ingest.

### `TypeError: Shapes of x ... and z ... do not match` in `contourf`

Use `node_to_cell_2d` on **both** coordinate arrays (see [Contour plots](#contour-plots-cell-centered-fields)). Restart kernel and re-import if you added it recently:

```python
from wake_store import node_to_cell_2d
```

### `ImportError: cannot import name 'node_to_cell_2d'`

The function is in `tools/wake_store.py`. **Restart the Jupyter kernel** and re-run Setup (or use `%autoreload 2` in the notebook).

### Jupyter kernel timeout (`.venv 3.13`)

Switch to **`Anaconda 3.12 (cfd-wake)`** or recreate `.venv` with Python 3.12 (see earlier README notes / `.vscode/settings.json`).

### `ModuleNotFoundError: No module named 'zarr'`

Install into the interpreter that runs the notebook:

```powershell
python -c "import sys; print(sys.executable)"
python -m pip install -r requirements.txt
```

### `Cannot build DataFrame` on slice export

Node and cell variables have different lengths on the same plane — export coords and fields separately, or use matching `var_location` only.

### `tecio` on Python 3.13

```bash
pip install tecio setuptools
```

---

## Limitations and roadmap

**Current scope:**

- Single-zone `.plt` files
- Structured ORDERED grids only
- Contours via `node_to_cell_2d` (no interpolation to nodes yet)

**Possible extensions:**

- Batch ingest for all cases in `inputs/flood-log-7`
- Quiver / wake-deficit plots
- xarray/Dask layer on Zarr
- VTK export for ParaView

---

## Example script

```bash
python examples/binary_workflow.py
```

Requires an existing Zarr store.

---

## License note

**tecio** is GPL-3.0. Review license obligations if you distribute tooling that bundles it.
