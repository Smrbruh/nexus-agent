"""
config.py — Centralized configuration loader for NEXUS Agent
Reads from .env and provides typed config values across all modules.
"""
import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    # Telegram
    TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_ADMIN_IDS: list[int] = [
        int(uid.strip())
        for uid in os.getenv("TELEGRAM_ADMIN_IDS", "").split(",")
        if uid.strip().isdigit()
    ]

    # Gemini
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")

    # GitHub
    GITHUB_TOKEN: str = os.getenv("GITHUB_TOKEN", "")

    # Flask
    FLASK_SECRET_KEY: str = os.getenv("FLASK_SECRET_KEY", "nexus-secret-change-me")
    FLASK_HOST: str = os.getenv("FLASK_HOST", "0.0.0.0")
    FLASK_PORT: int = int(os.getenv("FLASK_PORT", "5000"))
    FLASK_DEBUG: bool = os.getenv("FLASK_DEBUG", "false").lower() == "true"

    # Database
    DATABASE_PATH: str = os.getenv("DATABASE_PATH", "data/nexus.db")

    # Scraping
    SCRAPE_DELAY_SECONDS: float = float(os.getenv("SCRAPE_DELAY_SECONDS", "1.5"))
    MAX_SCRAPE_RETRIES: int = int(os.getenv("MAX_SCRAPE_RETRIES", "3"))

    # Logging
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    LOG_FILE: str = os.getenv("LOG_FILE", "logs/nexus.log")

    # Agent
    MAX_TOOL_ITERATIONS: int = int(os.getenv("MAX_TOOL_ITERATIONS", "5"))
    MAX_HISTORY_CONTEXT: int = int(os.getenv("MAX_HISTORY_CONTEXT", "20"))
    AGENT_SYSTEM_PROMPT: str = os.getenv(
        "AGENT_SYSTEM_PROMPT",
        (
            "You are NEXUS, an elite AI agent combining OSINT intelligence and "
            "software engineering expertise. You reason step by step, use tools "
            "strategically, and deliver precise, actionable results."
        ),
    )

    @classmethod
    def validate(cls) -> list[str]:
        """Return list of missing critical config keys."""
        missing = []
        if not cls.TELEGRAM_BOT_TOKEN:
            missing.append("TELEGRAM_BOT_TOKEN")
        if not cls.GEMINI_API_KEY:
            missing.append("GEMINI_API_KEY")
        return missing


config = Config()
