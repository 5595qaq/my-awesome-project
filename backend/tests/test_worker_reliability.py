from unittest.mock import AsyncMock, MagicMock, patch

from app import main


class FakeLockConnection:
    def __init__(self, acquired=True, rows=None):
        self.acquired = acquired
        self.rows = rows or []
        self.commands = []
        self.closed = False

    async def fetchval(self, query, job_id):
        self.commands.append(("lock", job_id))
        return self.acquired

    async def execute(self, query, job_id):
        self.commands.append(("unlock", job_id))

    async def fetch(self, query):
        return self.rows

    async def close(self):
        self.closed = True


async def test_advisory_lock_winner_runs_job_and_releases_lock():
    connection = FakeLockConnection(acquired=True)
    session = MagicMock()
    main.dispatched_jobs.add("job-1")

    with patch("app.main.asyncpg.connect", new=AsyncMock(return_value=connection)), patch(
        "app.main.SessionLocal", return_value=session
    ), patch(
        "app.main.process_evaluation_job", new=AsyncMock()
    ) as process:
        await main._run_claimed_job("job-1")

    process.assert_awaited_once_with("job-1", session)
    assert connection.commands == [("lock", "job-1"), ("unlock", "job-1")]
    assert connection.closed
    assert "job-1" not in main.dispatched_jobs
    session.close.assert_called_once()


async def test_advisory_lock_loser_does_not_run_job():
    connection = FakeLockConnection(acquired=False)
    main.dispatched_jobs.add("job-2")

    with patch("app.main.asyncpg.connect", new=AsyncMock(return_value=connection)), patch(
        "app.main.process_evaluation_job", new=AsyncMock()
    ) as process:
        await main._run_claimed_job("job-2")

    process.assert_not_awaited()
    assert connection.commands == [("lock", "job-2")]
    assert connection.closed
    assert "job-2" not in main.dispatched_jobs


async def test_advisory_lock_is_released_when_job_runner_raises():
    connection = FakeLockConnection(acquired=True)
    session = MagicMock()
    main.dispatched_jobs.add("job-error")

    with patch("app.main.asyncpg.connect", new=AsyncMock(return_value=connection)), patch(
        "app.main.SessionLocal", return_value=session
    ), patch(
        "app.main.process_evaluation_job",
        new=AsyncMock(side_effect=RuntimeError("worker crashed")),
    ):
        await main._run_claimed_job("job-error")

    assert connection.commands == [
        ("lock", "job-error"),
        ("unlock", "job-error"),
    ]
    assert connection.closed
    assert "job-error" not in main.dispatched_jobs
    session.close.assert_called_once()


async def test_terminal_job_is_not_reprocessed_after_lock_race():
    connection = FakeLockConnection(acquired=True)
    session = MagicMock()
    session.query.return_value.filter.return_value.first.return_value.status = "finished"

    with patch("app.main.asyncpg.connect", new=AsyncMock(return_value=connection)), patch(
        "app.main.SessionLocal", return_value=session
    ), patch(
        "app.main.process_evaluation_job", new=AsyncMock()
    ) as process:
        await main._run_claimed_job("job-finished")

    process.assert_not_awaited()
    assert connection.commands == [
        ("lock", "job-finished"),
        ("unlock", "job-finished"),
    ]


async def test_recovery_queues_only_jobs_accepted_by_dispatch():
    connection = FakeLockConnection(rows=[{"id": "job-1"}, {"id": "job-2"}])
    with patch("app.main.asyncpg.connect", new=AsyncMock(return_value=connection)), patch(
        "app.main.dispatch_job", side_effect=[True, False]
    ) as dispatch:
        recovered = await main.recover_unfinished_jobs_once()

    assert recovered == ["job-1"]
    assert [call.args[0] for call in dispatch.call_args_list] == ["job-1", "job-2"]
    assert connection.closed
