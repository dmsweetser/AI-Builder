"""Security helpers for the agentic engine."""

import os


class SecurityError(Exception):
    """Security violation - path escapes project root."""
    pass


class ToolError(Exception):
    """Tool-specific error (bad params, operation failed)."""
    pass


class EngineError(Exception):
    """Engine-level fatal error."""
    pass


def ensure_under_root(filepath: str, root_dir: str) -> str:
    """Resolve and validate that a path stays within root_dir."""
    root_dir = _normalize_path(root_dir)
    if os.path.isabs(filepath):
        full = _normalize_path(filepath)
    else:
        full = _normalize_path(os.path.join(root_dir, filepath))
    if full == root_dir or full.startswith(root_dir + os.sep) or full.startswith(root_dir + '\\'):
        return full
    raise SecurityError(f"Path escapes project root: {filepath} -> {full}")


def validate_tool_params(params: dict, schema: dict) -> dict:
    """Validate that all required string params are present and are strings."""
    result = {}
    for key, expected_type in schema.items():
        if key not in params:
            raise ToolError(f"Missing required parameter: {key}")
        val = params[key]
        if expected_type == "string" and not isinstance(val, str):
            raise ToolError(f"Parameter '{key}' must be a string, got {type(val).__name__}")
        result[key] = val
    return result


def _normalize_path(path: str) -> str:
    """Normalize a path for comparison."""
    return os.path.normpath(path)
