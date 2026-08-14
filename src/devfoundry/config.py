"""Environment configuration.

Loads `.env` (if present) once at import time via python-dotenv, then
exposes typed getters for settings providers/skills need. Real secrets
live only in the environment or `.env` — see `.env.example` for the full
list — never hardcoded, never logged.
"""

from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()


class ConfigError(Exception):
    """Raised when a required setting is missing or empty."""


def get_anthropic_api_key() -> str:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise ConfigError(
            "ANTHROPIC_API_KEY is not set. Copy .env.example to .env and fill it in."
        )
    return key
