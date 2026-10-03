"""Deterministic, atomic and secret-safe evaluation artifact IO."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from collections.abc import Mapping
from contextlib import suppress
from dataclasses import fields, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import UUID

_BEARER_RE = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{8,}")
_JWT_RE = re.compile(
    r"(?<![A-Za-z0-9_-])[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"
    r"(?![A-Za-z0-9_-])"
)
_CREDENTIAL_URL_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*://[^/@:\s]+:[^/@\s]+@")
_SECRET_KEY_MARKERS = (
    "authorization",
    "api_key",
    "apikey",
    "password",
    "database_url",
    "jwt",
)


class SecretArtifactError(ValueError):
    """Raised when a payload contains a field/value that may expose credentials."""


def _normalise_key(key: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", key.casefold()).strip("_")


def _is_secret_key(key: str) -> bool:
    normalised = _normalise_key(key)
    return any(marker in normalised for marker in _SECRET_KEY_MARKERS)


def _to_jsonable(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, UUID):
        return str(value)
    if is_dataclass(value) and not isinstance(value, type):
        return {item.name: _to_jsonable(getattr(value, item.name)) for item in fields(value)}
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("evaluation artifact mappings require string keys")
            result[key] = _to_jsonable(item)
        return result
    if isinstance(value, (tuple, list)):
        return [_to_jsonable(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return _to_jsonable(model_dump(mode="json"))
    raise TypeError(f"unsupported evaluation artifact value: {type(value).__name__}")


def _assert_secret_safe(value: Any, *, path: str = "$") -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if _is_secret_key(str(key)):
                raise SecretArtifactError(f"secret-like field is forbidden at {path}.{key}")
            _assert_secret_safe(item, path=f"{path}.{key}")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _assert_secret_safe(item, path=f"{path}[{index}]")
        return
    if isinstance(value, str):
        if _BEARER_RE.search(value):
            raise SecretArtifactError(f"Bearer token is forbidden at {path}")
        if _JWT_RE.search(value):
            raise SecretArtifactError(f"JWT-like value is forbidden at {path}")
        if _CREDENTIAL_URL_RE.search(value):
            raise SecretArtifactError(f"credential-bearing URL is forbidden at {path}")


def _safe_segment(value: str, *, label: str) -> str:
    if not value or value in {".", ".."} or "/" in value or "\\" in value:
        raise ValueError(f"invalid {label}: {value!r}")
    return value


class ArtifactStore:
    """Write deterministic files under one evaluation run directory."""

    def __init__(self, artifact_root: Path, evaluation_run_id: str) -> None:
        run_id = _safe_segment(evaluation_run_id, label="evaluation_run_id")
        self.artifact_root = artifact_root
        self.evaluation_run_id = run_id
        self.root = artifact_root / run_id

    @property
    def run_manifest_path(self) -> Path:
        return self.root / "run-manifest.json"

    @property
    def fixture_state_path(self) -> Path:
        return self.root / "fixture-state.json"

    @property
    def metrics_path(self) -> Path:
        return self.root / "metrics.json"

    @property
    def ablations_dir(self) -> Path:
        return self.root / "ablations"

    @property
    def report_json_path(self) -> Path:
        return self.root / "report.json"

    @property
    def report_markdown_path(self) -> Path:
        return self.root / "report.md"

    def trial_path(self, case_id: str, trial_no: int) -> Path:
        case = _safe_segment(case_id, label="case_id")
        if trial_no < 1:
            raise ValueError("trial_no must be >= 1")
        return self.root / "cases" / case / f"trial-{trial_no:03d}.json"

    def write_json(self, path: Path, payload: Any) -> str:
        """Atomically write canonical UTF-8 JSON and return its SHA256 hex digest."""

        jsonable = _to_jsonable(payload)
        _assert_secret_safe(jsonable)
        encoded = (
            json.dumps(
                jsonable,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
            + "\n"
        ).encode("utf-8")
        digest = hashlib.sha256(encoded).hexdigest()

        path.parent.mkdir(parents=True, exist_ok=True)
        temp_name: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                dir=path.parent,
                prefix=f".{path.name}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                temp_name = handle.name
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, path)
            temp_name = None
        finally:
            if temp_name is not None:
                with suppress(FileNotFoundError):
                    os.unlink(temp_name)
        return digest
