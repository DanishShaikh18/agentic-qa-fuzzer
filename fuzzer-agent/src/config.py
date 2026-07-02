"""
Central configuration manager for the Agentic QA Fuzzer.

This module loads environment variables from `.env` files using `python-dotenv`
and initializes a validated application configuration object (`AppConfig`).
Ensures critical runtime credentials (such as `GEMINI_API_KEY`) are present
and valid before executing the autonomous attacker agent or MCP server.
"""

import os
from dotenv import load_dotenv

# Load variables from `.env` file into os.environ (if present)
load_dotenv()


class AppConfig:
    """
    Application configuration store loading settings from environment variables.
    """

    def __init__(self) -> None:
        self.GEMINI_API_KEY: str = self._get_required_env("GEMINI_API_KEY")
        self.TARGET_API_URL: str = os.getenv("TARGET_API_URL", "http://localhost:8000")
        self.MAX_RECURSION_LIMIT: int = int(os.getenv("MAX_RECURSION_LIMIT", "15"))

    @staticmethod
    def _get_required_env(key: str) -> str:
        """
        Retrieves a required environment variable, raising a ValueError if missing or empty.
        """
        val = os.getenv(key)
        if val is None or not val.strip():
            raise ValueError(
                f"Configuration Error: Required environment variable '{key}' is missing or empty. "
                "Please verify that it is set in your environment or .env file."
            )
        return val.strip()


# Global configuration instance
settings = AppConfig()
