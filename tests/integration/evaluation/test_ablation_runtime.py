from __future__ import annotations

from pathlib import Path

import pytest

import project_agent.runtime.qa as qa_runtime
from project_agent.evaluation import variants


def test_live_variant_uses_same_project_authorization() -> None:
    factory = getattr(variants, "qa_runtime_composition_for_variant", None)
    assert callable(factory), "Task 7 live composition is not implemented"
    composition = factory("no_exact_registry")
    assert isinstance(composition, qa_runtime.QARuntimeComposition)
    assert not hasattr(composition, "authorization")
    assert not hasattr(composition, "membership")


def test_live_variant_uses_same_ragflow_project_dataset() -> None:
    factory = getattr(variants, "qa_runtime_composition_for_variant", None)
    assert callable(factory), "Task 7 live composition is not implemented"
    composition = factory("single_round_only")
    assert not hasattr(composition, "knowledge")
    assert not hasattr(composition, "dataset")


def test_live_variant_preserves_confirmation_and_idempotency() -> None:
    composition_type = getattr(qa_runtime, "QARuntimeComposition", None)
    assert composition_type is not None, "Task 7 QA runtime composition is not implemented"
    fields = getattr(composition_type, "__dataclass_fields__", {})
    assert set(fields) == {"exact_resolver_factory", "allow_second_round"}
    worker_path = (
        Path(__file__).resolve().parents[3]
        / "src"
        / "project_agent"
        / "runtime"
        / "worker.py"
    )
    assert "ABLATION" not in worker_path.read_text(encoding="utf-8").upper()


def test_shadow_ablations_require_no_live_runtime() -> None:
    factory = getattr(variants, "qa_runtime_composition_for_variant", None)
    assert callable(factory), "Task 7 live composition is not implemented"
    for name in ("pre_governance_shadow", "pre_guard_shadow"):
        with pytest.raises(ValueError, match="shadow"):
            factory(name)
