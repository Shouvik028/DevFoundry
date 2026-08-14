"""@reviewer agent — PR/diff review for correctness, style, and bugs.

Config-as-code for now (system prompt + tool schema), not a separate
service: matches spec 3.2 ("each is a config ... not necessarily separate
code"). Takes a ModelProvider as a dependency rather than constructing one
itself, so it stays provider-agnostic and config-driven model selection
(spec 3.4) works without touching this module.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from devfoundry.providers.base import ModelProvider
from devfoundry.providers.types import Message, Role, ToolDefinition, tool_uses

SYSTEM_PROMPT = """\
You are @reviewer, a careful senior software engineer reviewing a code diff.

Review the diff for:
- Correctness: logic errors, edge cases, off-by-one mistakes, unhandled
  failure modes.
- Style: consistency with the surrounding code, naming, clarity.
- Potential bugs: anything that could break at runtime or under load.

Be specific and cite what in the diff prompted each finding. Don't invent
issues that aren't there — an empty findings list is a valid, good review.
Call submit_review exactly once with your complete review.\
"""

SUBMIT_REVIEW_TOOL = ToolDefinition(
    name="submit_review",
    description="Submit the completed code review as structured feedback.",
    input_schema={
        "type": "object",
        "properties": {
            "summary": {
                "type": "string",
                "description": "One or two sentence overall assessment of the diff.",
            },
            "findings": {
                "type": "array",
                "description": "Individual review comments. Empty if the diff has no issues.",
                "items": {
                    "type": "object",
                    "properties": {
                        "severity": {
                            "type": "string",
                            "enum": ["blocking", "suggestion", "nit"],
                        },
                        "comment": {"type": "string"},
                        "line_ref": {
                            "type": "string",
                            "description": "Free-text pointer to the relevant location, e.g. a filename or hunk.",
                        },
                    },
                    "required": ["severity", "comment"],
                },
            },
        },
        "required": ["summary", "findings"],
    },
)


class ReviewError(Exception):
    """Raised when the model's submit_review call doesn't match the
    expected shape."""


@dataclass
class ReviewFinding:
    severity: str
    comment: str
    line_ref: str | None = None


@dataclass
class ReviewResult:
    summary: str
    findings: list[ReviewFinding]


class ReviewerAgent:
    """@reviewer. Stateless — the provider and diff are passed per call, so
    one instance can be reused across tasks."""

    name = "reviewer"
    system_prompt = SYSTEM_PROMPT

    async def review(
        self,
        provider: ModelProvider,
        diff: str,
        *,
        task_description: str = "",
        model: str | None = None,
    ) -> ReviewResult:
        if not diff.strip():
            return ReviewResult(summary="No changes to review.", findings=[])

        prompt = f"{task_description}\n\n" if task_description else ""
        prompt += f"Review this diff:\n\n```diff\n{diff}\n```"

        result = await provider.tool_call(
            [Message(role=Role.USER, content=prompt)],
            tools=[SUBMIT_REVIEW_TOOL],
            tool_choice=SUBMIT_REVIEW_TOOL.name,
            system=self.system_prompt,
            model=model,
        )

        calls = tool_uses(result.message)
        # provider.tool_call() guarantees at least one; take the first if
        # the model called it more than once.
        return _parse_review(calls[0].input)


def _parse_review(data: dict[str, Any]) -> ReviewResult:
    try:
        summary = data["summary"]
        findings = [
            ReviewFinding(
                severity=f["severity"],
                comment=f["comment"],
                line_ref=f.get("line_ref"),
            )
            for f in data["findings"]
        ]
    except (KeyError, TypeError) as exc:
        raise ReviewError(f"submit_review call had an unexpected shape: {data!r}") from exc
    return ReviewResult(summary=summary, findings=findings)
