# AI-Builder

An agentic, multi-step code-revision engine with a web UI. You give it a project directory and natural-language instructions — it explores the codebase, reads files, makes edits, verifies syntax, and iterates until the task is done.

---

## Table of Contents

- [Features](#features)
- [Architecture](#architecture)
- [Tool Reference](#tool-reference)
- [Configuration](#configuration)
- [Quick Start](#quick-start)
- [API Reference](#api-reference)
- [Security Model](#security-model)
- [Testing](#testing)

---

## Features

- **Multi-step agentic loop** — The engine calls an LLM, parses tool calls, executes tools, feeds results back, and repeats until the task is complete or `max_steps` is reached.
- **11 built-in tools** — Filesystem exploration, reading, writing, editing, searching, syntax checking, symbol finding, JAR decompilation, dependency listing, and file info.
- **OpenAI-compatible LLM endpoint** — Works with Ollama, LM Studio, vLLM, Azure AI, or any OpenAI-compatible API.
- **Tag-based tool-call protocol** — No JSON escaping nightmares. Tool calls use a clean `[TOOL:...] ... [TOOL_END]` block format that handles any content including quotes, newlines, and indentation.
- **Bounded tool execution** — Every tool call is validated against a security layer that prevents path traversal outside the project root.
- **Loop detection** — The engine detects when the LLM gets stuck in a repetition loop and intervenes with a corrective message.
- **Live instruction injection** — While a job is running, drop a `live_instruction.txt` file into the output directory to give the agent mid-run updates.
- **Tool filtering** — Enable or disable specific tools via `AIB_ENABLED_TOOLS` for constrained execution environments.
- **Flask web UI** — Manage projects, start jobs, monitor progress, and view step-by-step logs through a browser.

---

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                    Flask Web UI                      │
│              (app.py + static/ + templates/)         │
└──────────────────┬──────────────────────────────────┘
                   │ HTTP / JSON
                   ▼
┌─────────────────────────────────────────────────────┐
│                   app.py (Flask)                     │
│  • Project CRUD, job queue, worker thread           │
│  • run_with_agent_engine()                          │
└──────────────────┬──────────────────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────────────────┐
│              agent_engine /                          │
│                                                     │
│  ┌─────────────┐  ┌──────────────┐  ┌────────────┐ │
│  │  EngineConfig│  │  LLMClient   │  │ ToolRegistry│ │
│  │  (env vars)  │  │ (streaming   │  │  (11 tools) │ │
│  │              │  │  OpenAI API) │  │            │ │
│  └─────────────┘  └──────────────┘  └─────┬──────┘ │
│                                            │        │
│  ┌─────────────────────────────────────────┼──────┐ │
│  │           AgentEngine (orchestrator)    │      │ │
│  │  • build_system_prompt()               │      │ │
│  │  • parse_tool_calls()                  │      │ │
│  │  • run() — main agentic loop           │      │ │
│  └─────────────────────────────────────────┼──────┘ │
│                                            │        │
│  ┌─────────────────────────────────────────┼──────┐ │
│  │         agent_engine/tools/             │      │ │
│  │  files.py   checkers.py  misc.py       │      │ │
│  │  search.py   base.py   __init__.py     │      │ │
│  └─────────────────────────────────────────┼──────┘ │
│                                            │        │
│  ┌─────────────────────────────────────────┼──────┐ │
│  │         agent_engine/security.py       │      │ │
│  │  • ensure_under_root()                 │      │ │
│  │  • validate_tool_params()              │      │ │
│  └─────────────────────────────────────────┘      │ │
└─────────────────────────────────────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────────────────┐
│              Project Root (bounded)                  │
│  src/  tests/  requirements.txt  README.md          │
└─────────────────────────────────────────────────────┘
```

### Key components

| Component | Role |
|---|---|
| `AgentEngine` | Orchestrates the agentic loop: LLM → parse → execute → feedback → repeat |
| `LLMClient` | Streams responses from an OpenAI-compatible endpoint |
| `ToolRegistry` | Registers and dispatches tool calls with parameter validation |
| `EngineConfig` | Reads all runtime configuration from environment variables |
| `Security` layer | Validates every file path stays within the project root |

---

## Tool Reference

| Tool | Description |
|---|---|
| `list_directory` | List files/directories with configurable depth |
| `search_files` | Glob-style file name search (`*.py`, `**/*.java`) |
| `grep_code` | Search file contents for text patterns |
| `read_file` | Read file contents with optional line range |
| `write_file` | Write or overwrite a file (creates parent dirs) |
| `edit_file` | Targeted text replacement in an existing file |
| `delete_file` | Delete a file (blocks `.bak` / `.backup`) |
| `check_syntax` | Syntax check for Python, Java, C#, JS/TS, HTML, CSS, XML, JSON |
| `find_symbol` | Find references to a code symbol across the codebase |
| `decompile_jar` | Decompile a JAR file (requires `jd-cli` or `javap`) |
| `list_dependencies` | Parse dependency manifests (requirements.txt, pom.xml, package.json, .csproj, etc.) |
| `get_file_info` | Get file metadata: size, language, line count, binary/text |
| `execute_python` | Execute Python code (requires explicit approval) |

### Tool-call format

```
[TOOL:tool_name]
param1:value1
param2:
multi-line value here
[TOOL_END]
```

- `param1:value1` — single-line value
- `param2:` followed by lines — multi-line value (continues until the next `identifier:` line or `[TOOL_END]`)
- No escaping needed — quotes, newlines, indentation all work naturally

---

## Configuration

All configuration is via environment variables:

| Variable | Default | Description |
|---|---|---|
| `AIB_ROOT` / `ROOT_DIRECTORY` | `os.getcwd()` | Project root directory |
| `CUSTOM_ENDPOINT_URL` | — | OpenAI-compatible API endpoint |
| `CUSTOM_MODEL_NAME` | — | Model name to use |
| `CUSTOM_API_KEY` | — | API key (optional) |
| `CUSTOM_VERIFY_SSL` | `false` | Verify SSL certificates |
| `CUSTOM_TIMEOUT` | `300` | LLM call timeout in seconds |
| `AIB_MAX_STEPS` | `50` | Maximum agentic steps per job |
| `AIB_ENABLED_TOOLS` | `null` | JSON array of tool names to enable (null = all) |
| `JD_CLI_PATH` | — | Path to `jd-cli` for JAR decompilation |
| `JAVA_HOME` | — | Java home directory |
| `DOTNET_CLI_PATH` | — | Path to `dotnet` CLI |

---

## Quick Start

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Set environment variables

```bash
export CUSTOM_ENDPOINT_URL=http://localhost:11434/v1
export CUSTOM_MODEL_NAME=llama3.1
export CUSTOM_API_KEY=""
export AIB_MAX_STEPS=20
```

### 3. Run the app

```bash
python app.py
```

Open `http://localhost:5000` in your browser.

### 4. Create a project and run a job

1. Click **New Project** and enter a name and root directory path.
2. Click **Run** to start the agentic engine.
3. Watch the step-by-step log as the agent explores, edits, and verifies your code.

### 5. Run tests

```bash
python -m unittest tests.test_ai_builder_expanded -v
```

---

## API Reference

### Start a job

```
POST /api/jobs
{
  "project_id": "uuid",
  "instructions": "Add a hello function to main.py"
}
```

### Get job status

```
GET /api/jobs/<job_id>
```

### Get job history

```
GET /api/jobs/history
```

### Inject live instructions

Write to: `<output_dir>/<job_id>/live_instruction.txt`

The engine reads and clears this file each step, allowing mid-run updates.

---

## Security Model

- **Path bounding** — Every tool call passes through `ensure_under_root()` which resolves the path and verifies it stays within the project root. Path traversal via `../` is rejected.
- **Allowed absolute paths** — Absolute paths in `/tmp/` and `/var/tmp/` are permitted for task instructions that need system-wide files.
- **Parameter validation** — All tool parameters are validated against their schema before execution.
- **Backup file protection** — `delete_file` refuses to delete `.bak` or `.backup` files.
- **Tool filtering** — `AIB_ENABLED_TOOLS` lets you restrict which tools the agent can use.

---

## Testing

```bash
# Run all tests
python -m unittest tests.test_ai_builder_expanded -v

# Run parser tests only
python -m unittest tests.test_ai_builder_expanded.TestParseToolCalls -v

# Run E2E tests only
python -m unittest tests.test_ai_builder_expanded.TestAgentEngineE2E -v
```

The test suite covers:
- **Parser unit tests** — Tag-based format parsing, multi-line values, multiple tools, edge cases
- **E2E tests** — Full agentic loop with mocked LLM, loop detection, tool execution

---

## License

See [LICENSE](LICENSE) for details.
