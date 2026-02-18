from __future__ import annotations

import re
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Auth
    bearer_token: str

    # Sandbox — stored as raw strings, parsed in model_post_init
    allowed_dirs_raw: str = str(Path.home() / "projects")
    blocked_commands_raw: str = ""

    # Parsed versions (set in model_post_init)
    allowed_dirs: list[Path] = []
    blocked_commands: list[re.Pattern[str]] = []

    # Rate limits
    max_requests_per_minute: int = 10
    max_concurrent_claude: int = 3

    # Claude CLI
    claude_cli_path: str = "claude"
    claude_default_max_turns: int = 5
    claude_max_timeout: int = 600

    # Server
    host: str = "127.0.0.1"
    port: int = 8787
    log_level: str = "INFO"
    public_url: str = ""  # e.g. https://nativedev.tail7d3518.ts.net:10000

    # Audit
    log_dir: Path = Path.home() / ".local/share/mcp-bridge"
    max_log_size_mb: int = 50

    def model_post_init(self, __context: object) -> None:
        if self.allowed_dirs_raw and not self.allowed_dirs:
            self.allowed_dirs = [
                Path(p.strip()).expanduser().resolve()
                for p in self.allowed_dirs_raw.split(",")
            ]
        if self.blocked_commands_raw and not self.blocked_commands:
            self.blocked_commands = [
                re.compile(p.strip())
                for p in self.blocked_commands_raw.split("|")
                if p.strip()
            ]


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()  # type: ignore[call-arg]
    return _settings
