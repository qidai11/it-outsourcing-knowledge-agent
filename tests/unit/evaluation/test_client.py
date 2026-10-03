"""Task 4 RED: real HTTP transport and identity-only authorization."""
import asyncio
import base64
import json
from uuid import uuid4

import httpx
import pytest

from project_agent.evaluation.client import EvaluationClient, EvaluationHttpError, EvaluationTimeout

SECRET = 't' * 40
PROJECT = uuid4()
USER = uuid4()
STATE = {'user_ids': {'u': str(USER)}, 'project_ids': {'alpha': str(PROJECT)}}


def token_claims(value: str) -> dict:
    encoded = value.split('.')[1]
    return json.loads(base64.urlsafe_b64decode(encoded + '=' * (-len(encoded) % 4)))


@pytest.mark.asyncio
async def test_client_creates_run_with_explicit_project_id_and_mode() -> None:
    seen = []
    def respond(request):
        seen.append((request, json.loads(request.content)))
        return httpx.Response(201, json={'run_id': str(uuid4()), 'thread_id': str(uuid4()),
                                          'status': 'QUEUED', 'project_id': str(PROJECT)})
    async with EvaluationClient(api_base_url='http://api.test', fixture_state=STATE,
                                jwt_secret=SECRET,
                                transport=httpx.MockTransport(respond)) as client:
        result = await client.create_run(user_alias='u', project_id=PROJECT,
                                         business_mode='qa', query='frozen question')
    assert result.http_status == 201
    assert seen[0][1] == {
        'project_id': str(PROJECT), 'business_mode': 'qa', 'query': 'frozen question',
    }
    assert seen[0][0].url.path == '/api/v1/runs'


@pytest.mark.asyncio
async def test_client_uses_identity_only_jwt() -> None:
    def respond(request):
        header = request.headers['authorization']
        assert header.startswith('Bearer ')
        assert set(token_claims(header[7:])) == {'sub', 'iss', 'aud', 'iat', 'nbf', 'exp'}
        assert token_claims(header[7:])['sub'] == str(USER)
        return httpx.Response(403, json={'detail': 'denied'})
    async with EvaluationClient(api_base_url='http://api.test', fixture_state=STATE,
                                jwt_secret=SECRET,
                                transport=httpx.MockTransport(respond)) as client:
        result = await client.create_run(user_alias='u', project_id=PROJECT,
                                         business_mode='qa', query='frozen', allow_denial=True)
    assert result.http_status == 403


@pytest.mark.asyncio
async def test_client_polls_until_terminal_status() -> None:
    values = iter(['QUEUED', 'RUNNING', 'SUCCEEDED'])
    def respond(request):
        return httpx.Response(200, json={'run_id': request.url.path.split('/')[-1],
                                          'status': next(values), 'thread_id': str(uuid4())})
    async with EvaluationClient(api_base_url='http://api.test', fixture_state=STATE,
                                jwt_secret=SECRET, transport=httpx.MockTransport(respond),
                                poll_interval_seconds=0.001) as client:
        result = await client.poll_run(user_alias='u', run_id=uuid4())
    assert result.status == 'SUCCEEDED'


@pytest.mark.asyncio
async def test_client_treats_waiting_confirmation_as_observable_nonterminal() -> None:
    def respond(request):
        return httpx.Response(200, json={'run_id': request.url.path.split('/')[-1],
                                          'status': 'WAITING_CONFIRMATION',
                                          'thread_id': str(uuid4())})
    async with EvaluationClient(api_base_url='http://api.test', fixture_state=STATE,
                                jwt_secret=SECRET, transport=httpx.MockTransport(respond),
                                poll_interval_seconds=0.001, run_timeout_seconds=0.03) as client:
        result = await client.poll_run(user_alias='u', run_id=uuid4(), until_waiting=True)
        assert result.status == 'WAITING_CONFIRMATION'
        with pytest.raises(EvaluationTimeout):
            await client.poll_run(user_alias='u', run_id=uuid4())


@pytest.mark.asyncio
async def test_client_has_bounded_http_and_run_timeouts() -> None:
    async def respond(request):
        await asyncio.sleep(0.08)
        return httpx.Response(200, json={'status': 'QUEUED'})
    async with EvaluationClient(api_base_url='http://api.test', fixture_state=STATE,
                                jwt_secret=SECRET, transport=httpx.MockTransport(respond),
                                http_timeout_seconds=0.01, run_timeout_seconds=0.05) as client:
        with pytest.raises(EvaluationTimeout):
            await client.poll_run(user_alias='u', run_id=uuid4())


@pytest.mark.asyncio
async def test_client_rejects_non_denial_http_error_without_logging_body() -> None:
    def respond(request):
        return httpx.Response(500, json={'detail': 'SECRET-DO-NOT-LOG'})
    async with EvaluationClient(api_base_url='http://api.test', fixture_state=STATE,
                                jwt_secret=SECRET,
                                transport=httpx.MockTransport(respond)) as client:
        with pytest.raises(EvaluationHttpError) as exc:
            await client.create_run(
                user_alias='u', project_id=PROJECT, business_mode='qa', query='q',
            )
    assert 'SECRET-DO-NOT-LOG' not in str(exc.value)


