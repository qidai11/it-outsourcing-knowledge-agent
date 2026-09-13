from project_agent.infrastructure.db import repositories


def test_repository_package_preserves_previous_exports() -> None:
    assert set(repositories.__all__) == {
        "SqlAlchemyDocumentWorkflowRepository",
        "SqlAlchemyIdentifierRegistryRepository",
        "SqlAlchemyProjectAuthorizationRepository",
    }
