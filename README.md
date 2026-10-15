# AI Builder

AI Builder is an agentic code revision engine that automates software development tasks through multi-step planning, tool execution, and autonomous code modification. It supports a modern agentic mode that iteratively explores, modifies, and verifies codebases.

## Features

- **Agentic Multi-Step Engine**: Autonomous code exploration, modification, and verification loop.
- **Tool Registry**: 12 built-in tools for file system operations, syntax checking, symbol search, dependency analysis, and JAR decompilation.
- **OpenAI-Compatible Endpoints**: Connect to Ollama, LM Studio, vLLM, OpenAI, or any compatible REST API.
- **Web UI**: Interactive dashboard for project management, job queuing, live agent monitoring, and chat.
- **Safety First**: Path traversal protection, syntax validation, backup creation, and dry-run support.
- **Cross-Platform**: Windows, macOS, and Linux support with packaged executables.

## Installation

### Prerequisites
- Python 3.8+
- Virtual environment (recommended)

### Setup
```bash
# Clone the repository
git clone https://github.com/your-repo/ai-builder.git
cd ai-builder

# Create and activate virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Run installation script (optional, creates directories and configures environment)
./scripts/install.sh  # On Windows: scripts\install.bat
```

## Configuration

### Environment Variables
Configure the model endpoint and engine behavior via environment variables or the Web UI Settings panel.

| Variable | Description | Default |
|----------|-------------|---------|
| `CUSTOM_ENDPOINT_URL` | OpenAI-compatible API endpoint URL | Required |
| `CUSTOM_API_KEY` | API key for authentication (optional for local models) | Empty |
| `CUSTOM_MODEL_NAME` | Model identifier (e.g., `llama3`, `gpt-4`) | Required |
| `CUSTOM_API_VERSION` | API version | `v1` |
| `CUSTOM_VERIFY_SSL` | Verify SSL certificates | `false` |
| `CUSTOM_MAX_TOKENS` | Maximum output tokens | `8192` |
| `AIB_MAX_STEPS` | Maximum agent steps per run | `50` |
| `OUTPUT_TOKENS` | Output tokens for legacy mode | `8192` |
| `MODEL_CONTEXT` | Context window size | `128000` |
| `TOP_K` | Sampling top-k parameter | `50` |
| `MIN_P` | Sampling min-p parameter | `0.0` |
| `AIB_ENGINE_MODE` | Default engine mode (`agent` or `legacy`) | `agent` |
| `ROOT_DIRECTORY` | Default project root directory | CWD |
| `AIB_PRE_SCRIPT` / `AIB_POST_SCRIPT` | Pre/post execution scripts | Empty |
| `AIB_ENABLED_TOOLS` | JSON array of enabled tool names | All tools |

### Settings Persistence
Settings are stored in `aib_instance/settings.json` and applied to environment variables on each run. Changes take effect immediately after saving in the UI or reloading settings.

## Usage

### Web UI
```bash
python app.py
```
Open `http://localhost:5056` in your browser.

1. **Projects**: Create projects with root directories, instructions, and file patterns.
2. **Jobs**: Queue runs, monitor progress, and view history.
3. **Chat**: Interactive AI assistant for code queries.
4. **Settings**: Configure model endpoint and engine parameters.

### Command Line
```bash
python app.py
```
API endpoints are available at `/api/...`. Use `curl` or Postman to interact with the backend.

### Agentic Mode
1. Create a project with mode set to `agentic`.
2. Provide instructions and root directory.
3. Run the project. The agent will:
   - Explore the codebase using available tools.
   - Plan and execute modifications.
   - Verify syntax and fix errors.
   - Return a summary of changes.

## Architecture

### Core Components
- **`agent_engine/`**: Agentic multi-step engine, tool registry, security helpers, and configuration.
- **`app.py`**: Flask web server, API routes, job queue, and settings management.
- **`static/`**: Frontend JavaScript and CSS.
- **`templates/`**: HTML templates for the web UI.

### Tool Registry
Available tools in agentic mode:
- `list_directory`, `search_files`, `grep_code`
- `read_file`, `write_file`, `edit_file`, `delete_file`
- `find_symbol`, `decompile_jar`
- `list_dependencies`, `check_syntax`, `get_file_info`

### Safety Mechanisms
- **Path Validation**: All file operations are validated against the project root. Absolute paths are restricted to `/tmp/` and `/var/tmp/`.
- **Syntax Checking**: Automatic validation after modifications.
- **Backup Creation**: Original files are backed up before editing.
- **Dry Run**: Test modifications without applying changes.
- **Loop Detection**: Agent interventions prevent infinite tool call loops.

## Testing

Run the test suite:
```bash
python -m unittest discover -s tests -p "test_*.py"
```

Tests cover:
- File parsing and modification
- Tool execution and security
- Engine configuration and prompt generation
- Agentic integration workflows

## Packaging

### Windows
```bash
scripts\package.bat
```
Produces `dist\ai_builder.exe`.

### Linux/macOS
```bash
chmod +x scripts/package.sh
./scripts/package.sh
```
Produces `dist/ai_builder.bin`.

## License

MIT License. See LICENSE for details.

## Contributing

1. Fork the repository.
2. Create a feature branch.
3. Commit changes with clear descriptions.
4. Push and open a pull request.
5. Ensure tests pass and documentation is updated.