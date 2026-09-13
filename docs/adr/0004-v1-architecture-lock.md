# ADR-0004: V1 Core Architecture Lock

- Status: Accepted
- Date: 2026-08-08
- Decision Scope: V1

## Context

项目目标是在有限人员、有限服务器和较短实习周期内完成一个可信、可运行、可评测的 IT 外包项目交付知识 Agent。

最大风险不是“技术不够多”，而是范围失控、边界不清、模拟能力被误写成生产能力。

## Decision

V1 锁定：

```text
FastAPI
+ LangGraph
+ PostgreSQL
+ PostgreSQL Job Queue
+ RAGFlow（固定稳定版本，后续 Task 冻结）
+ LocalFileObjectStoreAdapter
+ SandboxProjectTrackerAdapter
```

并锁定：

```text
ProjectAccessScope
+ Identifier Registry
+ AuthorityPolicy
+ Citation Guard
+ 用户确认
+ client_request_id 幂等
```

## Allowed Changes

- Prompt 内容和版本；
- 文档枚举；
- RAGFlow 参数；
- Worker 并发/限流；
- 评测集；
- Sandbox Issue 字段；
- PostgreSQL 字段和索引；
- 模块内部实现。

## Prohibited in V1

- Redis / ARQ / Celery 替换 PostgreSQL Job Queue；
- 独立 MinIO；
- 第二套向量数据库；
- 多 Agent；
- SaaS 多租户；
- Kubernetes；
- 生产 Jira/禅道/飞书项目写入；
- LLM 自动发布文档；
- AI 自动判断 Issue 业务重复。

## Consequences

优点：

- 降低环境与运维复杂度；
- 业务边界更容易测试；
- 可逐 Task 做回归；
- 面试时职责与设计动机更清楚。

代价：

- 单 Worker；
- 本地文件存储；
- 不支持生产级多副本全局限流；
- Sandbox 不能等价于真实工单系统；
- V2 产品化需要重新评审。

## Revisit Conditions

只有以下情况才能新建 ADR 讨论修改核心架构：

1. 当前组件存在经过复现实验确认的硬性功能缺口；
2. 真实业务量级超过单机架构边界；
3. 安全/合规要求强制引入新基础设施；
4. 评测证明当前方案无法满足 V1 验收目标。

不得因为“技术更流行”改变架构。
