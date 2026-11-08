import asyncio
import subprocess
from types import SimpleNamespace

import pytest

from cast.media_probe import media_probe_budget, media_probe_budget_active, remaining_probe_timeout


def test_nested_budget_keeps_tightest_deadline_and_restores_parent(monkeypatch):
    clock = SimpleNamespace(now=100.0)
    monkeypatch.setattr("cast.media_probe.time", SimpleNamespace(monotonic=lambda: clock.now))
    with media_probe_budget(1):
        with media_probe_budget(100):
            assert remaining_probe_timeout(30) == 1
        with pytest.raises(RuntimeError):
            with media_probe_budget(0.25):
                assert remaining_probe_timeout(30) == 0.25
                raise RuntimeError("nested operation failed")
        assert remaining_probe_timeout(30) == 1
        clock.now += 2
        with media_probe_budget(100), pytest.raises(subprocess.TimeoutExpired):
            remaining_probe_timeout(30)
    assert not media_probe_budget_active()
    assert remaining_probe_timeout(30) == 30


def test_nested_budgets_remain_isolated_between_async_tasks(monkeypatch):
    monkeypatch.setattr("cast.media_probe.time", SimpleNamespace(monotonic=lambda: 100.0))

    async def exercise():
        ready = [asyncio.Event(), asyncio.Event()]
        proceed = asyncio.Event()

        async def worker(index, seconds):
            with media_probe_budget(seconds):
                ready[index].set()
                await proceed.wait()
                with media_probe_budget(100):
                    result = remaining_probe_timeout(30)
            assert not media_probe_budget_active()
            return result

        tasks = [asyncio.create_task(worker(0, 1)), asyncio.create_task(worker(1, 10))]
        await asyncio.gather(*(event.wait() for event in ready))
        assert not media_probe_budget_active()
        proceed.set()
        return await asyncio.gather(*tasks)

    assert asyncio.run(exercise()) == [1, 10]
    assert not media_probe_budget_active()
