"""Shared settings: API key, model, database path."""

import os
from pathlib import Path

from dotenv import find_dotenv, load_dotenv

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "erp.db"
DICT_PATH = ROOT / "data" / "data_dictionary.json"

# Read .env from this project, or the nearest parent folder that has one.
load_dotenv(ROOT / ".env", override=True) or load_dotenv(find_dotenv(usecwd=True), override=True)
# Same convention as the MCP book: the key is stored as LLM_API_KEY.
os.environ["ANTHROPIC_API_KEY"] = os.environ.get("LLM_API_KEY") or os.environ.get("ANTHROPIC_API_KEY", "")

DEFAULT_MODEL = os.environ.get("ERP_MODEL", "claude-sonnet-5-5")


def get_llm(model: str | None = None):
    from langchain_anthropic import ChatAnthropic

    if not os.environ["ANTHROPIC_API_KEY"]:
        raise RuntimeError("Add LLM_API_KEY=sk-ant-... to a .env file (see .env.example).")
    # No temperature setting: newer Claude models only accept the default.
    return ChatAnthropic(model=model or DEFAULT_MODEL, max_tokens=4096)


def readonly_uri() -> str:
    """SQLAlchemy URI that opens the database read-only: the agent can never change data."""
    return f"sqlite:///file:{DB_PATH}?mode=ro&uri=true"
