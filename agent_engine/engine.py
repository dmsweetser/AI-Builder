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
    MAX_CALL_TIME = 7200  # seconds — hard timeout per LLM call

    def __init__(self, max_context_tokens: int = 0, max_output_tokens: int = 0,
                 audit_dir: Optional[str] = None):
        self._prompt_file_counter = 0
        self._max_context_tokens = max_context_tokens
        self._max_output_tokens = max_output_tokens
        self._audit_dir = audit_dir
        if self._audit_dir:
            os.makedirs(self._audit_dir, exist_ok=True)

    def _audit_filename(self, step: int) -> Tuple[str, str]:
        """Return (request_file, response_file) paths for a given step."""
        if not self._audit_dir:
            return "", ""
        ts = time.time()
        tick = f"{ts:016.6f}".replace('.', '')[:16]  # 16-digit numeric tick for natural sort
        req = os.path.join(self._audit_dir, f"{tick}_step{step}_request.json")
        resp = os.path.join(self._audit_dir, f"{tick}_step{step}_response.json")
        return req, resp

    def call(self, messages: List[Dict[str, str]], response_file: Optional[str] = None,
             system_prompt: str = "", step: int = 0) -> Dict[str, Any]:
        """Call the LLM with retry logic and context trimming.

        Returns a dict with:
          - 'content': the LLM response text
          - 'raw_request': the full request JSON (truncated to 3000 chars)
          - 'raw_response': the full response text (truncated to 2000 chars)
        """
        last_err = None
        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                return self._call_custom_endpoint(messages, response_file, system_prompt, step)
            except Exception as e:
                last_err = e
                if attempt < self.MAX_RETRIES:
                    delay = self.BASE_DELAY * (2 ** (attempt - 1))
                    jitter = delay * (0.5 + 0.5 * _random.random())
                    _time.sleep(jitter)
        raise EngineError(f"LLM call failed after {self.MAX_RETRIES} attempts: {last_err}")

    def _call_custom_endpoint(self, messages: List[Dict[str, str]],
                              response_file: Optional[str], system_prompt: str,
                              step: int = 0) -> Dict[str, Any]:
        """Call a custom OpenAI-compatible endpoint (Ollama, LM Studio, vLLM, etc.).

        Returns a dict with:
          - 'content': the LLM response text
          - 'raw_request': the full request JSON (truncated to 3000 chars)
          - 'raw_response': the full response text (truncated to 2000 chars)
        """
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

        # --- Audit: log the full request ---
        req_file, resp_file = self._audit_filename(step)
        if req_file:
            audit_payload = {
                "step": step,
                "timestamp": time.time(),
                "model": model_name,
                "endpoint": endpoint_url,
                "message_count": len(openai_messages),
                "messages": openai_messages,
            }
            with open(req_file, 'w', encoding='utf-8') as f:
                json.dump(audit_payload, f, indent=2, ensure_ascii=False)

        payload: Dict[str, Any] = {
            "model": model_name,
            "messages": openai_messages,
            "stream": True,
        }
        if self._max_output_tokens > 0:
            payload["max_tokens"] = self._max_output_tokens

        # Build headers (redact API key for audit)
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        # Serialize the full request for raw_response
        full_request_json = json.dumps(payload, indent=2)

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
        reasoning = ""
        call_start = time.time()
        try:
            with urllib.request.urlopen(req, context=context, timeout=timeout) as response:
                for line in response:
                    # Check for hard timeout
                    if time.time() - call_start > self.MAX_CALL_TIME:
                        self.logger.warning(
                            f"LLM call timed out after {self.MAX_CALL_TIME}s "
                            f"(step {step})"
                        )
                        break

                    line = line.decode('utf-8').strip()
                    if not line.startswith('data: '):
                        continue
                    data_str = line[6:]
                    if data_str == '[DONE]':
                        break
                    try:
                        chunk = json.loads(data_str)
                        delta = chunk.get('choices', [{}])[0].get('delta', {})
                        # Prefer 'content' for the final response. Some models
                        # (e.g. Qwen with native thinking) only output
                        # 'reasoning_content' and never emit 'content'.
                        # In that case, fall back to the reasoning stream.
                        c = delta.get('content')
                        if c:
                            content += c
                            if response_file and len(content) % 100 == 0:
                                with open(response_file, 'w', encoding='utf-8') as rf:
                                    rf.write(content)
                        # Collect reasoning as fallback (only when content is empty)
                        r = delta.get('reasoning_content')
                        if r:
                            reasoning += r
                    except json.JSONDecodeError:
                        continue
        except _urllib_error.HTTPError as e:
            body = e.read().decode('utf-8', errors='replace') if hasattr(e, 'read') else ''
            raise EngineError(f"Custom endpoint HTTP {e.code}: {body}")
        except Exception as e:
            raise EngineError(f"Custom endpoint call failed: {e}")

        # If the model only outputs reasoning_content (no 'content' chunks),
        # use the reasoning stream as the response. This handles models like
        # Qwen with native thinking enabled.
        if not content and reasoning:
            content = reasoning

        # --- Audit: log the full response ---
        if resp_file:
            audit_response = {
                "step": step,
                "timestamp": time.time(),
                "model": model_name,
                "content": content,
                "reasoning": reasoning,
                "total_chars": len(content),
            }
            with open(resp_file, 'w', encoding='utf-8') as f:
                json.dump(audit_response, f, indent=2, ensure_ascii=False)

        # Return raw request and response for SSE streaming
        return {
            "content": content,
            "raw_request": full_request_json[:3000],
            "raw_response": content[:2000],
        }



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
        "[TOOL_NAME]\n"
        "write_file\n"
        "[PARAM_NAME]\n"
        "path\n"
        "[PARAM_VALUE]\n"
        "src/hello.py\n"
        "[PARAM_NAME]\n"
        "content\n"
        "[PARAM_VALUE]\n"
        "\"\"\"Hello module.\"\"\"\n"
        "from src.main import greet\n"
        "\n"
        'if __name__ == "__main__":\n'
        '    print(greet("World"))\n'
        "[RATIONALE]\n"
        "Writing the entry point file with the greet function import.\n"
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
- For large files, use read_file_range with a line_range parameter to read specific sections. Do NOT read entire large files.
- For Java projects with JAR dependencies, use decompile_jar to inspect them.
- For large codebases, be selective: grep for relevant code, don't read everything.
- You have a maximum of {EngineConfig.get_max_steps()} steps total. Use them wisely.
- After making changes, verify them. If check_syntax fails, fix the errors.
- When done, respond with: [DONE] followed by a summary of all changes made.
- To create a new tool, use create_tool. It proposes the tool for user approval - it does NOT execute arbitrary code. Wait for user approval in the live feed before expecting the tool to be available.
- Use respond_to_user to communicate findings, status updates, or questions to the user.
- Use request_user_input when you need clarification or a decision before proceeding.

