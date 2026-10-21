"""Agent Engine - the main orchestrator."""

import os
import re
import json
import logging
import time
import uuid
import subprocess
import platform
from typing import Any, Dict, List, Tuple, Optional
from agent_engine.config import EngineConfig
from agent_engine.security import SecurityError, ToolError, EngineError
from agent_engine.tools import ToolRegistry
from agent_engine.tools.base import ToolResult


import random as _random
import time as _time
import urllib.error as _urllib_error


def _estimate_tokens(text: str) -> int:
    """Rough token estimate: ~4 chars per token for English/code."""
    return max(1, len(text) // 4)


def _trim_messages_to_context(messages: List[Dict[str, str]], system_prompt: str,
                               max_tokens: int) -> List[Dict[str, str]]:
    """Trim conversation history so total tokens stay within max_tokens.

    Keeps system prompt + last N messages.  max_tokens==0 means unlimited.
    Only trims when the total actually exceeds the budget.
    """
    if max_tokens <= 0:
        return messages

    system_tokens = _estimate_tokens(system_prompt)

    # Start with all messages, trim from the beginning (oldest) until we fit
    trimmed = list(messages)
    while len(trimmed) > 1:  # keep at least the system prompt
        total = system_tokens + sum(_estimate_tokens(m.get("content", "")) for m in trimmed[1:])
        if total <= max_tokens:
            break
        # Remove the oldest non-system message (index 1)
        trimmed.pop(1)

    return trimmed


class LLMClient:
    """Interface for calling the LLM (OpenAI-compatible endpoint)."""

    MAX_RETRIES = 3
    BASE_DELAY = 2.0  # seconds

    def __init__(self, max_context_tokens: int = 0, max_output_tokens: int = 0):
        self._prompt_file_counter = 0
        self._max_context_tokens = max_context_tokens
        self._max_output_tokens = max_output_tokens

    def call(self, messages: List[Dict[str, str]], response_file: Optional[str] = None,
             system_prompt: str = "") -> str:
        """Call the LLM with retry logic and context trimming."""
        last_err = None
        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                return self._call_custom_endpoint(messages, response_file, system_prompt)
            except Exception as e:
                last_err = e
                if attempt < self.MAX_RETRIES:
                    delay = self.BASE_DELAY * (2 ** (attempt - 1))
                    jitter = delay * (0.5 + 0.5 * _random.random())
                    _time.sleep(jitter)
        raise EngineError(f"LLM call failed after {self.MAX_RETRIES} attempts: {last_err}")

    def _call_custom_endpoint(self, messages: List[Dict[str, str]],
                              response_file: Optional[str], system_prompt: str) -> str:
        """Call a custom OpenAI-compatible endpoint (Ollama, LM Studio, vLLM, etc.)."""
        import urllib.request
        import ssl

        endpoint_url = EngineConfig.get_custom_endpoint_url()
        api_key = EngineConfig.get_custom_api_key()
        model_name = EngineConfig.get_custom_model_name()
        timeout = EngineConfig.get_timeout()

        if not all([endpoint_url, model_name]):
            raise EngineError("Missing custom endpoint credentials: CUSTOM_ENDPOINT_URL and CUSTOM_MODEL_NAME required")

        # Trim messages to context budget
        if self._max_context_tokens > 0 and system_prompt:
            messages = _trim_messages_to_context(messages, system_prompt, self._max_context_tokens)

        # Build OpenAI-format messages
        openai_messages = []
        for msg in messages:
            openai_messages.append({
                "role": msg["role"],
                "content": msg["content"],
            })

        payload: Dict[str, Any] = {
            "model": model_name,
            "messages": openai_messages,
            "stream": True,
        }
        if self._max_output_tokens > 0:
            payload["max_tokens"] = self._max_output_tokens

        # Build headers
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        # Handle SSL verification
        verify_ssl = EngineConfig.get_custom_verify_ssl()
        if verify_ssl:
            context = ssl.create_default_context()
        else:
            context = ssl._create_unverified_context()

        data = json.dumps(payload).encode('utf-8')
        req = urllib.request.Request(
            endpoint_url,
            data=data,
            headers=headers,
            method='POST',
        )

        content = ""
        try:
            with urllib.request.urlopen(req, context=context, timeout=timeout) as response:
                for line in response:
                    line = line.decode('utf-8').strip()
                    if not line.startswith('data: '):
                        continue
                    data_str = line[6:]
                    if data_str == '[DONE]':
                        break
                    try:
                        chunk = json.loads(data_str)
                        delta = chunk.get('choices', [{}])[0].get('delta', {})
                        c = delta.get('content', '')
                        if c:
                            content += c
                            if response_file and len(content) % 100 == 0:
                                with open(response_file, 'w', encoding='utf-8') as rf:
                                    rf.write(content)
                    except json.JSONDecodeError:
                        continue
        except _urllib_error.HTTPError as e:
            body = e.read().decode('utf-8', errors='replace') if hasattr(e, 'read') else ''
            raise EngineError(f"Custom endpoint HTTP {e.code}: {body}")
        except Exception as e:
            raise EngineError(f"Custom endpoint call failed: {e}")

        return content



def build_system_prompt(tools: List[Dict[str, Any]]) -> str:
    """Build the system prompt that defines the agentic workflow."""
    tool_defs = ""
    for t in tools:
        tool_defs += f"\n  - {t['name']}: {t['description']}"
        if t.get('parameters'):
            tool_defs += "\n    Required parameters:"
            for pk, pv in t['parameters'].items():
                tool_defs += f"\n      - {pk}: {pv}"

    example_block = (
        "[TOOL_START]\n"
        "[TOOL_NAME_START]\n"
        "write_file\n"
        "[TOOL_NAME_END]\n"
        "[PARAM_NAME_START]\n"
        "path\n"
        "[PARAM_NAME_END]\n"
        "[PARAM_VALUE_START]\n"
        "src/hello.py\n"
        "[PARAM_VALUE_END]\n"
        "[PARAM_NAME_START]\n"
        "content\n"
        "[PARAM_NAME_END]\n"
        "[PARAM_VALUE_START]\n"
        "\"\"\"Hello module.\"\"\"\n"
        "from src.main import greet\n"
        "\n"
        'if __name__ == "__main__":\n'
        '    print(greet("World"))\n'
        "[PARAM_VALUE_END]\n"
        "[TOOL_END]"
    )

    return f'''You are an expert code engineer working inside a bounded tool environment.
You NEVER execute code directly. You ONLY use the tools below to explore, read, modify, and verify code.

AVAILABLE TOOLS:{tool_defs}

WORKFLOW:
1. EXPLORE: Use list_directory, search_files, and grep_code to understand the project structure.
2. UNDERSTAND: Use read_file, find_symbol, and get_file_info to inspect relevant code.
3. PLAN: Decide what changes are needed. For large codebases, focus on specific files.
4. MODIFY: Use write_file (new files), edit_file (targeted changes), or delete_file.
5. VERIFY: Use check_syntax to validate your changes before moving on.
6. ITERATE: If syntax errors or issues are found, fix them. Repeat until done.

CRITICAL: You MUST take at least one tool call before using [DONE]. You cannot complete the task without using tools.

RULES:
- ALWAYS use read_file before edit_file to get the exact text to replace.
- ALWAYS include ALL required parameters for every tool call. Missing parameters will cause errors.
- ALWAYS use check_syntax after editing to verify correctness.
- Keep edits focused and small - one change at a time.
- For Java projects with JAR dependencies, use decompile_jar to inspect them.
- For large codebases, be selective: grep for relevant code, don't read everything.
- You have a maximum of {EngineConfig.get_max_steps()} steps total. Use them wisely.
- After making changes, verify them. If check_syntax fails, fix the errors.
- When done, respond with: [DONE] followed by a summary of all changes made.
- To create a new tool, use create_tool. It proposes the tool for user approval - it does NOT execute arbitrary code. Wait for user approval in the live feed before expecting the tool to be available.

TRUNCATION HANDLING:
- Tool results may be truncated if they exceed the configured max length (default 2000 chars).
- If a result says [TRUNCATED], the output was cut off. You should retry with more specific parameters:
  * list_directory: add a 'path' to target a subdirectory, or 'pattern' to filter by name
  * search_files: use a more specific 'pattern' to narrow results
  * grep_code: use a more specific 'pattern' to narrow results
- When you see [TRUNCATED], do NOT assume the result is complete. Narrow your query and try again.

PARAMETER FORMAT (tag-based, no escaping needed):
- Start a tool call with [TOOL_START] on its own line.
- On the NEXT line, specify [TOOL_NAME_START], then the tool name on the following line, then [TOOL_NAME_END].
  - The format is very specific: [TOOL_NAME_START] and [TOOL_NAME_END] wrap the tool name.
- Each parameter uses a NAME/VALUE pair of tags:
  - [PARAM_NAME_START] on its own line, then the parameter KEY on the next line, then [PARAM_NAME_END].
  - [PARAM_VALUE_START] on its own line, then the parameter VALUE on subsequent lines, then [PARAM_VALUE_END].
  - Values may span multiple lines between the START and END tags.
  - Repeat the NAME/VALUE pair for each additional parameter.
- End a tool call with [TOOL_END] on its own line.
- You MUST include both [TOOL_START] and [TOOL_END]. A tool call without both tags will NOT be executed.
- You may call multiple tools in one response by listing them sequentially.

Example:
{example_block}

RESPONSE FORMAT:
After each tool result, you will respond with either:
1. A tool call block (see PARAMETER FORMAT above)
2. Or a final response: [DONE] Your summary of changes.

You may interleave thinking/reasoning text between tool calls.
Each [TOOL_START]...[TOOL_END] block will be executed and the result will be fed back to you.

IMPORTANT: You are bounded to the project root directory by default. All file paths are relative to it.
You CANNOT read or write files outside the project root unless the task instructions explicitly specify an absolute path (e.g., /tmp/something.py).
When the instructions specify an absolute path, use it directly.

TOOL APPROVAL:
When you use the create_tool to propose a new tool, you MUST wait for user approval before using it.
After calling create_tool, do NOT call the new tool in the same response. Wait for the user to approve it in the UI.
If the tool is approved, it will appear in the tool selector. You can then use it in subsequent steps.
If the tool is rejected, do not use it. Choose a different approach or use existing tools.
You will see a "PENDING TOOL APPROVAL" message in the live feed while waiting for user review.
'''

def build_user_prompt(instructions: str, context: str = "") -> str:
    """Build the initial user prompt with the task instructions."""
    prompt = f"TASK INSTRUCTIONS:\n{instructions}\n\n"
    if context:
        prompt += f"RELEVANT CONTEXT:\n{context}\n\n"
    prompt += "STEP 1: Use list_directory to explore the project structure. Do NOT use [DONE] yet - you must take action first."
    return prompt


def parse_tool_calls(response: str) -> List[Tuple[str, Dict[str, str]]]:
    """Parse tool calls from LLM response using the tag-based format.

    Format:
        [TOOL_START]
        [TOOL_NAME_START]
        write_file
        [TOOL_NAME_END]
        [PARAM_NAME_START]
        path
        [PARAM_NAME_END]
        [PARAM_VALUE_START]
        src/hello.py
        [PARAM_VALUE_END]
        [TOOL_END]
    """
    calls = []

    # Match [TOOL_START]...[TOOL_END] blocks containing [TOOL_NAME_START]
    tool_pattern = r'\[TOOL_START\]\s*\[TOOL_NAME_START\]\s*\n(.*?)\[TOOL_NAME_END\]\s*(.*?)\[TOOL_END\]'
    tool_matches = list(re.finditer(tool_pattern, response, re.DOTALL))

    for match in tool_matches:
        tool_name = match.group(1).strip()
        params_block = match.group(2)
        params = _parse_new_format_params(params_block)
        if tool_name and params is not None:
            calls.append((tool_name, params))

    return calls


def _parse_new_format_params(params_block: str) -> Optional[Dict[str, str]]:
    """Parse parameters from the new tag-based format.

    Format:
        [PARAM_NAME_START]
        key
        [PARAM_NAME_END]
        [PARAM_VALUE_START]
        value
        [PARAM_VALUE_END]

    NAME/VALUE pairs alternate: each parameter is a NAME tag followed by a VALUE tag.
    """
    params: Dict[str, str] = {}
    current_key: Optional[str] = None

    # Parse [PARAM_NAME_START]...[PARAM_NAME_END] blocks
    name_pattern = r'\[PARAM_NAME_START\]\s*\n(.*?)\[PARAM_NAME_END\]'
    name_matches = list(re.finditer(name_pattern, params_block, re.DOTALL))

    # Parse [PARAM_VALUE_START]...[PARAM_VALUE_END] blocks
    value_pattern = r'\[PARAM_VALUE_START\]\s*\n(.*?)\[PARAM_VALUE_END\]'
    value_matches = list(re.finditer(value_pattern, params_block, re.DOTALL))

    if not name_matches or not value_matches:
        return None

    if len(name_matches) != len(value_matches):
        return None

    # Pair them up in order
    for name_match, value_match in zip(name_matches, value_matches):
        key = name_match.group(1).strip()
        value = value_match.group(1).strip()
        params[key] = value

    return params if params else None


def _parse_tool_block(block: str, expected_tool_name: Optional[str] = None) -> Tuple[Optional[str], Optional[Dict[str, str]]]:
    """Parse parameters from a tool call block.

    If expected_tool_name is provided (lenient mode), validates that the
    first param is tool_name:expected_tool_name. Otherwise, expects
    tool_name:tool_name_here as the first parameter.

    Returns (tool_name, params) or (None, None) if invalid.
    """
    params: Dict[str, str] = {}
    current_key: Optional[str] = None
    current_value_lines: List[str] = []
    tool_name: Optional[str] = expected_tool_name

    for line in block.split('\n'):
        new_param = re.match(r'^([a-zA-Z_][a-zA-Z0-9_]*):(.*)', line)

        if new_param:
            key = new_param.group(1)
            value = new_param.group(2)

            if key == 'tool_name':
                # First parameter is always the tool name
                if tool_name is not None:
                    # Already saved previous param
                    params[tool_name] = '\n'.join(current_value_lines)
                tool_name = value.strip()
                current_value_lines = []
            else:
                if tool_name is None:
                    # No tool_name param found yet - skip this block
                    return None, None
                if current_key is not None:
                    params[current_key] = '\n'.join(current_value_lines)
                current_key = key
                current_value_lines = [value]
        else:
            if current_key is not None:
                current_value_lines.append(line)

    if current_key is not None and tool_name is not None:
        params[current_key] = '\n'.join(current_value_lines)

    if tool_name is None:
        return None, None

    return tool_name, params


def _parse_tool_calls_lenient(response: str) -> List[Tuple[str, Dict[str, str]]]:
    """Parse tool calls by splitting on [TOOL_START] markers.

    Handles cases where the AI omits [TOOL_END] (truncation, format confusion).
    Each [TOOL_START] line starts a new tool call; the next [TOOL_START] or end
    of string marks the boundary.
    """
    calls = []
    # Split on [TOOL_START] to get individual tool blocks
    parts = response.split('[TOOL_START]')

    for part in parts:
        # Skip non-tool-call content (before first [TOOL_START])
        stripped = part.lstrip('\n')
        if not stripped:
            continue

        # First line should be tool_name:tool_name_here
        first_nl = stripped.find('\n')
        if first_nl == -1:
            continue  # No content after tool name line

        first_line = stripped[:first_nl]
        tool_name_match = re.match(r'^tool_name:(.+)$', first_line)
        if not tool_name_match:
            continue  # Not a valid tool call

        tool_name = tool_name_match.group(1).strip()
        if not re.match(r'^[a-zA-Z_][a-zA-Z0-9_-]*$', tool_name):
            continue

        # Rest is the parameter block (may contain [TOOL_END] or not)
        block = stripped[first_nl + 1:]

        # Strip trailing [TOOL_END] if present
        block = re.sub(r'\[TOOL_END\]\s*$', '', block)

        _, params = _parse_tool_block(block, expected_tool_name=tool_name)
        if params is not None:
            calls.append((tool_name, params))

    return calls


def is_done(response: str) -> Tuple[bool, str]:
    """Check if the LLM has indicated completion."""
    match = re.search(r'\[DONE\]\s*(.*)', response, re.DOTALL)
    if match:
        return True, match.group(1).strip()
    return False, ""


# Tools that support filtering (for when results are truncated)
TOOLS_WITH_FILTERS = {
    "list_directory": "Use a 'path' parameter to narrow to a specific subdirectory, or add a 'pattern' parameter to filter by name.",
    "search_files": "Use a 'pattern' parameter to narrow the search scope.",
    "grep_code": "Use a 'pattern' parameter to narrow the search scope.",
}


def truncate_tool_result(content: str, max_length: int, tool_name: str) -> Tuple[str, bool]:
    """Truncate a tool result if it exceeds max_length characters.

    Returns (truncated_content, was_truncated).
    When truncated, appends a notice telling the LLM it can use filters.
    """
    if max_length <= 0 or len(content) <= max_length:
        return content, False

    # Keep first N chars + last 200 for context
    tail = content[-200:] if len(content) > max_length + 200 else ""
    truncated = content[:max_length] + "\n\n... [TRUNCATED - output was too long, "
    truncated += f"showing first {max_length} of {len(content)} characters]"

    # Add guidance on how to filter
    filter_hint = TOOLS_WITH_FILTERS.get(tool_name)
    if filter_hint:
        truncated += f"\n\n[HINT] Result was truncated. Try narrowing your query: {filter_hint}"

    return truncated, True


class AgentEngine:
    """
    Multi-step agentic code revision engine.

    The engine runs a loop:
    1. Send conversation + tool results to LLM
    2. Parse tool calls from LLM response
    3. Execute tools (with full validation)
    4. Feed results back
    5. Repeat until [DONE] or max_steps reached
    """

    def __init__(self, project_config: Dict[str, Any], output_dir: Optional[str] = None,
                 step_callback=None):
        self.project_config = project_config
        self.root_dir = project_config.get("rootDirectory", EngineConfig.get_root_directory())
        self.instructions = project_config.get("instructions", "")
        self.job_id = project_config.get("job_id", str(int(time.time() * 1000)))

        # Use caller-provided output_dir (from UI) to ensure consistent
        # aib_instance/output/ path for both agent_engine and legacy modes.
        if output_dir:
            self.output_dir = output_dir
        else:
            self.output_dir = os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                "aib_instance", "output", self.job_id
            )
        self.log_file = os.path.join(self.output_dir, "log.txt")
        self.response_file = os.path.join(self.output_dir, "current_response.txt")
        self.step_log_file = os.path.join(self.output_dir, "steps.jsonl")

        os.makedirs(self.output_dir, exist_ok=True)

        # Set up logging
        self.logger = logging.getLogger(f"agent_engine.{self.job_id}")
        self.logger.setLevel(logging.INFO)
        self.logger.handlers = []
        self.logger.propagate = False

        fh = logging.FileHandler(self.log_file)
        fh.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
        self.logger.addHandler(fh)

        sh = logging.StreamHandler()
        sh.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
        self.logger.addHandler(sh)

        # Initialize tools with optional filtering
        # Prefer enabled_tools from project_config, fall back to env var
        enabled_tools = project_config.get("enabled_tools")
        if enabled_tools is None:
            enabled_tools = EngineConfig.get_enabled_tools()
        self.tools = ToolRegistry(self.root_dir, enabled_tools=enabled_tools)
        self.max_context_tokens = EngineConfig.get_max_context_tokens()
        self.max_output_tokens = EngineConfig.get_max_output_tokens()
        self.max_tool_result_length = EngineConfig.get_max_tool_result_length()
        self.llm = LLMClient(
            max_context_tokens=self.max_context_tokens,
            max_output_tokens=self.max_output_tokens,
        )

        # Conversation history
        self.messages: List[Dict[str, str]] = []
        self.system_prompt = build_system_prompt(self.tools.list_tools())
        self.messages.append({"role": "system", "content": self.system_prompt})

        # Results tracking
        self.step_count = 0
        self.max_steps = EngineConfig.get_max_steps()
        self.step_history: List[Dict[str, Any]] = []
        self._recent_tool_calls: List[str] = []  # Track recent tool names for loop detection
        self._permission_requested = False
        self._continue_requested = False

        # Callback for real-time event streaming (called from worker thread)
        self._step_callback = step_callback

    def run(self) -> Dict[str, Any]:
        """Execute the agentic revision loop."""
        self.logger.info(f"Starting agentic engine for: {self.root_dir}")
        self.logger.info(f"Instructions: {self.instructions[:200]}...")

        try:
            # Build initial prompt
            user_prompt = build_user_prompt(self.instructions)
            self.messages.append({"role": "user", "content": user_prompt})

            # Main loop
            final_summary = ""
            while self.step_count < self.max_steps or self._continue_requested:
                if self.step_count >= self.max_steps and not self._continue_requested:
                    self.logger.info("Max steps reached. Waiting for user continuation.")
                    return {
                        "status": "max_steps_reached",
                        "steps": self.step_count,
                        "summary": final_summary,
                        "max_steps": self.max_steps,
                        "step_history": self.step_history,
                    }

                self.step_count += 1
                self.logger.info(f"Step {self.step_count}/{self.max_steps}")

                # Check for live instructions injected mid-run
                live_instruction = EngineConfig.get_live_instruction(
                    self.job_id, base_dir=self.output_dir
                )
                if live_instruction:
                    self.logger.info(f"Received live instruction: {live_instruction[:100]}...")
                    self.messages.append({
                        "role": "user",
                        "content": f"[LIVE INJECTION] User has sent new instructions: {live_instruction}\n\nConsider this as an update to your task. You may need to adjust your approach or add to what you're doing.\n\nContinue with your next action."
                    })

                # Call LLM
                try:
                    msg_summary = f"{sum(1 for m in self.messages if m['role']=='system')}S/{sum(1 for m in self.messages if m['role']=='user')}U/{sum(1 for m in self.messages if m['role']=='assistant')}A"
                    self.logger.info(f"Calling LLM with {len(self.messages)} messages ({msg_summary})")
                    # Record LLM call for live feed
                    llm_entry = {
                        "step": self.step_count,
                        "tool": "llm_call",
                        "params": {"messages": len(self.messages), "msg_summary": msg_summary},
                        "result": {"content": "", "success": True},
                    }
                    self.step_history.append(llm_entry)
                    if self._step_callback:
                        try:
                            self._step_callback({"type": "llm_call", "step": self.step_count,
                                                 "params": llm_entry["params"]})
                        except Exception:
                            pass
                    response = self.llm.call(self.messages, self.response_file, system_prompt=self.system_prompt)
                except Exception as e:
                    self.logger.error(f"LLM call failed: {e}")
                    return {"status": "error", "error": str(e), "steps": self.step_count}

                # Log response
                with open(self.response_file, 'w', encoding='utf-8') as f:
                    f.write(response)

                # Check for completion
                done, summary = is_done(response)
                if done:
                    final_summary = summary
                    self.logger.info(f"Agent completed: {summary[:200]}")
                    break

                # Parse tool calls
                tool_calls = parse_tool_calls(response)
                if not tool_calls:
                    # No tool calls found - LLM may be reasoning or stuck
                    # Check if we're in a loop (same response pattern repeated)
                    self.logger.warning(f"No tool calls in response (step {self.step_count}). Response preview: {response[:200]}")
                    last_user_msg = ""
                    for msg in reversed(self.messages):
                        if msg["role"] == "user":
                            last_user_msg = msg.get("content", "")
                            break

                    # Check for repetition: if the last assistant message is very similar
                    # to the current response, send a stronger prompt
                    last_assistant = ""
                    for msg in reversed(self.messages):
                        if msg["role"] == "assistant":
                            last_assistant = msg.get("content", "")
                            break

                    is_repeating = (
                        last_assistant and response.strip() == last_assistant.strip()
                    )

                    if is_repeating:
                        # LLM is stuck in a loop - tell it to stop and use [DONE]
                        stuck_msg = (
                            "\n\n[LOOP DETECTED] You are repeating the same output. "
                            "Either complete the task with [DONE] and a summary, "
                            "or use a different tool call. Do NOT repeat the same tool call."
                        )
                        self.messages.append({"role": "user", "content": stuck_msg})
                    else:
                        reminder = (
                            "\n\n[REMINDER] You must take action using the available tools. "
                            "Use the [TOOL_START] / [TOOL_END] block format. "
                            "Inside the block, use [TOOL_NAME_START]...[TOOL_NAME_END] for the tool name, "
                            "then [PARAM_NAME_START]...[PARAM_NAME_END] for each parameter key, "
                            "followed by [PARAM_VALUE_START]...[PARAM_VALUE_END] for each parameter value. "
                            "Or [DONE] when you have finished all changes."
                        )
                        self.messages.append({"role": "user", "content": reminder})
                    continue

                # Strip tool call blocks from the response before appending to
                # history.  This prevents the LLM from seeing its own tool
                # calls in the conversation, which causes it to repeat them
                # verbatim.
                cleaned_response = re.sub(
                    r'\[TOOL_START\].*?\[TOOL_END\]',
                    '',
                    response,
                    flags=re.DOTALL,
                ).strip()

                # Append cleaned response once (before all tool results)
                if cleaned_response:
                    self.messages.append({
                        "role": "assistant",
                        "content": cleaned_response
                    })

                # Process each tool call
                for tool_name, params in tool_calls:
                    self.logger.info(f"  Tool: {tool_name}({json.dumps(params)})")

                    step_entry = {
                        "step": self.step_count,
                        "tool": tool_name,
                        "params": params,
                    }

                    try:
                        result = self.tools.execute(tool_name, params)
                        step_entry["result"] = result.to_dict()
                    except SecurityError as e:
                        step_entry["result"] = ToolResult(False, "", error=f"SECURITY: {e}").to_dict()
                        self.logger.warning(f"Security violation: {e}")
                    except ToolError as e:
                        step_entry["result"] = ToolResult(False, "", error=str(e)).to_dict()
                        self.logger.warning(f"Tool error: {e}")
                    except Exception as e:
                        step_entry["result"] = ToolResult(False, "", error=f"Unexpected error: {e}").to_dict()
                        self.logger.error(f"Unexpected tool error: {e}")

                    # If create_tool was used, emit a pending approval event
                    if tool_name == "create_tool":
                        if self._step_callback:
                            try:
                                tool_name_val = params.get("name", "unknown")
                                self._step_callback({"type": "pending_approval", "tool_name": tool_name_val})
                            except Exception:
                                pass

                    # Save step to history
                    self.step_history.append(step_entry)
                    with open(self.step_log_file, 'a', encoding='utf-8') as f:
                        f.write(json.dumps(step_entry) + '\n')

                    # Notify callback for real-time streaming
                    if self._step_callback:
                        try:
                            self._step_callback({"type": "step", "step": step_entry["step"],
                                                 "tool": step_entry["tool"],
                                                 "params": step_entry.get("params", {}),
                                                 "result": step_entry.get("result", {})})
                        except Exception:
                            pass

                    # Feed tool result back to conversation as a user message
                    # so the LLM properly sees and processes the result.
                    # Format results in a readable way (not raw JSON) so the LLM
                    # can easily extract file content for edit_file operations.
                    # Apply truncation to prevent context overflow.
                    res_dict = step_entry.get("result", {})
                    raw_content = ""
                    if res_dict.get("error"):
                        result_display = f"Error: {res_dict['error']}"
                    elif res_dict.get("summary"):
                        result_display = res_dict["summary"]
                        if res_dict.get("content"):
                            result_display += f"\n\nOutput:\n{res_dict['content']}\n"
                    elif res_dict.get("content"):
                        result_display = res_dict["content"]
                    else:
                        result_display = "(no output)"

                    # Truncate if needed
                    if res_dict.get("content"):
                        raw_content = res_dict["content"]
                        result_display, was_truncated = truncate_tool_result(
                            raw_content, self.max_tool_result_length, tool_name
                        )
                        if was_truncated:
                            result_display += (
                                f"\n\n[NOTE: This result was truncated from {len(raw_content)} "
                                f"to {self.max_tool_result_length} characters. "
                                f"The LLM was notified and can retry with filter parameters.]"
                            )
                    
                    tool_result_msg = {
                        "role": "user",
                        "content": f"[TOOL RESULT for {tool_name}]\n{result_display}\n[END TOOL RESULT]\n\nNow continue with your next action."
                    }
                    self.messages.append(tool_result_msg)
                    self.logger.info(f"  Fed tool result for '{tool_name}' back to LLM (msg length: {len(tool_result_msg['content'])} chars)")

                # Track recent tool calls for loop detection
                for tool_name, _ in tool_calls:
                    self._recent_tool_calls.append(tool_name)
                # Keep only last 5 calls
                if len(self._recent_tool_calls) > 5:
                    self._recent_tool_calls = self._recent_tool_calls[-5:]

                # Check for repeated tool calls without progress
                unique_recent = set(self._recent_tool_calls)
                if len(unique_recent) == 1 and len(self._recent_tool_calls) >= 3:
                    repeated_tool = list(unique_recent)[0]
                    self.logger.warning(f"Loop detected: {repeated_tool} called {len(self._recent_tool_calls)} times in a row without progress")
                    # Send a strong intervention message
                    intervention = (
                        f"\n\n[LOOP DETECTED] You have called {repeated_tool} {len(self._recent_tool_calls)} times in a row without making progress. "
                        f"This is not productive. You MUST choose a DIFFERENT tool or take a different action. "
                        f"Available tools: list_directory, search_files, grep_code, read_file, write_file, edit_file, delete_file, "
                        f"find_symbol, decompile_jar, list_dependencies, check_syntax, get_file_info, create_tool. "
                        f"Think about what you've learned so far and what you need to do next. "
                        f"Either make a concrete change with write_file/edit_file, or gather specific information with a different tool. "
                        f"DO NOT call {repeated_tool} again."
                    )
                    self.messages.append({"role": "user", "content": intervention})
                    continue

            return {
                "status": "completed" if final_summary else "max_steps_reached",
                "steps": self.step_count,
                "summary": final_summary,
                "max_steps": self.max_steps,
                "step_history": self.step_history,
            }

        except Exception as e:
            self.logger.error(f"Engine fatal error: {e}", exc_info=True)
            return {"status": "error", "error": str(e), "steps": self.step_count}

    def _run_script(self, script_type: str, script_content: str):
        """Run a pre/post script safely."""
        if not script_content.strip():
            return
        script_name = f"{script_type}.ps1"
        temp_path = os.path.join(self.output_dir, f"{script_name}_{uuid.uuid4().hex}")
        with open(temp_path, 'w', encoding='utf-8') as f:
            f.write(script_content)
        try:
            ps = "powershell" if platform.system() == "Windows" else "pwsh"
            subprocess.run(
                [ps, "-File", temp_path, "-WorkingDirectory", self.root_dir],
                check=True, capture_output=True, text=True, timeout=300
            )
            self.logger.info(f"Executed {script_name}")
        except Exception as e:
            self.logger.error(f"Script execution failed: {e}")
        finally:
            try:
                os.remove(temp_path)
            except OSError:
                pass


def run(project_config: Dict[str, Any], output_dir: Optional[str] = None,
        step_callback=None) -> Dict[str, Any]:
    """Run the agentic engine with the given project configuration."""
    if output_dir is None:
        root_dir = project_config.get("rootDirectory", EngineConfig.get_root_directory())
        output_dir = os.path.join(root_dir, "aib_instance", "output",
                                   project_config.get("job_id", ""))
    engine = AgentEngine(project_config, output_dir=output_dir,
                         step_callback=step_callback)
    return engine.run()


if __name__ == "__main__":
    config_json = os.getenv("AIB_PROJECT_CONFIG")
    if config_json:
        config = json.loads(config_json)
    else:
        config = {
            "rootDirectory": EngineConfig.get_root_directory(),
            "instructions": os.getenv("AIB_INSTRUCTIONS", ""),
            "job_id": str(int(time.time() * 1000)),
        }

    result = run(config)
    print(json.dumps(result, indent=2))
