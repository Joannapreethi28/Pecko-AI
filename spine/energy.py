"""Package-only RAPL sampling. Energy covers the whole CPU package, not a cgroup."""

from pathlib import Path

from common.clock import now
from spine.resources import rapl_delta_j


class RaplMeter:
    def __init__(self, root: Path = Path("/sys/class/powercap"), max_gap_s: float = 2):
        if max_gap_s <= 0:
            raise ValueError("max_gap_s must be positive")
        self.domains = []
        self.errors = []
        self.max_gap_s = max_gap_s
        self.previous = None
        self.total_j = 0.0
        self.valid = True
        seen = set()
        try:
            # Linux exposes direct class symlinks and/or a control-type folder.
            candidates = list(root.iterdir())
            for child in list(candidates):
                if child.is_dir():
                    candidates.extend(child.iterdir())
            for candidate in candidates:
                if not candidate.is_dir():
                    continue
                resolved = candidate.resolve()
                if resolved in seen:
                    continue
                seen.add(resolved)
                name_file = candidate / "name"
                if not name_file.is_file():
                    continue
                name = name_file.read_text().strip()
                if name.startswith("package-"):
                    self.domains.append((resolved, name))
        except OSError as exc:
            self.errors.append(str(exc))
            self.valid = False
        if not self.domains:
            self.valid = False
            self.errors.append("No readable RAPL package domains")

    def sample(self, t: float | None = None) -> dict:
        t = now() if t is None else t
        values = {}
        try:
            for path, name in self.domains:
                energy = int((path / "energy_uj").read_text())
                maximum = int((path / "max_energy_range_uj").read_text())
                if maximum <= 0 or not 0 <= energy < maximum:
                    raise ValueError(f"Invalid counter in {name}")
                values[str(path)] = (energy, maximum)
            if self.previous is not None:
                old_t, old_values = self.previous
                if not 0 < t - old_t <= self.max_gap_s:
                    raise ValueError("RAPL sample interval cannot establish wrap count")
                if values.keys() != old_values.keys():
                    raise ValueError("RAPL domain set changed")
                delta = 0.0
                for key, (value, maximum) in values.items():
                    old, old_maximum = old_values[key]
                    if maximum != old_maximum:
                        raise ValueError("RAPL counter range changed")
                    delta += rapl_delta_j(old, value, maximum)
                if self.valid:
                    self.total_j += delta
            self.previous = (t, values)
        except (OSError, ValueError) as exc:
            self.valid = False
            message = str(exc)
            if message not in self.errors:
                self.errors.append(message)
        return self.summary()

    def summary(self) -> dict:
        return {"available": self.valid, "gross_j": self.total_j if self.valid else None,
                "domains": [name for _, name in self.domains], "scope": "whole CPU packages",
                "wrap_assumption": "less than one full counter wrap between samples",
                "errors": list(self.errors)}
