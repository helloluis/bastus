"""Orphaned-run reconciliation after a control-plane restart."""

from __future__ import annotations

import pytest


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'o.db'}")
    import bastus.db.session as session

    session._db = None
    from bastus.db.session import Database

    return Database()


async def test_fail_orphaned_runs_marks_nonterminal_failed(db):
    from bastus.db import repo
    from bastus.models.run import RunConfig

    await db.create_all()
    running = await repo.create_run(db, RunConfig(enabled_categories=["S9"]))
    await repo.set_state(db, running, "running")
    done = await repo.create_run(db, RunConfig(enabled_categories=["S9"]))
    await repo.set_state(db, done, "report_ready")

    orphaned = await repo.fail_orphaned_runs(db)

    assert running in orphaned
    assert done not in orphaned  # terminal runs are left alone
    row = await repo.get_run(db, running)
    assert row.state == "failed" and "Interrupted" in row.error
    await db.dispose()
