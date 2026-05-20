# CFD Wake Analysis — Postprocessing Workflow

Python tooling to analyze large CFD wake fields exported from Tecplot **binary** (`.plt`) files. The workflow converts each volume once into a **chunked Zarr store**, then supports fast 2D slices and 1D line probes without re-parsing the original binary file.

Designed for the Verdant flood/wake case study data (e.g. `flood-log-7/`), but applicable to any single-zone structured Tecplot binary grid with the same conventions.

---

## Table of contents

- [Why this workflow](#why-this-workflow)
- [Architecture](#architecture)
- [Project layout](#project-layout)
- [Input data](#input-data)
- [Installation](#installation)
- [Quick start](#quick-start)
- [Step 1 — Ingest binary to Zarr](#step-1--ingest-binary-to-zarr)
- [Step 2 — Inspect and extract data](#step-2--inspect-and-extract-data)
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

**Recommendation:** Keep `.plt` as the source of truth from CFD/Tecplot. Run ingest once per case, then point notebooks and scripts at the Zarr store.

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
  notebooks, plots, CSV exports
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
├── flood-log-7/                    # CFD outputs (not always in git)
│   ├── Result015000-avg.plt        # Main 3D averaged wake (binary)
│   ├── Result015000-avg.zarr/      # Generated analysis store
│   ├── Result015000-avg.zarr.json  # Metadata sidecar (human-readable)
│   ├── Flow0_*.dat / Flow1_*.dat   # Small probe tables (separate format)
│   └── Turbine_*                   # Turbine time histories
├── tools/
│   ├── tecplot_binary.py           # Binary .plt reader wrapper
│   ├── wake_store.py               # Zarr access API (slices, line probes)
│   └── tecplot_lazy_reader.py      # Legacy ASCII .dat reader (optional)
├── scripts/
│   ├── ingest_plt_to_zarr.py       # .plt → .zarr conversion
│   └── wake_postprocess.py         # CLI on Zarr stores
├── examples/
│   └── binary_workflow.py          # Minimal end-to-end example
├── wake.ipynb / wake1.ipynb        # Exploratory notebooks (ASCII era)
```

---

## Input data

### Primary 3D wake field (`Result015000-avg.plt`)

Example metadata for the reference case:

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

### Other files in `flood-log-7/`

These are **not** handled by the binary ingest pipeline:

- **`Flow0_*.dat` / `Flow1_*.dat`** — plain numeric probe tables (no Tecplot header)
- **`Turbine_*`** — ASCII time series (`Variables="time", "angle", ...`)

Use pandas directly for those.

---

## Installation

From the project root:

```bash
pip install -r requirements.txt
```

### Recommended environment

- Python 3.10+
- **NumPy &lt; 2.3** (see [Troubleshooting](#troubleshooting) if you use Anaconda pandas/pyarrow)

Optional for plotting in notebooks:

```bash
pip install matplotlib seaborn
```

---

## Quick start

```bash
# 1) Convert binary → Zarr (once per case)
python scripts/ingest_plt_to_zarr.py flood-log-7/Result015000-avg.plt \
  -o flood-log-7/Result015000-avg.zarr --overwrite

# 2) Inspect the store
python scripts/wake_postprocess.py flood-log-7/Result015000-avg.zarr info

# 3) Extract a horizontal slice at mid-height (K index)
python scripts/wake_postprocess.py flood-log-7/Result015000-avg.zarr slice \
  --plane XY --index 662 --vars X,Y,Z,U,K

# 4) Line probe along streamwise direction (K) at fixed I, J
python scripts/wake_postprocess.py flood-log-7/Result015000-avg.zarr line \
  --axis K --i 600 --j 36 --vars X,Z,U,K --csv outputs/line_probe.csv
```

---

## Step 1 — Ingest binary to Zarr

### Command

```bash
python scripts/ingest_plt_to_zarr.py <path/to/file.plt> [options]
```

### Options

| Flag | Default | Description |
|------|---------|-------------|
| `-o`, `--output` | `<stem>.zarr` | Output directory |
| `--vars X Y Z ...` | all variables | Subset to export |
| `--overwrite` | off | Replace existing store |
| `--chunk-i` | `128` | Chunk size along I |
| `--chunk-k` | `128` | Chunk size along K (J is kept full: 73) |
| `--no-compress` | off | Skip Zstd compression (faster, larger) |

### Examples

```bash
# Full ingest with compression (typical)
python scripts/ingest_plt_to_zarr.py flood-log-7/Result015000-avg.plt \
  -o flood-log-7/Result015000-avg.zarr --overwrite

# Fast ingest, velocity + TKE only
python scripts/ingest_plt_to_zarr.py flood-log-7/Result015000-avg.plt \
  --vars U V W K --no-compress --overwrite

# Custom chunking for slice-heavy K-planes
python scripts/ingest_plt_to_zarr.py flood-log-7/Result015000-avg.plt \
  --chunk-i 256 --chunk-k 64 --overwrite
```

### What gets written

**Zarr group** (`Result015000-avg.zarr/`):

- One array per variable (`X/`, `Y/`, `U/`, …)
- Group attributes: `source_plt`, `title`, `ijk`, `variables`, `var_location`

**Sidecar JSON** (`Result015000-avg.zarr.json`):

- Same metadata for quick inspection outside Python

Default chunk layout for 3D fields: `(128, 73, 128)` — tuned so an **XY** slice at fixed K touches a minimal set of chunks.

### Ingest behavior

- Reads **one variable at a time** from the `.plt` file (low peak RAM, ~500 MB per node field).
- Expect **~12–17 s per variable** on the reference grid (~3–5 min for all 14 fields, hardware-dependent).

---

## Step 2 — Inspect and extract data

### CLI

```bash
python scripts/wake_postprocess.py <zarr_path> <command> [options]
```

#### `info`

Print store metadata, shapes, and chunk sizes.

```bash
python scripts/wake_postprocess.py flood-log-7/Result015000-avg.zarr info
```

#### `slice`

Extract a 2D plane.

| Flag | Description |
|------|-------------|
| `--plane` | `XY`, `XZ`, or `YZ` |
| `--index` | Index along the normal direction (see [Grid conventions](#grid-and-indexing-conventions)) |
| `--vars` | Comma-separated variable names |
| `--csv` | Optional output CSV path |

```bash
python scripts/wake_postprocess.py flood-log-7/Result015000-avg.zarr slice \
  --plane XZ --index 36 --vars X,Z,U,K --csv slice_xz.csv
```

#### `line`

Extract a 1D line along `I`, `J`, or `K` with other indices fixed.

| Flag | Description |
|------|-------------|
| `--axis` | `I`, `J`, or `K` |
| `--i`, `--j`, `--k` | Fixed node indices (omit the axis you are sweeping along) |
| `--vars` | Comma-separated names |
| `--csv` | Optional output CSV |

```bash
python scripts/wake_postprocess.py flood-log-7/Result015000-avg.zarr line \
  --axis I --j 36 --k 600 --vars X,Y,U
```

---

## Python API

Add `tools/` to the path (or run from `examples/`):

```python
import sys
sys.path.insert(0, "./tools")

from tecplot_binary import TecplotBinaryDataset
from wake_store import WakeStore
```

### Inspect binary without loading the full volume

```python
ds = TecplotBinaryDataset("flood-log-7/Result015000-avg.plt", read_data=False)
print(ds.summary())

# Load a single variable (~seconds)
u = ds.read_variable("U")
print(u.shape, u.min(), u.max())
```

### Open Zarr store

```python
store = WakeStore.open("flood-log-7/Result015000-avg.zarr")
print(store.summary())

# Full variable (loads entire array into memory)
k_field = store.read("K")
```

### 2D slice — `slice_plane`

```python
k_mid = store.ijk[2] // 2  # K dimension index

result = store.slice_plane(
    "XY",
    k_mid,
    variables=["X", "Y", "Z", "U", "K"],
)

print(result.grid_shape)      # (1325, 73) for XY
print(result.node_index)      # K index used for node vars
print(result.cell_index)      # K index used for cell vars
print(result.arrays["U"].shape)  # (1324, 72) — cell-centered
```

Export to CSV (node and cell variables must share the same flattened length):

```python
# Safe: coordinates only (all node-based, same shape)
coords = store.slice_plane("XY", k_mid, variables=["X", "Y", "Z"])
df = coords.to_dataframe()

# Or export cell fields separately
cells = store.slice_plane("XY", k_mid, variables=["U", "V", "W", "K"])
```

### 1D line probe — `line_probe`

```python
line = store.line_probe(
    axis="K",
    fixed={"I": 600, "J": 36},
    variables=["X", "Z", "U", "K"],
)

# Includes an 'index' array (0 .. N-1 along the sweep axis)
import matplotlib.pyplot as plt
plt.plot(line["Z"], line["U"])
```

### `WakeStore` reference

| Method | Description |
|--------|-------------|
| `WakeStore.open(path)` | Construct store from Zarr directory |
| `store.summary()` | Human-readable metadata string |
| `store.get(name)` | Zarr array handle (lazy) |
| `store.read(name)` | NumPy array (full load) |
| `store.slice_plane(plane, index, variables=...)` | → `SliceResult` |
| `store.line_probe(axis, fixed, variables=...)` | → `dict[str, ndarray]` |

### `SliceResult` fields

| Field | Meaning |
|-------|---------|
| `plane` | `XY`, `XZ`, or `YZ` |
| `index` | User-supplied index (node space for the normal direction) |
| `node_index` | Index used for node variables |
| `cell_index` | Index used for cell-centered variables |
| `grid_shape` | 2D shape of the slice in logical I/J/K layout |
| `arrays` | `{variable_name: ndarray}` |
| `to_dataframe()` | Pandas DataFrame (requires equal-length arrays) |

---

## Grid and indexing conventions

### Tecplot ORDERED layout

Arrays are shaped `(I, J, K)` with **I varying fastest**, then J, then K — consistent with Tecplot `ORDERED` zones and `tecio` output.

Index `i` along I, `j` along J, `k` along K:

```text
linear_index = i + j * I + k * I * J
```

### Node vs cell-centered

| Location | Variables (typical) | Shape |
|----------|---------------------|--------|
| Node | `X`, `Y`, `Z` | `(I, J, K)` |
| Cell | `U`, `V`, `W`, Reynolds stresses, `K`, `Nv` | `(I-1, J-1, K-1)` |

When you call `slice_plane` with index `k`:

- Node fields use `[:, :, k]`
- Cell fields use `[:, :, k_cell]` with `k_cell = min(k, K-2)`

So **velocity on an XY slice is one cell shorter** in I and J than coordinates — this is expected, not a bug.

### Plane definitions

| Plane | Fixed dimension | `index` range | 2D shape |
|-------|-----------------|---------------|----------|
| `XY` | K | `0 … K-1` | `(I, J)` |
| `XZ` | J | `0 … J-1` | `(I, K)` |
| `YZ` | I | `0 … I-1` | `(J, K)` |

### Mapping index to physical position

Use node coordinates from the same slice:

```python
sl = store.slice_plane("XY", k_index, variables=["X", "Y", "Z"])
x2d = sl.arrays["X"]  # shape (I, J)
y2d = sl.arrays["Y"]
```

For cell-centered `U`, either plot on the cell subgrid or interpolate to nodes in a notebook.

---

## Performance and disk usage

| Stage | Reference case | Notes |
|-------|----------------|-------|
| `.plt` on disk | ~6.7 GB | float32 BLOCK data |
| Ingest time | ~3–5 min | 14 variables, compressed |
| `.zarr` on disk | ~5–8 GB | Depends on `--no-compress` |
| XY slice read | Sub-second | After ingest; chunked I–K |

**Tips:**

- Run ingest on a **local or fully synced** copy of `flood-log-7` (Box/OneDrive can stall on multi-GB files).
- Use `--vars` during development to ingest only `X Y Z U K`.
- Prefer Zarr for repeated notebook work; hit `.plt` directly only for one-off full-volume loads.

---

## Legacy ASCII support

`tools/tecplot_lazy_reader.py` streams Tecplot **ASCII** `.dat` files without loading the full ~27 GB volume. The notebooks `wake.ipynb` and `wake1.ipynb` were built around this path.

For new work, use the **binary → Zarr** pipeline instead. ASCII remains available for comparison or if only `.dat` exists.

```python
from tecplot_lazy_reader import TecplotLazyReader

reader = TecplotLazyReader("flood-log-7/tecplot-output.dat")
reader.parse_header()
sample = reader.sample_variable(var_index=4, count=100)  # 1-based index
```

---

## Troubleshooting

### `FileNotFoundError` for `.plt` or `flood-log-7`

Cloud-synced folders (Box) may show paths in the IDE before files are available locally. Ensure the file is **available offline** or copied locally before ingest.

### NumPy 2.x warnings with pandas / pyarrow

If you see errors about *“compiled using NumPy 1.x”*, use a compatible stack:

```bash
pip install "numpy>=1.22,<2.3"
```

Or use your Anaconda base env where NumPy 1.26 is already installed.

### `Cannot build DataFrame` on slice export

Node vars `(1325, 73)` and cell vars `(1324, 72)` have different sizes on the same plane. Export them in separate CSV files or use only variables of the same `var_location`.

### Ingest fails with `Multi-zone files are not supported`

The tools currently assume **exactly one zone** per `.plt`. Split or export a single zone from Tecplot if needed.

### Zarr `manifest.json` warning

Older test stores may contain a `manifest.json` inside the Zarr directory. Delete it; metadata lives in `.zattrs` and the `.zarr.json` sidecar.

### `tecio` import error

```bash
pip install tecio>=2.0.6
```

No Tecplot license is required.

---

## Limitations and roadmap

**Current limitations:**

- Single-zone `.plt` files only
- No built-in interpolation of cell-centered data onto nodes
- No batch ingest across many `.plt` files (run the script per file)
- Probe/turbine ASCII formats are out of scope

**Possible extensions:**

- Batch ingest driver for all cases in `flood-log-7`
- Notebook templates (contour, quiver, wake deficit vs `Uref`)
- Optional xarray/Dask layer on top of Zarr
- VTK export for ParaView

---

## Example script

See `examples/binary_workflow.py`:

```bash
python examples/binary_workflow.py
```

Requires an existing Zarr store (run ingest first).

---

## License note

**tecio** is GPL-3.0. If you distribute tooling that links or bundles it, review license obligations. Internal analysis use within Verdant is typically fine; confirm with your compliance process for external releases.
