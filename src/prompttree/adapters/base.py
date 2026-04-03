from __future__ import annotations

from typing import Any, Dict, Iterable, Protocol


class AdapterProtocol(Protocol):
    def list_artifacts(self) -> Iterable[Dict[str, Any]]:
        ...

    def load_artifact(self, artifact_ref: Dict[str, Any]) -> Dict[str, Any]:
        ...

    def diff_artifact(self, *, before_value: str, after_value: str, artifact_ref: Dict[str, Any]) -> Dict[str, Any]:
        ...

    def build_prompt_inputs(self, *, family_id: str, artifact_ref: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        ...

    def evaluate_output(self, *, family_id: str, artifact_ref: Dict[str, Any], output: str, context: Dict[str, Any]) -> Dict[str, Any]:
        ...

    def apply_output(self, *, family_id: str, artifact_ref: Dict[str, Any], output: str, context: Dict[str, Any]) -> Dict[str, Any]:
        ...

    def summarize_failure(self, evaluation_result: Dict[str, Any]) -> str:
        ...

