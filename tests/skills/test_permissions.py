from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock

import pytest

from devfoundry.skills.permissions import (
    ConfirmationRequest,
    PermissionDenied,
    PermissionGate,
    SkillTier,
    default_cli_confirm,
    get_tier,
    tier,
)


@tier(SkillTier.READ_ONLY)
def read_only_skill(x: int) -> int:
    return x * 2


@tier(SkillTier.MUTATING)
def mutating_skill(x: int) -> int:
    return x + 1


@tier(SkillTier.DESTRUCTIVE)
def destructive_skill() -> str:
    return "done"


def undeclared_skill() -> None:
    ...


def test_get_tier_reads_declared_tier():
    assert get_tier(read_only_skill) == SkillTier.READ_ONLY
    assert get_tier(mutating_skill) == SkillTier.MUTATING
    assert get_tier(destructive_skill) == SkillTier.DESTRUCTIVE


def test_get_tier_raises_for_undeclared_skill():
    with pytest.raises(PermissionError):
        get_tier(undeclared_skill)


async def test_read_only_skill_runs_without_confirmation():
    confirm = AsyncMock(return_value=False)  # would decline if ever asked
    gate = PermissionGate(confirm)

    result = await gate.run(read_only_skill, 3, summary="double a number")

    assert result == 6
    confirm.assert_not_called()


async def test_mutating_skill_runs_when_confirmed():
    confirm = AsyncMock(return_value=True)
    gate = PermissionGate(confirm)

    result = await gate.run(mutating_skill, 3, summary="increment a number")

    assert result == 4
    confirm.assert_awaited_once()
    request = confirm.await_args.args[0]
    assert isinstance(request, ConfirmationRequest)
    assert request.tier == SkillTier.MUTATING
    assert request.skill_name == "mutating_skill"


async def test_mutating_skill_raises_and_never_runs_when_declined():
    confirm = AsyncMock(return_value=False)
    gate = PermissionGate(confirm)

    with pytest.raises(PermissionDenied):
        await gate.run(mutating_skill, 3, summary="increment a number")

    confirm.assert_awaited_once()


async def test_destructive_skill_always_confirms():
    confirm = AsyncMock(return_value=True)
    gate = PermissionGate(confirm)

    await gate.run(destructive_skill, summary="do something destructive")

    request = confirm.await_args.args[0]
    assert request.tier == SkillTier.DESTRUCTIVE


# --- default_cli_confirm -------------------------------------------------


async def test_default_cli_confirm_reads_yes(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("builtins.input", lambda prompt="": "y")
    request = ConfirmationRequest(skill_name="x", tier=SkillTier.MUTATING, summary="s")

    assert await default_cli_confirm(request) is True


async def test_default_cli_confirm_reads_no(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("builtins.input", lambda prompt="": "n")
    request = ConfirmationRequest(skill_name="x", tier=SkillTier.MUTATING, summary="s")

    assert await default_cli_confirm(request) is False


async def test_default_cli_confirm_does_not_block_event_loop(monkeypatch: pytest.MonkeyPatch):
    """input() must run off-thread (asyncio.to_thread), not inline in the
    coroutine — otherwise it would stall every other task sharing this
    event loop (e.g. other requests once this runs inside the FastAPI/
    WebSocket server) for as long as the user takes to answer. Proven here
    by making input() take real wall-clock time and asserting a
    concurrent asyncio task still makes progress while it's "blocked"."""
    monkeypatch.setattr("builtins.input", lambda prompt="": (time.sleep(0.2), "y")[1])
    request = ConfirmationRequest(skill_name="x", tier=SkillTier.MUTATING, summary="s")

    progress: list[int] = []

    async def ticker() -> None:
        for i in range(4):
            await asyncio.sleep(0.05)
            progress.append(i)

    confirm_task = asyncio.create_task(default_cli_confirm(request))
    ticker_task = asyncio.create_task(ticker())

    result = await confirm_task
    await ticker_task

    assert result is True
    assert progress == [0, 1, 2, 3]