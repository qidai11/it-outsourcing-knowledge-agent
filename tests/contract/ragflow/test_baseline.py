from project_agent.infrastructure.ragflow.baseline import (
    RAGFLOW_STABLE_VERSION,
    BASELINE_DATASET_BINDINGS,
)


def test_ragflow_baseline_is_pinned() -> None:
    assert RAGFLOW_STABLE_VERSION == "v0.26.4"
    assert BASELINE_DATASET_BINDINGS == {
        "company-public": "company-public",
        "PRJ-RETAIL-ALPHA": "client-a-project-alpha",
        "PRJ-LOGISTICS-BETA": "client-b-project-beta",
    }
