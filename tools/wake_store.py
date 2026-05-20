"""Read chunked Zarr wake fields produced from Tecplot binary ingest."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Literal, Optional, Sequence, Tuple, Union

import numpy as np
import zarr

PathLike = Union[str, Path]
Plane = Literal["XY", "XZ", "YZ"]


@dataclass
class SliceResult:
    plane: Plane
    index: int
    variables: List[str]
    arrays: Dict[str, np.ndarray]
    grid_shape: Tuple[int, int]
    node_index: int
    cell_index: int

    def to_dataframe(self):
        import pandas as pd

        flat = {name: arr.ravel() for name, arr in self.arrays.items()}
        n = len(next(iter(flat.values())))
        for name, arr in flat.items():
            if len(arr) != n:
                raise ValueError(
                    f"Cannot build DataFrame: '{name}' has {len(arr)} points, "
                    f"expected {n}. Node and cell variables differ on the same plane."
                )
        return pd.DataFrame(flat)


class WakeStore:
    """Zarr-backed access to a single structured wake volume."""

    def __init__(self, path: PathLike):
        self.path = Path(path)
        if not self.path.exists():
            raise FileNotFoundError(self.path)
        self.root = zarr.open_group(str(self.path), mode="r")
        keys = list(self.root.array_keys()) if hasattr(self.root, "array_keys") else list(self.root.keys())
        self.variables: List[str] = list(self.root.attrs.get("variables", keys))
        self.ijk: Tuple[int, int, int] = tuple(self.root.attrs["ijk"])
        self.var_location: Dict[str, str] = dict(self.root.attrs.get("var_location", {}))
        self.title: str = self.root.attrs.get("title", "")
        self.source_plt: str = self.root.attrs.get("source_plt", "")

    @classmethod
    def open(cls, path: PathLike) -> "WakeStore":
        return cls(path)

    def has_variable(self, name: str) -> bool:
        return name in self.root

    def get(self, name: str) -> zarr.Array:
        if name not in self.root:
            raise KeyError(f"Variable '{name}' not in store. Available: {self.variables}")
        return self.root[name]

    def read(self, name: str) -> np.ndarray:
        return np.asarray(self.get(name))

    def slice_plane(
        self,
        plane: Plane,
        index: int,
        variables: Optional[Sequence[str]] = None,
    ) -> SliceResult:
        """Extract a 2D plane from the structured grid.

        ``index`` is along the normal direction in *node* index space:
        - XY: fixed K (0 .. K-1)
        - XZ: fixed J (0 .. J-1)
        - YZ: fixed I (0 .. I-1)
        """
        I, J, K = self.ijk
        plane = plane.upper()  # type: ignore
        if plane not in ("XY", "XZ", "YZ"):
            raise ValueError("plane must be XY, XZ, or YZ")

        if plane == "XY":
            if not 0 <= index < K:
                raise IndexError(f"XY plane index must be in [0, {K - 1}], got {index}")
            grid_shape = (I, J)
            node_index = index
            cell_index = min(index, K - 2) if K > 1 else 0
        elif plane == "XZ":
            if not 0 <= index < J:
                raise IndexError(f"XZ plane index must be in [0, {J - 1}], got {index}")
            grid_shape = (I, K)
            node_index = index
            cell_index = min(index, J - 2) if J > 1 else 0
        else:
            if not 0 <= index < I:
                raise IndexError(f"YZ plane index must be in [0, {I - 1}], got {index}")
            grid_shape = (J, K)
            node_index = index
            cell_index = min(index, I - 2) if I > 1 else 0

        names = list(variables) if variables else [n for n in self.variables if n in self.root]
        arrays: Dict[str, np.ndarray] = {}
        for name in names:
            z = self.get(name)
            loc = self.var_location.get(name, "node")
            if loc == "cell":
                sl = self._cell_slice(plane, cell_index)
            else:
                sl = self._node_slice(plane, node_index)
            arrays[name] = np.asarray(z[sl])

        return SliceResult(
            plane=plane,  # type: ignore
            index=index,
            variables=names,
            arrays=arrays,
            grid_shape=grid_shape,
            node_index=node_index,
            cell_index=cell_index,
        )

    def line_probe(
        self,
        axis: Literal["I", "J", "K"],
        fixed: Dict[str, int],
        variables: Optional[Sequence[str]] = None,
    ) -> Dict[str, np.ndarray]:
        """Extract a 1D line along ``axis`` with other indices held fixed.

        ``fixed`` uses keys I/J/K with *node* indices for positioning. Cell-centered
        fields use the nearest valid cell index (clamped).
        """
        I, J, K = self.ijk
        axis = axis.upper()
        for key, val in fixed.items():
            dim = {"I": I, "J": J, "K": K}[key.upper()]
            if not 0 <= val < dim:
                raise IndexError(f"{key}={val} out of range [0, {dim - 1}]")

        names = list(variables) if variables else [n for n in self.variables if n in self.root]
        out: Dict[str, np.ndarray] = {}
        length_axis = None
        for name in names:
            z = self.get(name)
            loc = self.var_location.get(name, "node")
            sl, length_axis = self._line_slice(axis, fixed, cell_centered=(loc == "cell"))
            out[name] = np.asarray(z[sl])
        if length_axis is not None:
            out["index"] = np.arange(length_axis)
        return out

    @staticmethod
    def _node_slice(plane: str, index: int) -> Tuple:
        if plane == "XY":
            return (slice(None), slice(None), index)
        if plane == "XZ":
            return (slice(None), index, slice(None))
        return (index, slice(None), slice(None))

    @staticmethod
    def _cell_slice(plane: str, index: int) -> Tuple:
        if plane == "XY":
            return (slice(None), slice(None), index)
        if plane == "XZ":
            return (slice(None), index, slice(None))
        return (index, slice(None), slice(None))

    def _line_slice(
        self,
        axis: str,
        fixed: Dict[str, int],
        *,
        cell_centered: bool,
    ) -> Tuple[Tuple, int]:
        def idx(key: str, node_val: int) -> int:
            dim = {"I": self.ijk[0], "J": self.ijk[1], "K": self.ijk[2]}[key]
            if not cell_centered:
                return node_val
            return min(node_val, dim - 2) if dim > 1 else 0

        fi = idx("I", fixed.get("I", 0))
        fj = idx("J", fixed.get("J", 0))
        fk = idx("K", fixed.get("K", 0))

        if axis == "I":
            sl = (slice(None), fj, fk)
            length = self.ijk[0] - (1 if cell_centered else 0)
        elif axis == "J":
            sl = (fi, slice(None), fk)
            length = self.ijk[1] - (1 if cell_centered else 0)
        else:
            sl = (fi, fj, slice(None))
            length = self.ijk[2] - (1 if cell_centered else 0)
        return sl, length

    def summary(self) -> str:
        lines = [
            f"store: {self.path}",
            f"title: {self.title}",
            f"source: {self.source_plt}",
            f"ijk: I={self.ijk[0]}, J={self.ijk[1]}, K={self.ijk[2]}",
            "variables:",
        ]
        for name in self.variables:
            if name not in self.root:
                continue
            z = self.root[name]
            loc = self.var_location.get(name, "node")
            lines.append(f"  {name:4s}  {loc:4s}  shape={z.shape}  chunks={z.chunks}")
        return "\n".join(lines)
