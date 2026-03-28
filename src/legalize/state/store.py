"""State Store — pipeline state tracking.

Persists in state.json which dispositions have been processed,
enabling idempotent re-runs.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class NormaState:
    """Processing state of an individual norm."""

    ultima_version_aplicada: str  # ISO date
    total_versiones_aplicadas: int


@dataclass
class RunRecord:
    """Record of a pipeline run."""

    fecha: str  # ISO datetime
    sumarios_revisados: list[str] = field(default_factory=list)
    commits_generados: int = 0
    errores: list[str] = field(default_factory=list)


class StateStore:
    """Manages the pipeline's state.json file."""

    def __init__(self, path: str | Path):
        self._path = Path(path)
        self._ultimo_sumario: Optional[str] = None
        self._normas: dict[str, NormaState] = {}
        self._ejecuciones: list[RunRecord] = []

    def load(self) -> None:
        """Loads the state from disk."""
        if not self._path.exists():
            return

        with open(self._path, encoding="utf-8") as f:
            data = json.load(f)

        self._ultimo_sumario = data.get("ultimo_sumario_procesado")
        self._normas = {
            k: NormaState(**v) for k, v in data.get("normas_procesadas", {}).items()
        }
        self._ejecuciones = [
            RunRecord(**r) for r in data.get("ejecuciones", [])
        ]

    def save(self) -> None:
        """Persists the state to disk."""
        self._path.parent.mkdir(parents=True, exist_ok=True)

        data = {
            "ultimo_sumario_procesado": self._ultimo_sumario,
            "normas_procesadas": {k: asdict(v) for k, v in self._normas.items()},
            "ejecuciones": [asdict(r) for r in self._ejecuciones],
        }

        with open(self._path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        logger.debug("State saved to %s", self._path)

    @property
    def ultimo_sumario(self) -> Optional[date]:
        """Date of the last processed sumario."""
        if self._ultimo_sumario:
            return date.fromisoformat(self._ultimo_sumario)
        return None

    @ultimo_sumario.setter
    def ultimo_sumario(self, fecha: date) -> None:
        self._ultimo_sumario = fecha.isoformat()

    def is_norma_processed(self, boe_id: str, fecha: date) -> bool:
        """Checks whether a specific version of a norm has already been processed."""
        state = self._normas.get(boe_id)
        if state is None:
            return False
        return state.ultima_version_aplicada >= fecha.isoformat()

    def mark_norma_processed(self, boe_id: str, fecha: date, total_versions: int) -> None:
        """Marks a norm as processed up to a given date."""
        self._normas[boe_id] = NormaState(
            ultima_version_aplicada=fecha.isoformat(),
            total_versiones_aplicadas=total_versions,
        )

    def record_run(
        self,
        sumarios: list[str] | None = None,
        commits: int = 0,
        errores: list[str] | None = None,
    ) -> None:
        """Records a pipeline run."""
        self._ejecuciones.append(RunRecord(
            fecha=datetime.now().isoformat(),
            sumarios_revisados=sumarios or [],
            commits_generados=commits,
            errores=errores or [],
        ))

    def get_norma_state(self, boe_id: str) -> Optional[NormaState]:
        return self._normas.get(boe_id)

    @property
    def normas_count(self) -> int:
        return len(self._normas)
