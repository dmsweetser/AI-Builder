"""Diagnostics subfolder — run any AI-Builder tool in its anticipated environment.

Useful for diagnosing why a tool may not be working as expected.
Run tools directly (without the agent) against a project's root_dir
to see the exact output, errors, and source code that would be
injected during agent execution.

Usage:
    python -m diagnostics.diagnose --tool read_file --params '{"path": "src/main.py"}' --root /path/to/project
    python -m diagnostics.diagnose --tool edit_file --params '{"path": "src/main.py", "original_text": "...", "new_text": "..."}' --root /path/to/project
    python -m diagnostics.diagnose --list  # list all available tools
"""
