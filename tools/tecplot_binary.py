"""Read Tecplot 360 binary (.plt) files via tecio."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple, Union

import numpy as np

try:
    from tecio import TecplotFile, VarLoc
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "tecio is required for binary Tecplot files. Install with: pip install tecio"
    ) from exc


PathLike = Union[str, Path]


@dataclass(frozen=True)
class ZoneInfo:
    title: str
    ijk: Tuple[int, int, int]
    var_location: Dict[str, str]  # "node" | "cell"

    @property
    def i(self) -> int:
        return self.ijk[0]

    @property
    def j(self) -> int:
        return self.ijk[1]

    @property
    def k(self) -> int:
        return self.ijk[2]

    @property
    def num_points(self) -> int:
        return self.i * self.j * self.k


class TecplotBinaryDataset:
    """Thin wrapper around tecio for one-zone structured Tecplot binary files."""

    def __init__(self, path: PathLike, *, read_data: bool = False):
        self.path = Path(path)
        if not self.path.is_file():
            hint = ""
            if "flood-log-7" in str(self.path) and "inputs" not in self.path.as_posix():
                hint = " (data may be under inputs/flood-log-7/)"
            raise FileNotFoundError(f"{self.path}{hint}")
        self._tf = TecplotFile(str(self.path), read_data=read_data)
        if self._tf.nzones < 1:
            raise ValueError(f"No zones found in {self.path}")
        if self._tf.nzones > 1:
            raise NotImplementedError(
                f"Multi-zone files are not supported yet ({self._tf.nzones} zones)."
            )
        self._zone = self._tf.zones[0]
        self.variables: List[str] = list(self._tf.variables)
        self.title: str = self._tf.title
        self.zone_info = self._build_zone_info()

    def _build_zone_info(self) -> ZoneInfo:
        ijk = tuple(int(x) for x in self._zone.ijk[:3])
        loc: Dict[str, str] = {}
        if self._zone.has_var_loc:
            for name, vl in zip(self.variables, self._zone.var_loc):
                loc[name] = "cell" if vl == VarLoc.CellCentered else "node"
        else:
            loc = {name: "node" for name in self.variables}
        title = getattr(self._zone, "title", "") or "zone_0"
        return ZoneInfo(title=str(title), ijk=ijk, var_location=loc)

    def read_variable(self, name: str) -> np.ndarray:
        if name not in self.variables:
            raise KeyError(
                f"Unknown variable '{name}'. Available: {', '.join(self.variables)}"
            )
        idx = self.variables.index(name)
        arr = self._tf.get_data(0, idx)
        return np.asarray(arr)

    def read_variables(self, names: Optional[Sequence[str]] = None) -> Dict[str, np.ndarray]:
        names = list(names) if names is not None else list(self.variables)
        return {name: self.read_variable(name) for name in names}

    def summary(self) -> str:
        zi = self.zone_info
        lines = [
            f"file: {self.path}",
            f"title: {self.title}",
            f"zone: {zi.title}",
            f"ijk: I={zi.i}, J={zi.j}, K={zi.k} ({zi.num_points:,} nodes)",
            f"variables ({len(self.variables)}):",
        ]
        for name in self.variables:
            loc = zi.var_location.get(name, "node")
            shape = self._expected_shape(name)
            lines.append(f"  {name:4s}  {loc:4s}  shape={shape}")
        return "\n".join(lines)

    def _expected_shape(self, name: str) -> Tuple[int, ...]:
        zi = self.zone_info
        if zi.var_location.get(name, "node") == "cell":
            return tuple(max(n - 1, 1) for n in zi.ijk)
        return zi.ijk
