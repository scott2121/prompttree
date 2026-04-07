from __future__ import annotations

from typing import Any, Dict, Iterable, List, Protocol

from ..models import ArtifactHandle


class AdapterProtocol(Protocol):
    def list_artifacts(self) -> Iterable[Dict[str, Any]]:
        ...

    def load_artifact(self, artifact_ref: Dict[str, Any]) -> Dict[str, Any]:
        ...

    def diff_artifact(
        self,
        *,
        before_artifact: ArtifactHandle | None,
        after_artifact: ArtifactHandle | None,
        artifact_ref: Dict[str, Any],
    ) -> Dict[str, Any]:
        ...

    def build_prompt_inputs(self, *, family_id: str, artifact_ref: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        ...

    def evaluate_output(
        self,
        *,
        family_id: str,
        artifact_ref: Dict[str, Any],
        outputs: List[ArtifactHandle],
        context: Dict[str, Any],
    ) -> Dict[str, Any]:
        ...

    def apply_output(
        self,
        *,
        family_id: str,
        artifact_ref: Dict[str, Any],
        outputs: List[ArtifactHandle],
        context: Dict[str, Any],
    ) -> Dict[str, Any]:
        ...

    def summarize_failure(self, evaluation_result: Dict[str, Any]) -> str:
        ...
