# Diagnostics — Run AI-Builder Tools Directly

Diagnose why a tool may not be working by running it directly in its anticipated environment, without going through the agent.

## Purpose

When the agent reports that a tool failed or produced unexpected output, you can use this diagnostic runner to:

1. **Reproduce the issue** — run the exact same tool with the same parameters against the same project root
2. **See the full output** — including error messages, injected source code (for custom tools), and tracebacks
3. **Test edge cases** — try path traversal, malformed params, or unusual inputs to understand tool behavior
4. **Verify tool availability** — list all built-in and project-local tools for a given project

## Quick Start

```bash
# List all available tools for a project
python -m diagnostics.diagnose --list --root /path/to/project

# Run a built-in tool
python -m diagnostics.diagnose --tool read_file \
    --params '{"path": "src/main.py"}' \
    --root /path/to/project

# Run with verbose output
python -m diagnostics.diagnose --tool grep_code \
    --params '{"pattern": "ensure_under_root", "file_pattern": "*.py"}' \
    --root /path/to/project --verbose

# Output as JSON (for piping to other tools)
python -m diagnostics.diagnose --tool list_directory \
    --params '{"path": "src/"}' \
    --root /path/to/project --json
```

## Command-Line Options

| Option | Short | Description |
|--------|-------|-------------|
| `--tool` | `-t` | Tool name to execute (required, unless using `--list`) |
| `--params` | `-p` | JSON object of tool parameters (default: `{}`) |
| `--root` | `-r` | Project root directory (default: current dir) |
| `--output-dir` | `-o` | Project output directory (auto-detected if omitted) |
| `--list` | `-l` | List all available tools and exit |
| `--verbose` | `-v` | Show verbose output (tool definition, full result) |
| `--json` | | Output result as JSON (for piping to other tools) |

## How It Works

The diagnostic runner:

1. **Resolves the project root** — walks up the directory tree looking for `agent_engine/` if not found at the specified path
2. **Sets up the import path** — adds the project root to `sys.path` and creates shim modules for common LLM-generated import patterns (`tools.base` → `agent_engine.tools.base`)
3. **Loads the ToolRegistry** — the same registry the agent engine uses, including project-local tools from `aib_instance/<project>/tools/active/`
4. **Creates a tool instance** — with the correct `root_dir`, `output_dir`, and `job_id`
5. **Executes the tool** — through the full pipeline (parameter validation, security checks, execution)
6. **Captures the result** — including any injected source code that would be shown to the agent on failure

## Examples

### Diagnosing a failed edit_file

```bash
python -m diagnostics.diagnose --tool edit_file \
    --params '{
        "path": "src/main.py",
        "original_text": "def hello():\n    print(\"world\")",
        "new_text": "def hello():\n    print(\"hello world\")"
    }' \
    --root /path/to/project --verbose
```

### Testing a custom/project-local tool

```bash
python -m diagnostics.diagnose --tool my_custom_tool \
    --params '{"path": "src/data.json"}' \
    --root /path/to/project
```

### Testing security boundaries

```bash
# This will fail with SecurityError — good for verifying path validation
python -m diagnostics.diagnose --tool read_file \
    --params '{"path": "../../../etc/passwd"}' \
    --root /path/to/project
```

### Piping JSON output to jq

```bash
python -m diagnostics.diagnose --tool list_directory \
    --params '{"path": "src/"}' \
    --root /path/to/project --json | jq '.content'
```

## Project-Local Tools

The diagnostic runner also loads project-local tools from:
- `aib_instance/<project>/tools/active/` — approved tools
- `aib_instance/<project>/tools/pending/` — pending tools (listed but not executable)

Use `--list` to see what tools are available for a project.

## Notes

- The diagnostic runner uses the **exact same** `ToolRegistry`, `BaseTool`, and security layer as the agent engine
- Custom tools that fail will have their source code injected into the output (same as agent behavior)
- Path validation is enforced — tools cannot escape the project root
- The `--json` flag produces clean output suitable for programmatic consumption
