"""Security helpers for the agentic engine."""

import os
import re


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

    # Normalize the input path first to detect cross-platform formats
    normalized = _normalize_path(filepath)

    # If normalization produced a Windows-style absolute path (e.g. C:/...),
    # treat it as relative to root_dir (the LLM may output paths in WSL/Cygwin
    # format like /c/local which becomes C:/local).
    if re.match(r'^[A-Z]:/', normalized, re.IGNORECASE):
        # Treat as relative path — join with root_dir
        # Strip the drive letter to get a relative path
        rel_path = normalized[2:]  # Remove "C:"
        if rel_path.startswith('/'):
            rel_path = rel_path[1:]  # Remove leading /
        full = _normalize_path(os.path.join(root_dir, rel_path))
        if full == root_dir or full.startswith(root_dir + '/'):
            return full
        raise SecurityError(f"Path escapes project root: {filepath} -> {full}")

    if os.path.isabs(filepath):
        full = normalized
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
    # After normalization, root_dir uses forward slashes — check with / separator
    if full == root_dir or full.startswith(root_dir + '/'):
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
    """Normalize a path for comparison.

    Handles cross-platform path formats:
    - Converts backslashes to forward slashes
    - Strips leading slashes for relative-style paths like /c/local (WSL/Cygwin style)
    - Normalizes drive letters (c: -> C:)
    - Uses os.path.normpath for canonical form
    - Ensures consistent forward-slash separators for comparison
    """
    if not path:
        return path

    # Work with a copy
    p = path.strip()

    # Convert Windows backslashes to forward slashes
    p = p.replace('\\', '/')

    # Handle WSL/Cygwin-style paths: /c/local -> C:/local or /c:/local -> C:/local
    # Pattern: single letter followed by optional colon, then / at the start
    # Must NOT match /home, /etc, /usr etc. — only single-letter drive letters
    # We check that what follows the letter+colon (if any) is / or end-of-string
    m = re.match(r'^/([a-zA-Z]):?(/.*)$', p)
    if m:
        p = m.group(1).upper() + ':' + m.group(2)

    # Handle bare Windows paths with backslashes that slipped through
    # e.g. C:\local -> C:/local (already handled above, but be safe)
    m = re.match(r'^([a-zA-Z]):/(.*)$', p)
    if m:
        p = m.group(1).upper() + ':/' + m.group(2)

    # Normalize using os.path (handles .., ., double slashes, etc.)
    p = os.path.normpath(p)

    # Final normalization: ensure forward slashes for consistent comparison
    p = p.replace('\\', '/')

    return p
