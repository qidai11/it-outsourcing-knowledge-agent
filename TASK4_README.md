# Task 4 — LocalFileObjectStoreAdapter

## 目标

实现 V1 单机部署下的真实源文件存储 Adapter，并严格保持 `ObjectStorePort` 边界。

本阶段只负责源文件本地持久化，不接 MinIO/S3，不负责 RAGFlow 入库，也不负责文档数据库事务。

## 物理存储布局

`LOCAL_STORAGE_ROOT` 默认由 `.env` 配置为：

```text
./data
```

每次 `put()` 都生成 UUID，对象完整落盘后返回规范化 `object_key`：

```text
projects/{project_id}/objects/{uuid}
```

真实目录：

```text
data/
├── .tmp/
└── projects/
    └── {project_id}/
        └── objects/
            └── {uuid}/
                ├── payload.bin
                └── metadata.json
```

`metadata.json` 保存：

```text
project_id
logical_object_key
storage_key
size_bytes
sha256
mime_type
```

调用方上传时传入的 `object_key` 只是逻辑源名称，例如：

```text
source/requirements-v2.pdf
```

它不会直接拼接为最终物理文件路径。

## 为什么使用 UUID 目录

避免直接使用用户文件名作为物理路径，从根本上降低：

- 同名文件覆盖；
- 特殊字符路径问题；
- 用户控制磁盘目录结构；
- 文件名泄漏业务信息；
- 后续切换 S3/MinIO 时 key 语义不稳定。

## 原子写入

写入过程：

```text
生成 UUID
  ↓
创建 .tmp/{uuid}.partial/
  ↓
写 payload.bin + fsync
  ↓
写 metadata.json + fsync
  ↓
fsync staging directory
  ↓
os.replace(staging_dir, final_dir)
  ↓
完整对象一次性可见
```

由于临时目录与最终目录位于同一个 `LOCAL_STORAGE_ROOT` 文件系统内，最终目录 rename 是本地文件系统原子操作。

若 rename 前失败：

- 最终对象目录不存在；
- 当前写入创建的 partial 目录会清理；
- 读取端不会观察到半份 payload / metadata。

若相同 UUID 的 `.partial` 已经存在，则拒绝新写入，避免覆盖未知的未完成写入。

## 路径安全

Adapter 拒绝：

```text
../
source/../../...
POSIX absolute path
Windows absolute path / drive path
backslash path
非法 storage key
symlink project directory escape
symlink object directory escape
```

`get / exists / delete` 不接受任意磁盘路径，只接受 Adapter 自己生成的严格格式：

```text
projects/{safe_project_id}/objects/{canonical_uuid}
```

## SHA256 与 MIME

`put()` 计算：

```text
sha256 = SHA256(payload bytes)
```

并将 SHA256、MIME、文件大小和逻辑源 key 一并写入 `metadata.json`。

`get()` 会重新计算 SHA256，并检查：

```text
actual SHA256 == metadata SHA256
actual size   == metadata size
storage key   == metadata storage key
```

不一致时抛出 `ObjectStoreCorruptionError`，不会静默返回损坏文件。

## 删除语义

```text
delete(existing) → 删除整个 UUID 对象目录
delete(missing)  → no-op
```

删除前仍执行 storage key 与 symlink 安全检查。

注意：Task 4 的 `delete()` 是基础文件能力。正式文档物理删除仍必须在后续业务流程中经过：

```text
DELETE_PENDING
→ Retention Policy
→ archive_before_delete
→ legal_hold
→ Audit
→ ObjectStore.delete
```

因此不能绕过 Task 0/2 的治理规则直接把 `ObjectStorePort.delete()` 暴露给用户。

## Gate 4 测试

```bash
uv run pytest tests/unit/object_store tests/security/test_path_traversal.py -v
```

覆盖：

- Port round-trip；
- UUID 物理路径；
- SHA256；
- MIME metadata；
- get / exists / delete；
- 成功写入不残留 partial；
- 重复 partial write 拒绝；
- rename 失败时不暴露最终对象；
- `../`；
- POSIX absolute；
- Windows absolute；
- 非 UUID storage key；
- project symlink escape；
- object symlink escape。

## 完整回归

```bash
python scripts/run_checks.py
```

如果还要执行 Task 2 的真实 PostgreSQL 在线门禁：

```bash
export DATABASE_URL='postgresql+asyncpg://project_agent:project_agent@127.0.0.1:5432/project_agent'
export RUN_POSTGRES_INTEGRATION=1
python scripts/run_checks.py
```

## Git 提交

Gate 4 通过后：

```bash
git add \
  src/project_agent/infrastructure/object_store \
  tests/__init__.py \
  tests/unit/object_store \
  tests/security \
  scripts/run_checks.py \
  README.md \
  TASK4_README.md

git commit -m "feat: add secure local source storage"
```
