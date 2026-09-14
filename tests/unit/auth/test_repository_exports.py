from project_agent.infrastructure.db import repositories


def test_repository_package_preserves_previous_exports_and_adds_run_repository() -> None:
    assert set(repositories.__all__) == {
        "SqlAlchemyDocumentWorkflowRepository",
        "SqlAlchemyIdentifierRegistryRepository",
        "SqlAlchemyProjectAuthorizationRepository",
        "SqlAlchemyRunRepository",
    }
