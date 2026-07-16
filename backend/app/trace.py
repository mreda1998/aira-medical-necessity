from typing import Any


class Tracer:
    """Collects ordered intermediate artifacts from a pipeline run.

    The pipeline calls ``add(step, data)`` at each boundary (compiled tree,
    extracted order, per-branch facts, verifier output, verdict). ``data`` must
    already be JSON-serializable (call ``model_dump(mode="json")`` on Pydantic
    models before handing it over). ``as_list`` returns the ordered steps for the
    API response and for writing one JSON file per step to disk.
    """

    def __init__(self) -> None:
        self.steps: list[dict[str, Any]] = []

    def add(self, step: str, data: Any) -> None:
        self.steps.append({"step": step, "data": data})

    def as_list(self) -> list[dict[str, Any]]:
        return self.steps
