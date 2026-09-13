# V1 Scope Freeze

> 版本：v0.1  
> 产品定位：`internal-first, external-ready`

## 1. V1 一句话目标

构建一个供公司内部项目成员使用的“项目交付知识检索 + 历史 Issue 查询 + Issue 草稿 + 人工确认 + Sandbox 幂等创建”闭环。

## 2. V1 只实现两个业务场景

### 场景 A：项目交付知识问答

流程：

```text
身份
→ 项目访问范围
→ Query Analysis
→ Exact Identifier Resolver
→ 检索范围限制
→ RAGFlow Hybrid Retrieval
→ Authority / Version Filter
→ Evidence Packing
→ Answer
→ Citation Guard
```

### 场景 B：历史 Issue 查询与 Sandbox 工单创建

流程：

```text
项目识别
→ 需求/测试/历史问题证据
→ Sandbox Issue 检索
→ possible_duplicates
→ Issue Draft
→ 用户确认
→ 幂等创建
→ Sandbox Issue Key
```

## 3. V1 In Scope

- FastAPI API；
- LangGraph 工作流编排；
- PostgreSQL 业务数据、Job Queue、Checkpoint；
- RAGFlow 文档解析、Chunk、Hybrid Retrieval、V1 Rerank；
- 本地文件存储；
- 项目级访问控制；
- 文档版本和人工权威治理；
- Exact Identifier Registry；
- Citation Guard；
- Sandbox Issue；
- 用户确认；
- `client_request_id` 幂等；
- JSON 日志；
- 基础 Prometheus 指标；
- Run 级模型、Token、OCR、检索轮数和估算成本记录；
- Prompt 版本快照；
- Retention Policy 与 legal hold 字段。

## 4. V1 Out of Scope

- 生产 Jira / 禅道 / 飞书项目写入；
- 多 Agent；
- 长期 Memory；
- 自动修改代码；
- 自动发布生产；
- 自动合并 PR；
- 自动合同责任判断；
- 自动报价和工期估算；
- 自动把文件判定为正式合同；
- LLM 自动发布文档；
- AI 自动认定重复 Issue；
- 客户 Guest；
- SaaS 多租户；
- 客户账单；
- 全局 Budget Guard；
- Redis / ARQ / Celery；
- 独立 MinIO；
- Kubernetes；
- 第二套向量数据库；
- GraphRAG / RAPTOR。

## 5. 知识空间

| knowledge_space | scope | V1 |
|---|---|---|
| `company-public` | 公司公共规范 | 启用 |
| `client-a-project-alpha` | `PRJ-RETAIL-ALPHA` | 启用 |
| `client-b-project-beta` | `PRJ-LOGISTICS-BETA` | 启用 |

## 6. V1 P0 安全不变量

```text
跨客户 Evidence = 0
跨项目 Evidence = 0
未参与项目访问 = 0
DELETE_PENDING 文档召回 = 0
跨项目 Citation = 0
未确认创建 Issue = 0
重复副作用 = 0
```

## 7. V1 验收目标

> 下列值是**目标**，不是当前实测成绩。

| 指标 | 目标 |
|---|---:|
| Exact-Identifier Hit@10 | ≥ 95% |
| Evidence Recall@10 | ≥ 90% |
| Current-Version Hit Rate | ≥ 95% |
| Citation ID Validity | 100% |
| 无答案拒答准确率 | ≥ 90% |
| 跨项目 Evidence | 0 |
| 未确认 Issue 创建 | 0 |
| 重复 Issue 副作用 | 0 |
| Critical Regression | 100% |

## 8. 进入 V1.5 的条件

只有当 V1 已经证明：

- 内部成员持续使用；
- 文档持续更新；
- 引用可用于复核；
- 项目级权限稳定；
- 单项目成本可接受；

才讨论客户只读 Guest PoC。