TRUNCATION HANDLING:
- Tool results may be truncated if they exceed the configured max length (default 5000 chars).
- If a result says [TRUNCATED], the output was cut off. You should retry with more specific parameters.

PARAMETER FORMAT (tag-based, NO EXCEPTIONS):
- Your ENTIRE response MUST be exactly ONE of the following:
  1. A single tool call block using [TOOL_START]...[TOOL_END]
  2. A final completion: [DONE] followed by a summary
- You are FORBIDDEN from writing any other text outside of tool call blocks.
- Do NOT write any reasoning, thinking, or explanation text.
- Do NOT write "I will..." or "Let me..." or any natural language.
- Do NOT explain what you are about to do — just DO it with a tool call.

The EXACT format for a tool call is:

[TOOL_START]
[TOOL_NAME]
the tool name here
[PARAM_NAME]
the first parameter key
[PARAM_VALUE]
the first parameter value
[PARAM_NAME]
the second parameter key
[PARAM_VALUE]
the second parameter value
[RATIONALE]
(optional) Explain why you are making this tool call — your reasoning, strategy, or what you expect to happen. This helps the user understand your thought process.
[TOOL_END]

Rules for the format:
- [TOOL_START] and [TOOL_END] wrap the entire tool call
- [TOOL_NAME] appears once, right after [TOOL_START], followed by the tool name on the next line
- Each parameter uses exactly two tags: [PARAM_NAME] followed by the key, then [PARAM_VALUE] followed by the value
- [RATIONALE] is optional and can appear after all parameters, before [TOOL_END]. It contains your reasoning for the tool call.
- Values may span multiple lines between [PARAM_VALUE] and the next [PARAM_NAME] or [TOOL_END]
- You MUST include both [TOOL_START] and [TOOL_END]
- Make exactly ONE tool call per response

