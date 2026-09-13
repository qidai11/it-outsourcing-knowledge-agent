from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import select

from project_agent.infrastructure.db.models.schema import (
    ClientModel,
    ProjectModel,
    SandboxIssueModel,
    SandboxProjectModel,
)
from project_agent.infrastructure.db.session import create_engine, create_session_factory


def stable_uuid(name: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"project-agent-task12:{name}")


COMPANY_ID = stable_uuid("company-demo")
MANAGER_ID = stable_uuid("manager")
REPORTER_ID = stable_uuid("reporter")


@dataclass(frozen=True, slots=True)
class ProjectSeed:
    code: str
    name: str
    client_name: str
    external_key: str


PROJECTS = (
    ProjectSeed(
        code="PRJ-RETAIL-ALPHA",
        name="订单与库存协同平台升级项目",
        client_name="华东智零售集团（模拟）",
        external_key="ALPHA",
    ),
    ProjectSeed(
        code="PRJ-LOGISTICS-BETA",
        name="运输结算平台改造项目",
        client_name="远海供应链集团（模拟）",
        external_key="BETA",
    ),
)


ISSUES = {
    "PRJ-RETAIL-ALPHA": (
        (
            "ALPHA-101", "CSV import fails with invalid encoding",
            "UAT import returns ERR-IMPORT-004. Root cause is invalid CSV encoding.",
            "OPEN", "high", "import", "ERR-IMPORT-004",
        ),
        (
            "ALPHA-102", "CSV import fails after gateway timeout",
            "The same ERR-IMPORT-004 is exposed, but root cause is upstream gateway timeout.",
            "RESOLVED", "medium", "import", "ERR-IMPORT-004",
        ),
        (
            "ALPHA-103", "CSV import fails with invalid encoding",
            "Parser validation returns ERR-IMPORT-005; root cause differs from ALPHA-101.",
            "OPEN", "medium", "import", "ERR-IMPORT-005",
        ),
    ),
    "PRJ-LOGISTICS-BETA": (
        (
            "BETA-201", "CSV import fails with invalid encoding",
            "Beta intentionally reuses ERR-IMPORT-004 to test cross-project isolation.",
            "OPEN", "high", "import", "ERR-IMPORT-004",
        ),
        (
            "BETA-202", "Settlement import gateway timeout",
            "Transport settlement import fails because the partner gateway times out.",
            "IN_PROGRESS", "medium", "settlement", "ERR-SETTLE-009",
        ),
    ),
}


async def main() -> int:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise SystemExit("DATABASE_URL is required")
    engine = create_engine(database_url)
    session_factory = create_session_factory(engine)
    try:
        async with session_factory() as session:
            for seed in PROJECTS:
                project = (
                    await session.scalars(
                        select(ProjectModel).where(
                            ProjectModel.company_id == COMPANY_ID,
                            ProjectModel.code == seed.code,
                        )
                    )
                ).one_or_none()
                if project is None:
                    client_id = stable_uuid(f"client:{seed.code}")
                    client = await session.get(ClientModel, client_id)
                    if client is None:
                        client = ClientModel(
                            id=client_id,
                            company_id=COMPANY_ID,
                            name=seed.client_name,
                        )
                        session.add(client)
                        await session.flush()
                    project = ProjectModel(
                        id=stable_uuid(f"project:{seed.code}"),
                        company_id=COMPANY_ID,
                        client_id=client.id,
                        code=seed.code,
                        name=seed.name,
                        phase="sandbox",
                        manager_id=MANAGER_ID,
                    )
                    session.add(project)
                    await session.flush()

                sandbox = (
                    await session.scalars(
                        select(SandboxProjectModel).where(
                            SandboxProjectModel.project_id == project.id
                        )
                    )
                ).one_or_none()
                if sandbox is None:
                    sandbox = SandboxProjectModel(
                        id=stable_uuid(f"sandbox:{seed.code}"),
                        project_id=project.id,
                        external_key=seed.external_key,
                        name=f"{seed.name} Sandbox",
                    )
                    session.add(sandbox)
                    await session.flush()

                for (
                    issue_key, title, description, status, priority, module, error_code
                ) in ISSUES[seed.code]:
                    issue = (
                        await session.scalars(
                            select(SandboxIssueModel).where(
                                SandboxIssueModel.project_id == project.id,
                                SandboxIssueModel.issue_key == issue_key,
                            )
                        )
                    ).one_or_none()
                    if issue is None:
                        issue = SandboxIssueModel(
                            id=stable_uuid(f"issue:{issue_key}"),
                            project_id=project.id,
                            sandbox_project_id=sandbox.id,
                            issue_key=issue_key,
                            title=title,
                            description=description,
                            issue_type="bug",
                            priority=priority,
                            status=status,
                            module=module,
                            error_code=error_code,
                            environment="uat",
                            reporter_id=REPORTER_ID,
                            source="sandbox",
                        )
                        session.add(issue)
                    else:
                        issue.title = title
                        issue.description = description
                        issue.status = status
                        issue.priority = priority
                        issue.module = module
                        issue.error_code = error_code
                await session.flush()
            await session.commit()
        print("[PASS] Task 12 sandbox seeded")
        for code, rows in ISSUES.items():
            print(f"       {code}: {len(rows)} issues")
        return 0
    finally:
        await engine.dispose()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
