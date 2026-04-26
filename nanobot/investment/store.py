"""Investment workspace state storage."""

from __future__ import annotations

import json
import uuid
from pathlib import Path

from nanobot.investment.models import InvestmentState
from nanobot.utils.helpers import ensure_dir


class InvestmentStore:
    """Persist investment state while delegating schema parsing to the model layer."""

    def __init__(self, workspace: Path):
        self.workspace = workspace
        self.path = workspace / "investment" / "state.json"

    def load(self) -> InvestmentState:
        """Load workspace state and let ``InvestmentState`` own payload decoding."""
        if not self.path.exists():
            return InvestmentState()

        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid investment state file: {self.path}") from exc
        return InvestmentState.from_dict(payload)

    def save(self, state: InvestmentState) -> None:
        ensure_dir(self.path.parent)

        tmp_path = self.path.with_name(f".{self.path.name}.{uuid.uuid4().hex}.tmp")
        try:
            tmp_path.write_text(
                json.dumps(state.to_dict(), ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            tmp_path.replace(self.path)
        finally:
            tmp_path.unlink(missing_ok=True)