STRING LITERAL ESCAPING (CRITICAL):
- When writing code that contains string literals with escape sequences (e.g., Python's "\n", "\t", "\r"),
  you MUST double-escape them: use \\n instead of \n, \\t instead of \t, \\r instead of \r.
- This is because the tool environment converts single-backslash escape sequences to their actual characters.
- Example for Python: write 'hello\\nworld' in the PARAM_VALUE to produce the source code 'hello\nworld'.
- Example for JavaScript: write 'line1\\nline2' to produce 'line1\\nline2' in the file.
- Line breaks in the code itself should be actual newlines (press Enter), not \\n.
- This rule applies to ALL string literals in ALL languages: Python, JavaScript, Java, C++, etc.

Example:
{example_block}

RESPONSE FORMAT:
After each tool result, your ENTIRE response must be exactly one of:
1. A tool call block (see PARAMETER FORMAT above) — nothing else
2. Or a final response: [DONE] Your summary of changes.

You are NOT allowed to write any text outside of tool call blocks or [DONE].
Any text outside these formats will be ignored.

CRITICAL: Make EXACTLY ONE tool call per response. Do not include multiple tool call blocks. If you include more than one [TOOL_START]...[TOOL_END] block, only the FIRST one will be executed — the rest will be ignored as invalid output.

IMPORTANT: You are bounded to the project root directory by default. All file paths are relative to it.
You CANNOT read or write files outside the project root unless the task instructions explicitly specify an absolute path (e.g., /tmp/something.py).
When the instructions specify an absolute path, use it directly.

TOOL APPROVAL:
When you use the create_tool to propose a new tool, you MUST wait for user approval before using it.
After calling create_tool, do NOT call the new tool in the same response. Wait for the user to approve it in the UI.
If the tool is approved, it will appear in the tool selector. You can then use it in subsequent steps.
If the tool is rejected, do not use it. Choose a different approach or use existing tools.
You will see a "PENDING TOOL APPROVAL" message in the live feed while waiting for user review.

CONTEXT MANAGEMENT:
- If you have accumulated many tool results and the conversation is getting long, use the compress_context tool to summarize prior steps into a compact summary.
- This helps free up context space for new work. Provide a summary that captures what was learned, what files were modified, and the current state of the project.
- After compressing, continue with your next action using the compressed context.
'''


def build_user_prompt(instructions: str, context: str = "") -> str:
    """Build the initial user prompt with the task instructions."""
    prompt = f"""TASK INSTRUCTIONS:
{instructions}

CRITICAL INSTRUCTIONS:
1. You MUST use a tool call to take action. Do NOT just talk about what you will do.
2. Your FIRST action MUST be: list_directory with path="."
3. Do NOT use [DONE] until you have actually used tools and gathered information.
4. Your ENTIRE response must be ONLY a tool call block or [DONE]. No other text.
5. Format your tool call EXACTLY like this example:

[TOOL_START]
[TOOL_NAME]
list_directory
[PARAM_NAME]
path
[PARAM_VALUE]
.
[TOOL_END]

STEP 1: Use list_directory to explore the project structure. Do NOT use [DONE] yet - you must take action first."""
    if context:
        prompt += f"\n\nRELEVANT CONTEXT:\n{context}"
    return prompt


def parse_tool_calls(response: str) -> List[Tuple[str, Dict[str, str], Optional[str]]]:
    """Parse tool calls from LLM response using the simplified tag-based format.

    Format:
        [TOOL_START]
        [TOOL_NAME]
        write_file
        [PARAM_NAME]
        path
        [PARAM_VALUE]
        src/hello.py
        [RATIONALE]
        Writing the entry point file.
        [TOOL_END]

    Also handles LLM quirks:
    - [PARAM_END] is treated as [TOOL_END]
    - [tool_name] directly after [TOOL_START] (without [TOOL_NAME] tag)
    - Natural language text before/after tool call blocks
    - [RATIONALE] block for explaining reasoning
    """
    calls = []
    # Normalize LLM quirks: treat [PARAM_END] as [TOOL_END]
    normalized = response.replace('[PARAM_END]', '[TOOL_END]')

    # Also handle the case where LLM uses [tool_name] directly instead of
    # [TOOL_NAME] tag (e.g., "[list_directory]" instead of "[TOOL_NAME]\nlist_directory")
    # Pattern: [TOOL_START][tool_name]...[TOOL_END]
    alt_pattern = r'\[TOOL_START\]\s*\[([^\]]+)\]\s*(.*?)\[TOOL_END\]'
    alt_matches = list(re.finditer(alt_pattern, normalized, re.DOTALL))

    # Also try the standard pattern: [TOOL_START][TOOL_NAME]\nname\n...[TOOL_END]
    tool_pattern = r'\[TOOL_START\]\s*\[TOOL_NAME\]\s*\n(.*?)\n(.*?)\[TOOL_END\]'
    tool_matches = list(re.finditer(tool_pattern, normalized, re.DOTALL))

    # Prefer standard matches; fall back to alt matches if no standard matches found
    if tool_matches:
        for match in tool_matches:
            tool_name = match.group(1).strip()
            params_block = match.group(2)
            rationale = _extract_rationale(params_block)
            # Strip rationale block so the param parser doesn't see it.
            # Use '$' anchor (end of string) instead of '[TOOL_END]' because
            # the main regex already consumed [TOOL_END] as the delimiter,
            # so it is NOT present in params_block.
            params_block = re.sub(r'\[RATIONALE\].*?$', '', params_block, flags=re.DOTALL)
            params = _parse_params(params_block)
            if tool_name and params is not None:
                calls.append((tool_name, params, rationale))
    elif alt_matches:
        for match in alt_matches:
            tool_name = match.group(1).strip()
            params_block = match.group(2)
            rationale = _extract_rationale(params_block)
            params_block = re.sub(r'\[RATIONALE\].*?$', '', params_block, flags=re.DOTALL)
            params = _parse_params(params_block)
            if tool_name and params is not None:
                calls.append((tool_name, params, rationale))

    return calls


def _extract_rationale(params_block: str) -> Optional[str]:
    """Extract [RATIONALE] block from params if present."""
    rationale_match = re.search(r'\[RATIONALE\]\s*\n(.*?)(?=\[TOOL_END\]|\[TOOL_NAME\]|\Z)', params_block, re.DOTALL)
    if rationale_match:
        rationale = rationale_match.group(1).strip()
        if rationale:
            return rationale
    return None


def _parse_params(params_block: str) -> Optional[Dict[str, str]]:
    """Parse parameters from the simplified tag-based format.

    Format:
        [PARAM_NAME]
        key
        [PARAM_VALUE]
        value
        [PARAM_NAME]
        key2
        [PARAM_VALUE]
        value2

    NAME/VALUE pairs alternate: each parameter is a NAME tag followed by a VALUE tag.
    """
    params: Dict[str, str] = {}

    # Split into tokens by tag
    # Strategy: find all [PARAM_NAME] and [PARAM_VALUE] tags and their content
    name_pattern = r'\[PARAM_NAME\]\s*\n(.*?)(?=\[PARAM_VALUE\]|\[TOOL_END\]|\[TOOL_NAME\]|\Z)'
    value_pattern = r'\[PARAM_VALUE\]\s*\n(.*?)(?=\[PARAM_NAME\]|\[TOOL_END\]|\[TOOL_NAME\]|\Z)'

    name_matches = list(re.finditer(name_pattern, params_block, re.DOTALL))
    value_matches = list(re.finditer(value_pattern, params_block, re.DOTALL))

    if len(name_matches) != len(value_matches):
        # Fallback: try a simpler approach - just grab everything between tags
        # Split by [PARAM_NAME] and [PARAM_VALUE] tags
        parts = re.split(r'(\[PARAM_NAME\]|\[PARAM_VALUE\])', params_block)
        if len(parts) >= 4:
            i = 0
            while i < len(parts) - 2:
                if parts[i].strip() == '[PARAM_NAME]':
                    key = parts[i+1].strip() if i+1 < len(parts) else ''
                    if i+2 < len(parts) and parts[i+2].strip() == '[PARAM_VALUE]':
                        val = parts[i+3].strip() if i+3 < len(parts) else ''
                        if key and val:
                            params[key] = val
                    i += 4
                else:
                    i += 1
            return params if params else None
        return None

    if not name_matches or not value_matches:
        return None

    # Pair them up in order
    for name_match, value_match in zip(name_matches, value_matches):
        key = name_match.group(1).strip()
        value = value_match.group(1).strip()
        if key:  # Skip empty keys
            params[key] = value

    return params if params else None


def is_done(response: str) -> Tuple[bool, str]:
    """Check if the LLM has indicated completion."""
    match = re.search(r'\[DONE\]\s*(.*)', response, re.DOTALL)
    if match:
        return True, match.group(1).strip()
    return False, ""


# Tools that support filtering (for when results are truncated)
TOOLS_WITH_FILTERS = {
    "list_directory": "Use list_directory_deep to explore subdirectories recursively.",
    "search_files": "Use search_files_dir with a directory parameter to narrow the search scope.",
    "grep_code": "Use grep_code_dir with a directory parameter to narrow the search scope.",
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
        # Set up LLM audit directory for per-step request/response logging
        self.audit_dir = os.path.join(self.output_dir, "llm_audit")
        self.llm = LLMClient(
            max_context_tokens=self.max_context_tokens,
            max_output_tokens=self.max_output_tokens,
            audit_dir=self.audit_dir,
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
        self._files_seen: set = set()  # Track files already read
        self._file_lines_seen: dict = {}  # Track (file, line_range) pairs already read
        self._read_step_count = 0  # Track consecutive read-only steps
        self._max_read_steps = 8  # Max steps allowed for reading before forcing action
        self._action_forced = False  # Track if we've forced the LLM to act

        # Callback for real-time event streaming (called from worker thread)
        self._step_callback = step_callback

        # Context compression settings
        self._compress_threshold = 28  # Compress when message count exceeds this
        self._compressed = False  # Track if we've already compressed

    def reload_approved_tools(self):
        """Reload approved tools from disk and rebuild system prompt.

        Call this after tool approval to make newly approved tools
        visible to the LLM without restarting the engine.
        """
        self.tools._load_approved_tools()
        self.system_prompt = build_system_prompt(self.tools.list_tools())
        # Replace the system prompt message in-place so the LLM sees the
        # updated tool list on the next call.
        if self.messages and self.messages[0].get("role") == "system":
            self.messages[0]["content"] = self.system_prompt

    def run(self) -> Dict[str, Any]:
        """Execute the agentic revision loop."""
        # Reload approved tools so any tools approved since the last run
        # are visible to the LLM immediately.
        self.reload_approved_tools()
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
                    # Use a clear separator and explicit instruction to start fresh
                    self.messages.append({
                        "role": "user",
                        "content": (
                            "========== NEW USER INSTRUCTION ==========\n"
                            f"User has sent new instructions:\n{live_instruction}\n"
                            "========== END NEW INSTRUCTION ==========\n\n"
                            "You must respond with EXACTLY ONE tool call. "
                            "Do NOT combine this with any previous context. "
                            "Start fresh with a single tool call to address the new instructions."
                        )
                    })

                # Auto-compress context if conversation is getting too long
                if (not self._compressed and
                    len(self.messages) > self._compress_threshold):
                    self.logger.info(
                        f"Auto-compressing context: {len(self.messages)} messages "
                        f"(threshold: {self._compress_threshold})"
                    )
                    # Build a compact summary from the step history
                    summary_parts = []
                    summary_parts.append(
                        f"Project: {self.root_dir}"
                    )
                    summary_parts.append(
                        f"Task: {self.instructions[:300]}"
                    )

                    # Track what files were read and key findings
                    files_read = {}
                    files_modified = []
                    for h in self.step_history:
                        tool = h.get("tool", "unknown")
                        params = h.get("params", {})
                        result = h.get("result", {})
                        content = result.get("content", "")
                        summary = result.get("summary", "")
                        error = result.get("error", "")

                        if error:
                            summary_parts.append(
                                f"  - {tool}: FAILED ({error})"
                            )
                        elif tool in ("read_file", "read_file_range"):
                            path = params.get("path", "unknown")
                            line_range = params.get("line_range", "full")
                            files_read[path] = {
                                "lines": line_range,
                                "size": len(content),
                            }
                            # Include key excerpts for files we might need to edit
                            if len(content) > 0 and len(content) < 3000:
                                # Include the full content for small files
                                files_read[path]["content"] = content[:2000]
                            elif len(content) > 0:
                                # Include first 500 and last 500 chars for large files
                                files_read[path]["content"] = content[:500] + "\n... [truncated] ...\n" + content[-500:]
                        elif tool in ("write_file", "edit_file", "delete_file"):
                            path = params.get("path", "unknown")
                            files_modified.append((tool, path))
                        elif tool in ("list_directory", "list_directory_deep"):
                            path = params.get("path", ".")
                            summary_parts.append(
                                f"  - {tool}: {path}"
                            )
                        elif tool in ("grep_code", "grep_code_dir",
                                      "search_files", "search_files_dir"):
                            pattern = params.get("pattern", "")
                            directory = params.get("directory", "root")
                            summary_parts.append(
                                f"  - {tool}: pattern='{pattern}' dir='{directory}'"
                            )
                        elif tool == "check_syntax":
                            path = params.get("path", "unknown")
                            if "passed" in (summary or "").lower() or "ok" in (summary or "").lower():
                                summary_parts.append(f"  - {tool}: {path} OK")
                            else:
                                summary_parts.append(f"  - {tool}: {path} FAILED ({error})")
                        else:
                            summary_parts.append(
                                f"  - {tool}: {params}"
                            )

                    # Add file content summaries (critical for LLM to continue editing)
                    if files_read:
                        summary_parts.append("\nFILES READ (content included):")
                        for path, info in files_read.items():
                            summary_parts.append(f"\n--- {path} (lines {info.get('lines', 'full')}, {info['size']} bytes) ---")
                            if "content" in info:
                                summary_parts.append(info["content"])
                            else:
                                summary_parts.append(f"[content truncated, {info['size']} bytes]")

                    if files_modified:
                        summary_parts.append("\nFILES MODIFIED:")
                        for tool, path in files_modified:
                            summary_parts.append(f"  - {tool}: {path}")

                    summary_text = "\n".join(summary_parts)

                    # Keep the last N messages for recent context, compress the rest
                    messages_to_compress = self.messages[1:]  # Exclude system prompt
                    messages_to_keep = 6  # Keep last 6 messages (3 turns of user/assistant)
                    messages_to_compress_list = messages_to_compress[:-messages_to_keep] if len(messages_to_compress) > messages_to_keep else []
                    messages_to_keep_list = messages_to_compress[-messages_to_keep:] if len(messages_to_compress) > messages_to_keep else messages_to_compress

                    # Build compressed summary for older messages
                    compressed_summary = (
                        f"[CONTEXT COMPRESSED]\n"
                        f"Your prior conversation has been compressed to save context space.\n"
                        f"Here is the summary of what was done, including file contents:\n\n"
                        f"{summary_text}\n\n"
                        f"[STATE: You have already read {len(self._files_seen)} files. "
                        f"DO NOT read any more files. YOU MUST NOW TAKE ACTION.\n"
                        f"Use edit_file to fix issues, write_file to create files, or delete_file to remove files.\n"
                        f"If you need to make changes, use the file contents included above.\n"
                        f"DO NOT explore further. TAKE ACTION NOW.]"
                    )

                    # Rebuild messages: system + compressed summary + last N messages
                    self.messages = [
                        self.messages[0],  # Keep system prompt
                        {
                            "role": "user",
                            "content": compressed_summary,
                        },
                    ]
                    # Append the most recent messages for recent context
                    for msg in messages_to_keep_list:
                        self.messages.append(msg)
                    # Add a continuation prompt
                    self.messages.append({
                        "role": "user",
                        "content": "Continue with your next action.",
                    })
                    self._compressed = True
                    # Keep the read budget counter so it doesn't reset after compression
                    self.logger.info(
                        f"Context compressed. Messages reduced to {len(self.messages)}. "
                        f"Files read: {len(files_read)}, Files modified: {len(files_modified)}"
                    )

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
                    llm_result = self.llm.call(self.messages, self.response_file, system_prompt=self.system_prompt, step=self.step_count)
                    response = llm_result["content"]
                    # Emit raw LLM request/response for live feed
                    if self._step_callback:
                        try:
                            self._step_callback({
                                "type": "llm_call",
                                "step": self.step_count,
                                "params": llm_entry["params"],
                                "raw_request": llm_result.get("raw_request", ""),
                                "raw_response": llm_result.get("raw_response", ""),
                            })
                        except Exception:
                            pass
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
                    # No tool calls and no [DONE] — the LLM likely didn't
                    # produce a properly formatted tool call. Send a reminder
                    # back and let it try again (up to a retry budget).
                    self.logger.warning(
                        f"No tool calls in response (step {self.step_count}). "
                        f"Response preview: {response[:200]}"
                    )
                    # Count consecutive non-tool-call steps
                    consecutive_no_tool = sum(
                        1 for h in self.step_history[-5:]
                        if h.get("tool") not in (
                            "list_directory", "list_directory_deep",
                            "search_files", "search_files_dir",
                            "grep_code", "grep_code_dir",
                            "read_file", "read_file_range",
                            "write_file", "edit_file",
                            "delete_file", "find_symbol", "decompile_jar",
                            "list_dependencies", "check_syntax", "get_file_info",
                            "create_tool", "compress_context",
                            "respond_to_user", "request_user_input",
                        )
                    )
                    if consecutive_no_tool >= 3:
                        # After 3 failed attempts, pause and ask the user
                        if self._step_callback:
                            try:
                                self._step_callback({
                                    "type": "pending_user_input",
                                    "step": self.step_count,
                                    "response": (
                                        "The agent failed to produce a valid tool call "
                                        "after 3 attempts. You can try resuming with a "
                                        "nudge, or stop the run.\n\n"
                                        f"Last LLM response:\n{response[:500]}"
                                    ),
                                })
                            except Exception:
                                pass
                        return {
                            "status": "pending_user_input",
                            "steps": self.step_count,
                            "summary": response.strip(),
                            "max_steps": self.max_steps,
                            "step_history": self.step_history,
                        }
                    # Send a reminder and continue
                    reminder = (
                        "[FORMAT ERROR] Your response contained NO valid tool call. "
                        "Your ENTIRE response must be ONLY a tool call block or [DONE]. "
                        "Do NOT write any reasoning, thinking, or explanation text. "
                        "Do NOT write \"I will...\" or \"Let me...\" or any natural language. "
                        "Here is the EXACT format you must use — copy it verbatim:\n\n"
                        "[TOOL_START]\n"
                        "[TOOL_NAME]\n"
                        "list_directory\n"
                        "[PARAM_NAME]\n"
                        "path\n"
                        "[PARAM_VALUE]\n"
                        ".\n"
                        "[TOOL_END]\n\n"
                        "Start with list_directory to explore the project. NOTHING ELSE."
                    )
                    self.messages.append({
                        "role": "user",
                        "content": f"{reminder}\n\nPlease try again with a proper tool call.",
                    })
                    # Log this as an llm_call retry so it shows in the feed
                    if self._step_callback:
                        try:
                            self._step_callback({
                                "type": "step",
                                "step": self.step_count,
                                "tool": "format_retry",
                                "params": {},
                                "result": {"success": True, "content": "Format reminder sent — retrying…"},
                            })
                        except Exception:
                            pass
                    continue

                # Only process the first tool call per step (enforce single-call rule)
                if tool_calls:
                    tool_calls = [tool_calls[0]]

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
                for tool_name, params, rationale in tool_calls:
                    self.logger.info(f"  Tool: {tool_name}({json.dumps(params)})")

                    step_entry = {
                        "step": self.step_count,
                        "tool": tool_name,
                        "params": params,
                    }
                    if rationale:
                        step_entry["rationale"] = rationale

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

                    # Track files seen for loop prevention
                    if tool_name in ("read_file", "read_file_range"):
                        path = params.get("path", "")
                        self._files_seen.add(path)
                        if tool_name == "read_file_range":
                            line_range = params.get("line_range", "")
                            self._file_lines_seen.setdefault(path, set()).add(line_range)

                    # If create_tool was used, emit a pending approval event
                    # and PAUSE the engine — do NOT continue the loop.
                    # The user must approve/reject before the agent proceeds.
                    if tool_name == "create_tool":
                        if self._step_callback:
                            try:
                                tool_name_val = params.get("name", "unknown")
                                self._step_callback({
                                    "type": "pending_approval",
                                    "tool_name": tool_name_val,
                                })
                            except Exception:
                                pass
                        # Pause: do NOT feed result back or call LLM again.
                        # The engine returns so the UI can show the pending
                        # approval. When the user approves, a new run is
                        # started (which reloads approved tools into the
                        # registry and rebuilds the system prompt).
                        self.logger.info(
                            "create_tool called — pausing engine for approval."
                        )
                        return {
                            "status": "pending_approval",
                            "steps": self.step_count,
                            "summary": final_summary,
                            "max_steps": self.max_steps,
                            "step_history": self.step_history,
                        }

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
                for tool_name, _, _ in tool_calls:
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
                        f"Available tools: list_directory, list_directory_deep, search_files, search_files_dir, "
                        f"grep_code, grep_code_dir, read_file, read_file_range, write_file, edit_file, delete_file, "
                        f"find_symbol, decompile_jar, list_dependencies, check_syntax, get_file_info, "
                        f"create_tool, compress_context, respond_to_user, request_user_input. "
                        f"Think about what you've learned so far and what you need to do next. "
                        f"Either make a concrete change with write_file/edit_file, or gather specific information with a different tool. "
                        f"DO NOT call {repeated_tool} again. "
                        f"If you need more context, use read_file_range to read specific sections of files. "
                        f"If the conversation is getting too long, use compress_context to summarize prior work. "
                        f"If you need to communicate with the user, use respond_to_user."
                    )
                    self.messages.append({"role": "user", "content": intervention})
                    continue

                # Check for repeated reads of the same file (not just same tool)
                if tool_calls:
                    tc_name, tc_params, _ = tool_calls[0]
                    if tc_name in ("read_file", "read_file_range"):
                        path = tc_params.get("path", "")
                        if path and path in self._files_seen:
                            # Check if we've already read this file or overlapping lines
                            if tc_name == "read_file" and path in self._files_seen:
                                # Full file read — check if we've read it before
                                if path in self._file_lines_seen:
                                    all_lines = self._file_lines_seen[path]
                                    if len(all_lines) >= 3:
                                        # We've read this file 3+ times already
                                        self.logger.warning(
                                            f"Repeated read detected: {path} read {len(all_lines)} times"
                                        )
                                        # Don't read again — suggest editing or moving on
                                        next_action = (
                                            f"\n\n[NOTE] You have already read {path} {len(all_lines)} times. "
                                            f"Further reads will not give you new information. "
                                            f"You should either: (1) make changes with edit_file/write_file, "
                                            f"(2) read a DIFFERENT file, or "
                                            f"(3) use check_syntax to verify your changes."
                                        )
                                        self.messages.append({"role": "user", "content": next_action})
                                        continue
                            elif tc_name == "read_file_range":
                                line_range = tc_params.get("line_range", "")
                                if path in self._file_lines_seen and line_range in self._file_lines_seen[path]:
                                    self.logger.warning(
                                        f"Duplicate read: {path} lines {line_range} already read"
                                    )
                                    next_action = (
                                        f"\n\n[NOTE] You have already read {path} lines {line_range}. "
                                        f"Try reading a different range or a different file."
                                    )
                                    self.messages.append({"role": "user", "content": next_action})
                                    continue

                    # Track read budget: increment counter for read-only steps, reset for action steps
                    if tc_name in ("read_file", "read_file_range"):
                        self._read_step_count += 1
                    elif tc_name in ("list_directory", "list_directory_deep", "grep_code",
                                     "grep_code_dir", "search_files", "search_files_dir",
                                     "get_file_info"):
                        # These are exploration steps — increment but less aggressively
                        self._read_step_count += 1
                    else:
                        # Action step (write, edit, delete, check_syntax, etc.) — reset counter
                        self._read_step_count = 0
                        self._action_forced = False
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
        # Load instructions from file (to avoid env var length limits)
        instructions_file = os.environ.get("AIB_INSTRUCTIONS_FILE", "")
        if instructions_file and os.path.exists(instructions_file):
            with open(instructions_file, 'r', encoding='utf-8') as f:
                instructions = f.read()
        else:
            instructions = os.environ.get("AIB_INSTRUCTIONS", "")
        config = {
            "rootDirectory": EngineConfig.get_root_directory(),
            "instructions": instructions,
            "job_id": str(int(time.time() * 1000)),
        }

    result = run(config)
    print(json.dumps(result, indent=2))