@pytest.mark.asyncio
async def test_client_run_deadline_cancels_slow_http_with_evaluation_timeout() -> None:
    async def respond(request):
        await asyncio.sleep(0.08)
        return httpx.Response(200, json={'run_id': request.url.path.split('/')[-1],
                                          'thread_id': str(uuid4()), 'status': 'RUNNING'})
    async with EvaluationClient(api_base_url='http://api.test', fixture_state=STATE,
                                jwt_secret=SECRET, transport=httpx.MockTransport(respond),
                                http_timeout_seconds=0.5, run_timeout_seconds=0.01) as client:
        with pytest.raises(EvaluationTimeout, match='Run state'):
            await client.poll_run(user_alias='u', run_id=uuid4())

@pytest.mark.asyncio
async def test_poll_run_retries_one_transient_get_transport_failure() -> None:
    calls = 0

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise httpx.ReadError("transient read failure", request=request)
        return httpx.Response(
            200,
            json={
                "run_id": request.url.path.split("/")[-1],
                "thread_id": str(uuid4()),
                "status": "SUCCEEDED",
            },
        )

    async with EvaluationClient(
        api_base_url="http://api.test",
        fixture_state=STATE,
        jwt_secret=SECRET,
        transport=httpx.MockTransport(respond),
        poll_interval_seconds=0.001,
        run_timeout_seconds=0.1,
    ) as client:
        result = await client.poll_run(user_alias="u", run_id=uuid4())

    assert result.status == "SUCCEEDED"
    assert calls == 2


@pytest.mark.asyncio
async def test_poll_run_transient_transport_failures_remain_bounded_by_run_deadline() -> None:
    calls = 0

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ConnectError("transient connect failure", request=request)

    async with EvaluationClient(
        api_base_url="http://api.test",
        fixture_state=STATE,
        jwt_secret=SECRET,
        transport=httpx.MockTransport(respond),
        poll_interval_seconds=0.001,
        run_timeout_seconds=0.02,
    ) as client:
        with pytest.raises(EvaluationTimeout, match="Run state"):
            await client.poll_run(user_alias="u", run_id=uuid4())

    assert calls > 1


@pytest.mark.asyncio
async def test_poll_run_does_not_retry_semantic_http_failure() -> None:
    calls = 0

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(503, json={"detail": "unavailable"})

    async with EvaluationClient(
        api_base_url="http://api.test",
        fixture_state=STATE,
        jwt_secret=SECRET,
        transport=httpx.MockTransport(respond),
        poll_interval_seconds=0.001,
        run_timeout_seconds=0.1,
    ) as client:
        with pytest.raises(EvaluationHttpError) as exc:
            await client.poll_run(user_alias="u", run_id=uuid4())

    assert exc.value.status == 503
    assert calls == 1




@pytest.mark.asyncio
async def test_poll_run_retries_transient_404_until_waiting_confirmation() -> None:
    calls = 0
    run_id = uuid4()
    thread_id = uuid4()

    def respond(request):
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(
                404,
                json={"detail": "run not found"},
            )
        return httpx.Response(
            200,
            json={
                "run_id": str(run_id),
                "thread_id": str(thread_id),
                "status": "WAITING_CONFIRMATION",
            },
        )

    async with EvaluationClient(
        api_base_url="http://api.test",
        fixture_state=STATE,
        jwt_secret=SECRET,
        transport=httpx.MockTransport(respond),
        waiting_timeout_seconds=0.05,
        poll_interval_seconds=0.001,
    ) as client:
        result = await client.poll_run(
            user_alias="u",
            run_id=run_id,
            until_waiting=True,
        )

    assert result.status == "WAITING_CONFIRMATION"
    assert calls == 2


@pytest.mark.asyncio
async def test_poll_run_persistent_404_is_bounded_by_waiting_deadline() -> None:
    calls = 0
    run_id = uuid4()

    def respond(request):
        nonlocal calls
        calls += 1
        return httpx.Response(
            404,
            json={"detail": "run not found"},
        )

    async with EvaluationClient(
        api_base_url="http://api.test",
        fixture_state=STATE,
        jwt_secret=SECRET,
        transport=httpx.MockTransport(respond),
        waiting_timeout_seconds=0.01,
        poll_interval_seconds=0.001,
    ) as client:
        with pytest.raises(
            EvaluationTimeout,
            match="Run state",
        ):
            await client.poll_run(
                user_alias="u",
                run_id=run_id,
                until_waiting=True,
            )

    assert calls >= 2


@pytest.mark.asyncio
async def test_poll_run_does_not_retry_forbidden_403() -> None:
    calls = 0
    run_id = uuid4()

    def respond(request):
        nonlocal calls
        calls += 1
        return httpx.Response(
            403,
            json={"detail": "forbidden"},
        )

    async with EvaluationClient(
        api_base_url="http://api.test",
        fixture_state=STATE,
        jwt_secret=SECRET,
        transport=httpx.MockTransport(respond),
        poll_interval_seconds=0.001,
    ) as client:
        with pytest.raises(EvaluationHttpError) as exc:
            await client.poll_run(
                user_alias="u",
                run_id=run_id,
            )

    assert exc.value.status == 403
    assert calls == 1
