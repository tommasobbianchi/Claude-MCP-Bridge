from __future__ import annotations

import re
from pathlib import Path


def validate_path(path_str: str, allowed_dirs: list[Path]) -> Path:
    """Resolve and validate a path against the whitelist.

    Expands ~, resolves symlinks, then checks that the resolved
    path is under at least one allowed directory.

    Raises ValueError if not allowed.
    """
    resolved = Path(path_str).expanduser().resolve()
    for allowed in allowed_dirs:
        try:
            resolved.relative_to(allowed)
            return resolved
        except ValueError:
            continue
    raise ValueError(
        f"Path '{resolved}' is not under any allowed directory: "
        f"{[str(d) for d in allowed_dirs]}"
    )


def validate_command(command: str, blocked_patterns: list[re.Pattern[str]]) -> None:
    """Check command against blocklist regex patterns.

    Raises ValueError if the command matches any blocked pattern.
    """
    for pattern in blocked_patterns:
        if pattern.search(command):
            raise ValueError(
                f"Command blocked by security policy (matched: {pattern.pattern})"
            )
