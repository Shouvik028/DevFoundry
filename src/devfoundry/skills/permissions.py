"""Permission-tier primitive for skill execution (spec 5: read-only skills
run free; mutating skills require confirmation; destructive ops always
confirm, even in background mode).

Skills declare their tier via `@tier(...)`. The orchestrator never calls a
gated skill directly — it routes every call through `PermissionGate.run()`,
which is the single point (spec 3.1) that decides whether to confirm
before executing. `ConfirmCallback` is the swap point: today it's a
blocking terminal prompt; later it can await a REST/WebSocket approval
without PermissionGate or any skill changing shape.

There is deliberately no bypass path for DESTRUCTIVE anywhere in this
module. If a background/unattended mode is added later, only MUTATING
should ever become eligible for a pre-approved policy — DESTRUCTIVE must
keep going through `confirm()` unconditionally.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, TypeVar

R = TypeVar("R")


class SkillTier(str, Enum):
    READ_ONLY = "read_only"
    MUTATING = "mutating"
    DESTRUCTIVE = "destructive"


_TIER_ATTR = "_devfoundry_skill_tier"


def tier(level: SkillTier) -> Callable[[Callable[..., R]], Callable[..., R]]:
    """Decorator: declares a skill function's permission tier. Every skill
    routed through PermissionGate must carry this, including read-only
    ones — an undeclared tier is treated as a bug (see `get_tier`), never
    a silent free pass."""

    def decorator(fn: Callable[..., R]) -> Callable[..., R]:
        setattr(fn, _TIER_ATTR, level)
        return fn

    return decorator


def get_tier(fn: Callable[..., Any]) -> SkillTier:
    """Look up a skill's declared tier. Raises PermissionError if `fn` was
    never decorated with `@tier(...)` — fail closed rather than guessing."""
    level = getattr(fn, _TIER_ATTR, None)
    if level is None:
        name = getattr(fn, "__name__", repr(fn))
        raise PermissionError(
            f"{name} has no declared SkillTier — decorate it with @tier(...) "
            "before routing it through PermissionGate."
        )
    return level


@dataclass
class ConfirmationRequest:
    """What the orchestrator hands to a confirmation callback before
    running a mutating/destructive skill. Deliberately plain data (no
    behavior) so any interface — CLI prompt, future REST/WebSocket
    endpoint — can render and answer it without importing anything
    skill-specific."""

    skill_name: str
    tier: SkillTier
    summary: str
    details: dict[str, Any] = field(default_factory=dict)


ConfirmCallback = Callable[[ConfirmationRequest], Awaitable[bool]]


class PermissionDenied(Exception):
    """Raised when a confirmation callback declines a mutating/destructive
    skill call. The skill is never invoked in this case."""


def _prompt_cli_confirm(request: ConfirmationRequest) -> bool:
    print(f"\n[confirm required] {request.skill_name} ({request.tier.value})")
    print(request.summary)
    for key, value in request.details.items():
        print(f"  {key}: {value}")
    answer = input("Proceed? [y/N] ").strip().lower()
    return answer in ("y", "yes")


async def default_cli_confirm(request: ConfirmationRequest) -> bool:
    """Blocking terminal y/n prompt. Suitable default while DevFoundry is
    CLI-only; pass a different ConfirmCallback to PermissionGate/
    Orchestrator once a dashboard/API can answer confirmations instead.

    Runs the actual input() call via asyncio.to_thread rather than inline:
    input() blocks the whole thread, and this coroutine may share an event
    loop with other work (e.g. once the orchestrator runs inside the
    FastAPI/WebSocket server, spec 3.6) that shouldn't stall while this
    one waits on stdin."""
    return await asyncio.to_thread(_prompt_cli_confirm, request)


class PermissionGate:
    """Single enforcement point for permission tiers (spec 3.1: 'a single
    place to enforce permissions'). The orchestrator owns one instance and
    routes every gated skill call through `run()` instead of calling skill
    functions directly."""

    def __init__(self, confirm: ConfirmCallback | None = None) -> None:
        self._confirm = confirm or default_cli_confirm

    async def run(
        self,
        fn: Callable[..., R],
        *args: Any,
        summary: str,
        details: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> R:
        """Run `fn(*args, **kwargs)`, confirming first if its declared
        tier is above READ_ONLY. `summary`/`details` describe the call for
        the confirmation prompt — they're keyword-only and required so
        callers can't forget to explain what they're asking to confirm.

        Raises PermissionDenied if the confirmation callback declines;
        `fn` is never called in that case.
        """
        level = get_tier(fn)
        if level != SkillTier.READ_ONLY:
            request = ConfirmationRequest(
                skill_name=getattr(fn, "__name__", repr(fn)),
                tier=level,
                summary=summary,
                details=details or {},
            )
            approved = await self._confirm(request)
            if not approved:
                raise PermissionDenied(
                    f"{request.skill_name} ({level.value}) was declined: {summary}"
                )
        return fn(*args, **kwargs)
