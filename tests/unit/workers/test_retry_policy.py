from project_agent.infrastructure.jobs.postgres import compute_retry_delay, should_retry


def test_exponential_retry_is_capped() -> None:
    assert compute_retry_delay(1, base_seconds=5, max_seconds=60) == 5
    assert compute_retry_delay(2, base_seconds=5, max_seconds=60) == 10
    assert compute_retry_delay(3, base_seconds=5, max_seconds=60) == 20
    assert compute_retry_delay(10, base_seconds=5, max_seconds=60) == 60


def test_max_attempts_turns_retry_into_terminal_failure() -> None:
    assert should_retry(attempt_count=1, max_attempts=3) is True
    assert should_retry(attempt_count=2, max_attempts=3) is True
    assert should_retry(attempt_count=3, max_attempts=3) is False
