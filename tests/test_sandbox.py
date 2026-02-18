import re
from pathlib import Path

import pytest

from mcp_bridge.sandbox import validate_command, validate_path


class TestValidatePath:
    def test_valid_path(self):
        allowed = [Path("/home/tommaso/projects")]
        p = validate_path("/home/tommaso/projects/myapp/src", allowed)
        assert p == Path("/home/tommaso/projects/myapp/src")

    def test_path_under_allowed(self):
        allowed = [Path("/home/tommaso/projects")]
        p = validate_path("/home/tommaso/projects", allowed)
        assert p == Path("/home/tommaso/projects")

    def test_invalid_path_outside_allowed(self):
        allowed = [Path("/home/tommaso/projects")]
        with pytest.raises(ValueError, match="not under any allowed"):
            validate_path("/etc/passwd", allowed)

    def test_tilde_expansion(self):
        allowed = [Path.home() / "projects"]
        p = validate_path("~/projects/foo", allowed)
        assert str(p).startswith(str(Path.home()))

    def test_multiple_allowed_dirs(self):
        allowed = [Path("/home/tommaso/projects"), Path("/tmp/safe")]
        p = validate_path("/tmp/safe/file.txt", allowed)
        assert p == Path("/tmp/safe/file.txt")

    def test_parent_traversal_blocked(self):
        allowed = [Path("/home/tommaso/projects")]
        with pytest.raises(ValueError):
            validate_path("/home/tommaso/projects/../../etc/passwd", allowed)


class TestValidateCommand:
    def test_allowed_command(self):
        patterns = [re.compile(r"rm\s+-rf\s+/")]
        validate_command("ls -la", patterns)  # Should not raise

    def test_blocked_rm_rf(self):
        patterns = [re.compile(r"rm\s+-rf\s+/")]
        with pytest.raises(ValueError, match="blocked"):
            validate_command("rm -rf /", patterns)

    def test_blocked_shutdown(self):
        patterns = [re.compile(r"shutdown")]
        with pytest.raises(ValueError, match="blocked"):
            validate_command("sudo shutdown -h now", patterns)

    def test_empty_blocklist(self):
        validate_command("anything", [])  # Should not raise
