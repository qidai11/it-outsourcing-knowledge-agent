# RAGFlow Baseline Runbook — Task 5

## 1. Baseline lock

V1 pins RAGFlow to:

```text
v0.26.4
infiniflow/ragflow:v0.26.4
```

Do not use `main`, `nightly`, or an unpinned image for acceptance testing.

RAGFlow must remain a separately deployed knowledge provider. The application does not read or write RAGFlow's internal MySQL/PostgreSQL/Redis/Elasticsearch/Infinity storage directly.

## 2. Why v0.26.4

As of the Task 5 baseline date (2026-08-08), RAGFlow's official quickstart labels `v0.26.4` as the stable release and explicitly recommends checking out the matching Git tag so `entrypoint.sh` matches the Docker image.

Official references:

- https://github.com/infiniflow/ragflow/blob/main/docs/quickstart.mdx
- https://github.com/infiniflow/ragflow/blob/main/docs/references/http_api_reference.md

## 3. Host preflight

```bash
uname -m
sysctl vm.max_map_count
docker --version
docker compose version
```

Expected architecture:

```text
x86_64
```

RAGFlow requires:

```text
vm.max_map_count >= 262144
```

Temporary setting:

```bash
sudo sysctl -w vm.max_map_count=262144
```

Persist it in `/etc/sysctl.conf` if required by your environment.

## 4. Deploy RAGFlow separately

Recommended path:

```bash
cd ~/workspace
git clone https://github.com/infiniflow/ragflow.git
cd ragflow
git checkout -f v0.26.4
cd docker
```

Confirm the image tag in `docker/.env` is pinned to `v0.26.4` before startup.

For the first integration gate, CPU DeepDoc is sufficient:

```bash
docker compose -f docker-compose.yml up -d
```

Follow logs until the RAGFlow server is fully initialized:

```bash
docker compose -f docker-compose.yml ps
docker compose -f docker-compose.yml logs -f ragflow-cpu
```

Container names can vary by Compose version/project name. Use `docker compose ps` if the log service name differs.

## 5. Configure an embedding model before parsing

The three baseline datasets must use a working embedding model. Configure one in the RAGFlow UI before running the live integration test.

Once a dataset has parsed documents using one embedding model, do not change that dataset to another embedding model. Create a new dataset if the embedding space must change.

Set the exact RAGFlow model identifier if you want dataset creation to pin it:

```dotenv
RAGFLOW_EMBEDDING_MODEL=<model_name@provider>
```

If blank, RAGFlow uses the account's configured/default embedding model.

## 6. Acquire API key

Create a RAGFlow API key in the RAGFlow UI and set the application `.env`:

```dotenv
RAGFLOW_BASE_URL=http://127.0.0.1:9380
RAGFLOW_API_KEY=<real-key>
RAGFLOW_EXPECTED_VERSION=v0.26.4
RAGFLOW_IMAGE=infiniflow/ragflow:v0.26.4
RAGFLOW_CHUNK_METHOD=naive
RAGFLOW_REQUEST_TIMEOUT_SECONDS=30
RAGFLOW_MAX_ATTEMPTS=3
```

Never commit the real key.

## 7. Verify health, API baseline, and create datasets

From the application repository:

```bash
conda activate it-agent
cd ~/workspace/it-outsourcing-knowledge-agent
export UV_PROJECT_ENVIRONMENT="$CONDA_PREFIX"

uv run python scripts/check_ragflow_version.py \
  --image infiniflow/ragflow:v0.26.4 \
  --ensure-datasets
```

Expected datasets:

```text
company-public
client-a-project-alpha
client-b-project-beta
```

The RAGFlow health endpoint does not expose a reliable server-version field. Therefore Task 5 enforces version by the deployment image/tag plus `RAGFLOW_EXPECTED_VERSION`, and independently checks `/api/v1/system/healthz` and authenticated `/api/v1/datasets` compatibility.

## 8. Adapter mapping rule

Every uploaded document is updated with RAGFlow `meta_fields` before parsing starts:

```text
project_agent_project_id
project_agent_document_version_id
```

Retrieval sends a project metadata filter to RAGFlow and then performs a second application-side check:

```text
allowed dataset ID
+ mapped project ID
+ mapped document_version_id
```

A provider Chunk that cannot be mapped to an application `document_version_id` is discarded and never becomes `KnowledgeChunk` / Agent Evidence.

## 9. Retry rule

The shared HTTP boundary retries only bounded transient failures:

```text
HTTP 429
HTTP 5xx
httpx timeout/network errors
```

Default maximum attempts:

```text
3
```

Application-level RAGFlow errors (`HTTP 200` with `code != 0`) fail immediately rather than being retried blindly.

## 10. Run Task 5 contract gate

```bash
uv run pytest tests/contract/ragflow -v
```

No live RAGFlow is required for this gate.

## 11. Run real RAGFlow isolation gate

After RAGFlow and the embedding model are ready:

```bash
export RUN_RAGFLOW_INTEGRATION=1
uv run pytest tests/integration/ragflow -v
```

The integration test uploads one Alpha document and one Beta document, parses both, queries Alpha, and asserts that Beta evidence never appears in the returned `KnowledgeChunk` list.

The test cleans up its two temporary documents in a `finally` block.

## 12. Gate 5 definition

Gate 5 is complete only when both are true:

```text
Contract mapping/isolation tests: PASS
Real RAGFlow project-isolation test: PASS
```

If the real integration test is skipped, Task 5 implementation is present but the live provider gate is still pending.
