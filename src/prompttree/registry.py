from __future__ import annotations

import re
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from .models import ExperimentArm, PromptExperiment, PromptFamily, PromptVersion, PromotionPolicy


FRONT_MATTER_RE = re.compile(r"\A---\n(.*?)\n---\n?(.*)\Z", re.DOTALL)


class Registry:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.families_dir = root / "families"
        self.experiments_dir = root / "experiments"

    @classmethod
    def load(cls, root: Path) -> "Registry":
        return cls(root=root)

    def init_layout(self) -> None:
        self.families_dir.mkdir(parents=True, exist_ok=True)
        self.experiments_dir.mkdir(parents=True, exist_ok=True)

    def list_families(self) -> List[PromptFamily]:
        families = []
        if not self.families_dir.exists():
            return families
        for family_dir in sorted(p for p in self.families_dir.iterdir() if p.is_dir()):
            families.append(self._load_family(family_dir))
        return families

    def get_family(self, family_id: str) -> PromptFamily:
        return self._load_family(self.families_dir / family_id)

    def list_versions(self, family_id: str) -> List[PromptVersion]:
        versions_dir = self.families_dir / family_id / "versions"
        versions = []
        if not versions_dir.exists():
            return versions
        for path in sorted(versions_dir.glob("*.md")):
            versions.append(self._load_version(path, family_id))
        return versions

    def resolve_version(self, family_id: str, version_ref: str) -> PromptVersion:
        family = self.get_family(family_id)
        version_id = self._resolve_version_id(family, version_ref)
        path = self.families_dir / family_id / "versions" / f"{version_id}.md"
        if not path.exists():
            raise FileNotFoundError(f"Prompt version not found: {family_id}@{version_id}")
        return self._load_version(path, family_id)

    def list_refs(self, family_id: str) -> Dict[str, str]:
        return dict(self.get_family(family_id).refs)

    def list_experiments(self, family_id: Optional[str] = None) -> List[PromptExperiment]:
        experiments = []
        if not self.experiments_dir.exists():
            return experiments
        for path in sorted(self.experiments_dir.glob("*.yaml")):
            experiment = self._load_experiment(path)
            if family_id and experiment.family_id != family_id:
                continue
            experiments.append(experiment)
        return experiments

    def get_active_experiment(self, family_id: str) -> Optional[PromptExperiment]:
        running = [experiment for experiment in self.list_experiments(family_id=family_id) if experiment.status == "running"]
        if len(running) > 1:
            raise RuntimeError(f"Multiple active experiments found for family: {family_id}")
        return running[0] if running else None

    def get_experiment(self, experiment_id: str) -> PromptExperiment:
        path = self.experiments_dir / f"{experiment_id}.yaml"
        if not path.exists():
            raise FileNotFoundError(f"Experiment not found: {experiment_id}")
        return self._load_experiment(path)

    def create_family(
        self,
        family_id: str,
        name: str,
        description: str,
        current_version: str,
        artifact_kind: str,
        stage: str = "",
        refs: Optional[Dict[str, str]] = None,
        promotion_policy: Optional[PromotionPolicy] = None,
    ) -> Path:
        family_dir = self.families_dir / family_id
        versions_dir = family_dir / "versions"
        versions_dir.mkdir(parents=True, exist_ok=True)
        manifest = self._family_manifest_data(
            family_id=family_id,
            name=name,
            description=description,
            current_version=current_version,
            refs=refs,
            artifact_kind=artifact_kind,
            stage=stage,
            promotion_policy=promotion_policy,
        )
        path = family_dir / "family.yaml"
        self._write_yaml(path, manifest)
        return path

    def set_current_version(self, family_id: str, version_id: str) -> Path:
        return self.set_refs(family_id, {"current": version_id})

    def set_ref(self, family_id: str, ref_name: str, version_id: str) -> Path:
        return self.set_refs(family_id, {ref_name: version_id})

    def set_refs(self, family_id: str, updates: Dict[str, str]) -> Path:
        if any(ref_name == "latest" for ref_name in updates):
            raise ValueError("The 'latest' ref is derived and cannot be persisted.")
        family = self.get_family(family_id)
        for version_id in updates.values():
            self.resolve_version(family_id, version_id)
        manifest_path = self.families_dir / family_id / "family.yaml"
        refs = dict(family.refs)
        refs.update(updates)
        data = self._family_manifest_data(
            family_id=family.id,
            name=family.name,
            description=family.description,
            current_version=refs["current"],
            refs=refs,
            artifact_kind=family.artifact_kind,
            stage=family.stage,
            promotion_policy=family.promotion_policy,
            metadata=family.metadata,
        )
        self._write_yaml(manifest_path, data)
        return manifest_path

    def write_version(
        self,
        family_id: str,
        version_id: str,
        body: str,
        *,
        label: str,
        parent_id: Optional[str],
        status: str,
        author: str,
        hypothesis: str,
        tags: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Path:
        versions_dir = self.families_dir / family_id / "versions"
        versions_dir.mkdir(parents=True, exist_ok=True)
        front_matter = {
            "id": version_id,
            "label": label,
            "parent_id": parent_id,
            "status": status,
            "author": author,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "hypothesis": hypothesis,
            "tags": tags or [],
        }
        if metadata:
            front_matter.update(metadata)
        text = f"---\n{yaml.safe_dump(front_matter, sort_keys=False).strip()}\n---\n\n{body.rstrip()}\n"
        path = versions_dir / f"{version_id}.md"
        path.write_text(text, encoding="utf-8")
        return path

    def write_experiment(self, experiment: PromptExperiment) -> Path:
        self.experiments_dir.mkdir(parents=True, exist_ok=True)
        path = self.experiments_dir / f"{experiment.id}.yaml"
        data = asdict(experiment)
        self._write_yaml(path, data)
        return path

    @staticmethod
    def _write_yaml(path: Path, data: Dict[str, Any]) -> None:
        path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

    def _load_family(self, family_dir: Path) -> PromptFamily:
        manifest_path = family_dir / "family.yaml"
        if not manifest_path.exists():
            raise FileNotFoundError(f"Missing family manifest: {manifest_path}")
        data = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
        refs = self._normalize_refs(data.get("current_version"), data.get("refs"))
        return PromptFamily(
            id=data["id"],
            name=data.get("name", data["id"]),
            description=data.get("description", ""),
            current_version=refs["current"],
            artifact_kind=data.get("artifact_kind", ""),
            refs=refs,
            stage=data.get("stage", ""),
            promotion_policy=PromotionPolicy.from_dict(data.get("promotion_policy")),
            metadata={
                k: v
                for k, v in data.items()
                if k not in {"id", "name", "description", "current_version", "refs", "artifact_kind", "stage", "promotion_policy"}
            },
        )

    def _load_version(self, path: Path, family_id: str) -> PromptVersion:
        raw = path.read_text(encoding="utf-8")
        match = FRONT_MATTER_RE.match(raw)
        if match:
            meta = yaml.safe_load(match.group(1)) or {}
            body = match.group(2).strip()
        else:
            meta = {"id": path.stem}
            body = raw.strip()
        return PromptVersion(
            id=meta.get("id", path.stem),
            label=meta.get("label", meta.get("id", path.stem)),
            family_id=family_id,
            parent_id=meta.get("parent_id"),
            status=meta.get("status", "candidate"),
            author=meta.get("author", "unknown"),
            created_at=meta.get("created_at", ""),
            hypothesis=meta.get("hypothesis", ""),
            template_path=path,
            body=body,
            tags=list(meta.get("tags", [])),
            metadata={k: v for k, v in meta.items() if k not in {"id", "label", "parent_id", "status", "author", "created_at", "hypothesis", "tags"}},
        )

    def _load_experiment(self, path: Path) -> PromptExperiment:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        arms = [ExperimentArm(**arm) for arm in data.get("arms", [])]
        return PromptExperiment(
            id=data["id"],
            family_id=data["family_id"],
            name=data.get("name", data["id"]),
            status=data.get("status", "planned"),
            assignment_unit=data.get("assignment_unit", "run"),
            assignment_strategy=data.get("assignment_strategy", "deterministic_hash"),
            sticky=bool(data.get("sticky", True)),
            target_filter=data.get("target_filter", {}),
            arms=arms,
            primary_metrics=list(data.get("primary_metrics", [])),
            secondary_metrics=list(data.get("secondary_metrics", [])),
            started_at=data.get("started_at", ""),
            ended_at=data.get("ended_at", ""),
            winner_version_id=data.get("winner_version_id", ""),
            metadata={k: v for k, v in data.items() if k not in {
                "id", "family_id", "name", "status", "assignment_unit", "assignment_strategy",
                "sticky", "target_filter", "arms", "primary_metrics", "secondary_metrics",
                "started_at", "ended_at", "winner_version_id"
            }},
        )

    def _resolve_version_id(self, family: PromptFamily, version_ref: str) -> str:
        if version_ref == "latest":
            return self._latest_version_id(family.id)
        if version_ref in family.refs:
            return family.refs[version_ref]
        return version_ref

    def _latest_version_id(self, family_id: str) -> str:
        versions = self.list_versions(family_id)
        if not versions:
            raise FileNotFoundError(f"No prompt versions found for family: {family_id}")

        def sort_key(version: PromptVersion) -> tuple[int, float, str]:
            created_at = self._parse_timestamp(version.created_at)
            return (
                1 if created_at is not None else 0,
                created_at.timestamp() if created_at is not None else float("-inf"),
                version.template_path.name,
            )

        return max(versions, key=sort_key).id

    @staticmethod
    def _parse_timestamp(value: str) -> Optional[datetime]:
        if not value:
            return None
        normalized = value.replace("Z", "+00:00") if value.endswith("Z") else value
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed

    @staticmethod
    def _normalize_refs(current_version: Optional[str], refs: Optional[Dict[str, Any]]) -> Dict[str, str]:
        normalized = {
            str(name): str(version_id)
            for name, version_id in (refs or {}).items()
            if name and version_id and str(name) != "latest"
        }
        if current_version:
            normalized["current"] = str(current_version)
        if "current" not in normalized:
            raise KeyError("Prompt family is missing current_version / refs.current")
        return normalized

    def _family_manifest_data(
        self,
        *,
        family_id: str,
        name: str,
        description: str,
        current_version: str,
        artifact_kind: str,
        stage: str = "",
        refs: Optional[Dict[str, str]] = None,
        promotion_policy: Optional[PromotionPolicy] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        normalized_refs = self._normalize_refs(current_version, refs)
        data = {
            "id": family_id,
            "name": name,
            "description": description,
            "current_version": normalized_refs["current"],
            "refs": normalized_refs,
            "artifact_kind": artifact_kind,
            "stage": stage,
        }
        if promotion_policy is not None:
            data["promotion_policy"] = promotion_policy.to_dict()
        if metadata:
            data.update(metadata)
        return data
