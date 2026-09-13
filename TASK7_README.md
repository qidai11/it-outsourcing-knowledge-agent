# Task 7 — Identifier Extraction 与 Registry

## 状态

```text
TASK7_IMPLEMENTATION        = COMPLETE
TASK7_UNIT_GATE             = PASS
TASK7_LIVE_POSTGRES_GATE    = PENDING on environments without PostgreSQL
```

Task 7 不调用 Embedding，也不调用 RAGFlow Retrieval。Exact Identifier 的正式命中只依赖 PostgreSQL Registry。

## 支持类型

```text
project_code
requirement_id
issue_key
api_path
db_table
db_column
error_code
version
```

代表性示例：

```text
PRJ-ERP-2026
REQ-3.2.1
BUG-1842
/api/v2/import
t_order_detail
customer_id
E1027
ERR-IMPORT-004
v1.8.3
```

## 处理链

```text
Document / Query Text
        ↓
IdentifierExtractor
        ↓
regex + labeled structure parsing + SQL DDL structure parsing
        ↓
raw_value + normalized_value
        ↓
manual identifiers override automatic values by type
        ↓
IdentifierRegistryService
        ↓
document_identifiers
```

### Manual override 语义

如果人工确认提供某个 `identifier_type`，则该类型的人工集合取代自动提取集合，而不是简单追加。

例如：

```text
auto requirement_id: REQ-3.2.1
manual requirement_id: REQ-9.9.9
```

最终 Registry 对该版本只保留：

```text
REQ-9.9.9 source=manual
```

其它未被人工覆盖的类型（如 `/api/v1/import`）仍保留自动提取结果。

如果人工确认某一类型应当完全为空，可传 `manual_override_types` 覆盖该类型但不提供任何 manual value，从而删除自动误报。

## Exact 与 Fuzzy 必须分离

正式查询：

```sql
WHERE project_id = :project_id
  AND identifier_type = :identifier_type
  AND normalized_value = :normalized_value
```

对应既有 B-tree：

```text
idx_identifier_exact(
    project_id,
    identifier_type,
    normalized_value
)
```

拼写建议单独调用 `suggest_spelling()`，使用 PostgreSQL `pg_trgm similarity()` 与：

```text
idx_identifier_trgm(normalized_value gin_trgm_ops)
```

拼写建议只返回：

```text
IdentifierSpellingSuggestion
```

它不会自动改写用户输入，也不会被当成 Exact Hit。

## Migration

新增：

```text
migrations/versions/0002_identifier_trigram.py
```

执行：

```bash
uv run alembic upgrade head
```

它会执行：

```sql
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE INDEX idx_identifier_trgm
ON document_identifiers
USING gin (normalized_value gin_trgm_ops);
```

原有 `idx_identifier_exact` 不变。

## Gate 7

专项：

```bash
uv run pytest tests/unit/identifiers tests/integration/identifiers -v
```

没有真实 PostgreSQL 时，integration test 会明确 skip。

在线 PostgreSQL Gate：

```bash
export DATABASE_URL='postgresql+asyncpg://project_agent:project_agent@127.0.0.1:5432/project_agent'
export RUN_POSTGRES_INTEGRATION=1

uv run alembic upgrade head
uv run pytest tests/unit/identifiers tests/integration/identifiers -v
```

在线测试会验证：

- Alpha/Beta 同名 `REQ-3.2.1` 不串项目；
- 大小写输入经 deterministic normalization 后仍精确命中；
- 人工覆盖后旧自动值不再命中；
- `REQ-3.2.l` 只能产生 pg_trgm 拼写建议；
- `idx_identifier_exact` 和 `idx_identifier_trgm` 都存在；
- Exact 查询路径不依赖任何 vector/embedding 条件。

## 完整门禁

```bash
python scripts/run_checks.py
```

如果本机已经配置 PostgreSQL：

```bash
export RUN_POSTGRES_INTEGRATION=1
python scripts/run_checks.py
```

RAGFlow 在线 Gate 仍由 `RUN_RAGFLOW_INTEGRATION=1` 单独控制。
