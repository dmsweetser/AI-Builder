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


# Well-known directories where absolute paths are allowed (for task instructions)
ALLOWED_ABSOLUTE_PREFIXES = [
    "/tmp/", "/tmp",
    "/var/tmp/", "/var/tmp",
]


def ensure_under_root(filepath: str, root_dir: str) -> str:
    """Resolve and validate that a path stays within root_dir,
    unless it's an absolute path in a well-known writable directory."""
    root_dir = _normalize_path(root_dir)
    if os.path.isabs(filepath):
        full = _normalize_path(filepath)
        # Allow absolute paths that equal the root_dir itself
        if full == root_dir:
            return full
        # Allow absolute paths in well-known writable directories
        for prefix in ALLOWED_ABSOLUTE_PREFIXES:
            if full == prefix or full.startswith(prefix):
                return full
        raise SecurityError(f"Absolute path escapes project root and is not in a permitted directory: {filepath} -> {full}")
    else:
        full = _normalize_path(os.path.join(root_dir, filepath))
    if full == root_dir or full.startswith(root_dir + os.sep) or full.startswith(root_dir + '\\'):
        return full
    raise SecurityError(f"Path escapes project root: {filepath} -> {full}")


def validate_tool_params(params: dict, schema: dict) -> dict:
    """Validate that all required string params are present and are strings.

    Parameters with a 'string?' type are optional — they will be included
    in the result only if the caller provided them.
    """
    result = {}
    for key, expected_type in schema.items():
        optional = expected_type.endswith("?")
        if optional:
            expected_type = expected_type[:-1]
        if key not in params:
            if optional:
                continue
            raise ToolError(f"Missing required parameter: {key}")
        val = params[key]
        if expected_type == "string" and not isinstance(val, str):
            raise ToolError(f"Parameter '{key}' must be a string, got {type(val).__name__}")
        result[key] = val
    return result


def _normalize_path(path: str) -> str:
    """Normalize a path for comparison."""
    return os.path.normpath(path)
