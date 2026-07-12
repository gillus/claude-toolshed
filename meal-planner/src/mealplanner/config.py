"""Settings loaded from environment variables.

All configuration is passed through the MCP client config's `env` block:
  MEALPLANNER_DB        path to the SQLite database
  CALLMEBOT_PHONE       WhatsApp phone number in international format (+39...)
  CALLMEBOT_APIKEY      API key received from the CallMeBot bot
  MEALPLANNER_MAX_FETCH max recipe pages fetched per search (default 8)
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_DB = Path.home() / ".local" / "share" / "mealplanner" / "mealplanner.db"


@dataclass(frozen=True)
class Settings:
    db_path: Path
    callmebot_phone: str | None
    callmebot_apikey: str | None
    max_fetch: int


def load() -> Settings:
    db_path = Path(os.environ.get("MEALPLANNER_DB", DEFAULT_DB)).expanduser()
    return Settings(
        db_path=db_path,
        callmebot_phone=os.environ.get("CALLMEBOT_PHONE") or None,
        callmebot_apikey=os.environ.get("CALLMEBOT_APIKEY") or None,
        max_fetch=int(os.environ.get("MEALPLANNER_MAX_FETCH", "8")),
    )
