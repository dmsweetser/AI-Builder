"""Agent Engine - the main orchestrator."""

import os
import re
import json
import logging
import time
import uuid
import subprocess
import platform
import sys
import threading as _threading
from typing import Any, Dict, List, Tuple, Optional
from agent_engine.config import EngineConfig
from agent_engine.security import SecurityError, ToolError, EngineError
from agent_engine.tools import get_registry
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


def _write_step_file(output_dir: str, step_num: int, step_data: Dict[str, Any]) -> None:
    """Atomically write a step record to steps/NNN.json.

    Creates the steps/ subdirectory if needed. Uses a temp file + atomic
    rename so readers never see a half-written file.
    """
    steps_dir = os.path.join(output_dir, "steps")
    os.makedirs(steps_dir, exist_ok=True)
    # Zero-padded step number for natural sort order
    step_file = os.path.join(steps_dir, f"{step_num:04d}.json")
    tmp_file = step_file + ".tmp"
    try:
        with open(tmp_file, 'w', encoding='utf-8') as f:
            json.dump(step_data, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_file, step_file)
    except Exception as e:
        logging.warning(f"Failed to write step file {step_file}: {e}")


def _write_status_file(output_dir: str, status_data: Dict[str, Any]) -> None:
    """Atomically write status.json in the output directory."""
    status_file = os.path.join(output_dir, "status.json")
    tmp_file = status_file + ".tmp"
    try:
        with open(tmp_file, 'w', encoding='utf-8') as f:
            json.dump(status_data, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_file, status_file)
    except Exception as e:
        logging.warning(f"Failed to write status file {status_file}: {e}")


def _init_status_file(output_dir: str) -> None:
    """Create an initial status.json for a new run."""
    _write_status_file(output_dir, {
        "status": "running",
        "step": 0,
        "timestamp": time.time(),
    })


class LLMClient:
    """Interface for calling the LLM (OpenAI-compatible endpoint)."""

    MAX_RETRIES = 3
    BASE_DELAY = 2.0  # seconds
    MAX_CALL_TIME = 7200  # seconds - hard timeout per LLM call

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
            "raw_request": full_request_json,
            "raw_response": content,
        }


# ====================================================================
# Prefixed marker system
# ====================================================================

def _prefixed_markers(prefix: str = "") -> Dict[str, str]:
    """Return a dict of marker_name → prefixed_marker for the given prefix.

    When prefix is set, ALL tool format markers are prefixed so that the agent
    cannot match unprefixed markers in source code it reads during review.
    """
    if prefix:
        return {
            "TOOL_START": f"[{prefix}_TOOL_START]",
            "TOOL_END": f"[{prefix}_TOOL_END]",
            "TOOL_NAME": f"[{prefix}_TOOL_NAME]",
            "PARAM_NAME": f"[{prefix}_PARAM_NAME]",
            "PARAM_VALUE": f"[{prefix}_PARAM_VALUE]",
            "PARAM_END": f"[{prefix}_PARAM_END]",
            "RATIONALE": f"[{prefix}_RATIONALE]",
        }
    return {
        "TOOL_START": "[TOOL_START]",
        "TOOL_END": "[TOOL_END]",
        "TOOL_NAME": "[TOOL_NAME]",
        "PARAM_NAME": "[PARAM_NAME]",
        "PARAM_VALUE": "[PARAM_VALUE]",
        "PARAM_END": "[PARAM_END]",
        "RATIONALE": "[RATIONALE]",
    }


def _marker(prefix: str, key: str) -> str:
    """Get a single prefixed marker string."""
    return _prefixed_markers(prefix).get(key, key)


def build_system_prompt(tools: List[Dict[str, Any]], instance_prefix: str = "") -> str:
    """Build the system prompt that defines the agentic workflow.

    Args:
        tools: List of tool definitions from the registry.
        instance_prefix: Optional prefix. When set, ALL tool format markers
            ([TOOL_START], [TOOL_NAME], [PARAM_NAME], [PARAM_VALUE], etc.)
            and tool names are prefixed so the agent cannot match unprefixed
            markers in source code it reads during review.
    """
    m = _marker(instance_prefix, "TOOL_START")
    m_end = _marker(instance_prefix, "TOOL_END")
    m_name = _marker(instance_prefix, "TOOL_NAME")
    m_pname = _marker(instance_prefix, "PARAM_NAME")
    m_pval = _marker(instance_prefix, "PARAM_VALUE")
    m_rat = _marker(instance_prefix, "RATIONALE")

    tool_defs = ""
    for t in tools:
        tool_name = t['name']
        if instance_prefix:
            tool_name = f"{instance_prefix}_{tool_name}"
        tool_defs += f"\n  - {tool_name}: {t['description']}"
        if t.get('parameters'):
            tool_defs += "\n    Required parameters:"
            for pk, pv in t['parameters'].items():
                tool_defs += f"\n      - {pk}: {pv}"

    example_block = (
        f"{m}\n"
        f"{m_name}\n"
        "write_file\n"
        f"{m_pname}\n"
        "path\n"
        f"{m_pval}\n"
        "src/hello.py\n"
        f"{m_pname}\n"
        "content\n"
        f"{m_pval}\n"
        '\"\"\"Hello module.\"\"\"\n'
        "from src.main import greet\n"
        "\n"
        'if __name__ == "__main__":\n'
        '    print(greet("World"))\n'
        f"{m_rat}\n"
        "Writing the entry point file with the greet function import.\n"
        f"{m_end}"
    )

    return f'''You are an expert code engineer working inside a bounded tool environment.
You NEVER execute code directly. You ONLY use the tools below to explore, read, modify, and verify code.

AVAILABLE TOOLS:{tool_defs}

WORKFLOW:
1. EXPLORE: Use list_directory, search_files, and grep_code to understand the project structure.
2. UNDERSTAND: Use read_file and find_symbol to inspect relevant code.
3. PLAN: Decide what changes are needed. For large codebases, focus on specific files.
4. MODIFY: Use write_file (new files), edit_file (targeted changes), or delete_file.
5. VERIFY: Use check_syntax to validate your changes before moving on.
6. ITERATE: If syntax errors or issues are found, fix them. Repeat until done.
7. COMPLETE: When all work is done, use the task_completed tool to signal completion.

COMPLETION (CRITICAL - READ CAREFULLY):
- The ONLY way to conclude a run is to use the task_completed tool.
- When you have finished all the work described in the task instructions, call task_completed with a summary of all changes made.
- The run will IMMEDIATELY stop after task_completed is executed - no further tool calls will be made.
- Do NOT use task_completed until you have actually used tools and made changes. You must take at least one tool action before completing.
- If you are unsure whether the task is complete, review the task instructions and verify all requirements are met.
- Once you call task_completed, the run is OVER. Do not make any additional tool calls after it.

CRITICAL: You MUST take at least one tool call before using task_completed. You cannot complete the task without using tools.

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
- When done, use the task_completed tool with a summary of all changes made.
- To create a new tool, use create_tool. It proposes the tool for user approval - it does NOT execute arbitrary code. Wait for user approval in the live feed before expecting the tool to be available. The tool code must define a class that inherits from BaseTool with name, description, parameters, and an execute(params) method.
- If the user asks you to do something you CANNOT do with the currently available tools (e.g., run a shell command, execute a script, make an HTTP request, compile code, run tests, use a specific CLI tool), you SHOULD create a tool to do it. Use create_tool to propose a Python tool that implements the requested functionality, then wait for approval. Do NOT give up, do NOT say you cannot do it, and do NOT just write a script and stop — create a proper tool so the functionality is reusable.
- Use respond_to_user to communicate findings, status updates, or questions to the user.
- Use request_user_input when you need clarification or a decision before proceeding.

TRUNCATION HANDLING:
- Tool results may be truncated if they exceed the configured max length (default 5000 chars).
- If a result says [TRUNCATED], the output was cut off. You should retry with more specific parameters.

PARAMETER FORMAT (tag-based, NO EXCEPTIONS):
- Your ENTIRE response MUST be exactly ONE of the following:
  1. A single tool call block using {m}...{m_end}
  2. A final completion: {m_name}
     task_completed
     {m_pname}
     summary
     {m_pval}
     <your summary here>
     {m_end}
- You are FORBIDDEN from writing any other text outside of tool call blocks.
- Do NOT write any reasoning, thinking, or explanation text.
- Do NOT write "I will..." or "Let me..." or any natural language.
- Do NOT explain what you are about to do - just DO it with a tool call.

The EXACT format for a tool call is:

{m}
{m_name}
the tool name here
{m_pname}
the first parameter key
{m_pval}
the first parameter value
{m_pname}
the second parameter key
{m_pval}
the second parameter value
{m_rat}
(optional) Explain why you are making this tool call - your reasoning, strategy, or what you expect to happen. This helps the user understand your thought process.
{m_end}

Rules for the format:
- {m} and {m_end} wrap the entire tool call
- {m_name} appears once, right after {m}, followed by the tool name on the next line
- Each parameter uses exactly two tags: {m_pname} followed by the key, then {m_pval} followed by the value
- {m_rat} is optional and can appear after all parameters, before {m_end}. It contains your reasoning for the tool call.
- Values may span multiple lines between {m_pval} and the next {m_pname} or {m_end}
- You MUST include both {m} and {m_end}
- Make exactly ONE tool call per response

Example:
{example_block}

RESPONSE FORMAT:
After each tool result, your ENTIRE response must be exactly one of:
1. A tool call block (see PARAMETER FORMAT above) - nothing else
2. A task_completed tool call with a summary of all changes made

You are NOT allowed to write any text outside of tool call blocks.
Any text outside these formats will be ignored.

CRITICAL: task_completed is the FINAL tool call. Once you call task_completed, the run ends immediately. Do not make any additional tool calls after task_completed.

CRITICAL: Make EXACTLY ONE tool call per response. Do not include multiple tool call blocks. If you include more than one {m}...{m_end} block, only the FIRST one will be executed - the rest will be ignored as invalid output.

IMPORTANT: You are bounded to the project root directory by default. All file paths are relative to it.
You CANNOT read or write files outside the project root unless the task instructions explicitly specify an absolute path (e.g., /tmp/something.py).
When the instructions specify an absolute path, use it directly.

TOOL APPROVAL:
When you use the create_tool to propose a new tool, you MUST wait for user approval before using it.
After calling create_tool, do NOT call the new tool in the same response. Wait for the user to approve it in the UI.
If the tool is approved, it will appear in the tool selector. You can then use it in subsequent steps.
If the tool is rejected, do not use it. Choose a different approach or use existing tools.
You will see a "PENDING TOOL APPROVAL" message in the live feed while waiting for user review.

TOOL FAILURE HANDLING (CRITICAL - READ CAREFULLY):
- Every tool result includes a "success" field: true means the tool worked, false means it failed.
- When success is false, the "error" field contains the specific reason for failure.
- If a tool fails, you MUST retry with a corrected approach. Do NOT ignore the error and continue.
- For write_file/edit_file failures: re-read the file first to get the current content, then retry with the correct original text.
- For edit_file failures: the error will show what was expected vs what was found — use that to adjust your original_text or try a different strategy.
- For create_tool failures: fix the code or parameters based on the error message and retry.
- For delete_file failures: verify the file exists and is not a backup file before retrying.
- If a tool fails 3+ times with the same error, try a completely different approach rather than repeating the same call.
- NEVER proceed as if a failed tool succeeded. Always address the error before moving on.

CONTEXT MANAGEMENT:
'''


def build_user_prompt(instructions: str, context: str = "", instance_prefix: str = "") -> str:
    """Build the initial user prompt with the task instructions."""
    m = _marker(instance_prefix, "TOOL_START")
    m_end = _marker(instance_prefix, "TOOL_END")
    m_name = _marker(instance_prefix, "TOOL_NAME")
    m_pname = _marker(instance_prefix, "PARAM_NAME")
    m_pval = _marker(instance_prefix, "PARAM_VALUE")
    prompt = f"""TASK INSTRUCTIONS:
{instructions}

CRITICAL INSTRUCTIONS:
1. You MUST use a tool call to take action. Do NOT just talk about what you will do.
2. Your FIRST action MUST be: list_directory with path="."
3. Do NOT use task_completed until you have actually used tools and gathered information.
4. Your ENTIRE response must be ONLY a tool call block or a task_completed tool call. No other text.
5. Format your tool call EXACTLY like this example:

{m}
{m_name}
list_directory
{m_pname}
path
{m_pval}
.
{m_end}

STEP 1: Use list_directory to explore the project structure. Do NOT use task_completed yet - you must take action first."""
    if context:
        prompt += f"\n\nRELEVANT CONTEXT:\n{context}"
    return prompt


def _strip_code_blocks(response: str) -> str:
    """Strip fenced code blocks (```...```) and inline code (`...`) from response.

    Prevents the parser from extracting tool call blocks that appear inside
    code examples in the LLM's response.
    """
    # Strip fenced code blocks: ```...```
    result = re.sub(r'```[\s\S]*?```', '', response)
    # Strip inline code: `...`
    result = re.sub(r'`[^`]*`', '', result)
    return result


def parse_tool_calls(response: str, prefix: str = "") -> List[Tuple[str, Dict[str, str], Optional[str]]]:
    """Parse tool calls from LLM response using the simplified tag-based format.

    Format (standard, when no prefix):
        [TOOL_START]
        [TOOL_NAME]
        write_file
        [PARAM_NAME]
        path
        [PARAM_VALUE]
        .
        [TOOL_END]

    Format (prefixed, when instance_prefix is set):
        [<prefix>_TOOL_START]
        [<prefix>_TOOL_NAME]
        write_file
        [<prefix>_PARAM_NAME]
        path
        [<prefix>_PARAM_VALUE]
        .
        [<prefix>_TOOL_END]
    """
    # Strip code blocks before parsing
    response = _strip_code_blocks(response)

    # Get the markers for this instance
    markers = _prefixed_markers(prefix)
    m_start = markers["TOOL_START"]
    m_end = markers["TOOL_END"]
    m_name = markers["TOOL_NAME"]
    m_pname = markers["PARAM_NAME"]
    m_pval = markers["PARAM_VALUE"]
    m_pend = markers["PARAM_END"]
    m_rat = markers["RATIONALE"]

    # Normalize LLM quirks: treat [PARAM_END] (or prefixed) as [TOOL_END]
    normalized = response.replace(m_pend, m_end)

    # Build regex patterns using the actual marker strings
    # Standard pattern: [TOOL_START]...[TOOL_NAME]\nname\n...[TOOL_END]
    tool_pattern = re.escape(m_start) + r'\s*' + re.escape(m_name) + r'\s*\n(.*?)\n(.*?)' + re.escape(m_end)

    tool_matches = list(re.finditer(tool_pattern, normalized, re.DOTALL))

    calls = []

    def _process_match(tool_name: str, params_block: str):
        tool_name = tool_name.strip()
        # Reject tool names that look like parameter/rationale markers
        # Check both bracketed and unbracketed forms
        marker_names = (m_pname, m_pval, m_rat, m_end, m_name,
                        m_pname.strip('[]'), m_pval.strip('[]'),
                        m_rat.strip('[]'), m_end.strip('[]'), m_name.strip('[]'))
        if tool_name in marker_names:
            return
        rationale = _extract_rationale(params_block, m_rat, m_end)
        params_block = re.sub(re.escape(m_rat) + r'.*?$', '', params_block, flags=re.DOTALL)
        params = _parse_params(params_block, m_pname, m_pval, m_end)
        if tool_name and params is not None:
            # Strip instance prefix if present
            if prefix and tool_name.startswith(prefix + '_'):
                tool_name = tool_name[len(prefix) + 1:]
            calls.append((tool_name, params, rationale))
        elif tool_name and params is None:
            # Tool with no parameters (with or without rationale) — still valid.
            # _parse_params returns None for an empty params_block; treat it
            # as an empty dict so tools like list_directory with no required
            # params are not silently dropped.
            if prefix and tool_name.startswith(prefix + '_'):
                tool_name = tool_name[len(prefix) + 1:]
            calls.append((tool_name, {}, rationale))

    # Prefer standard matches; fall back to alt matches if no standard matches found
    if tool_matches:
        for match in tool_matches:
            tool_name = match.group(1).strip()
            params_block = match.group(2)
            _process_match(tool_name, params_block)

    return calls


def _extract_rationale(params_block: str, rationale_marker: str = "[RATIONALE]", end_marker: str = "[TOOL_END]") -> Optional[str]:
    """Extract [RATIONALE] block from params if present."""
    rationale_match = re.search(
        re.escape(rationale_marker) + r'\s*\n(.*?)(?=' + re.escape(end_marker) + r'|\[TOOL_NAME\]|\Z)',
        params_block,
        re.DOTALL
    )
    if rationale_match:
        rationale = rationale_match.group(1).strip()
        if rationale:
            return rationale
    return None


def _parse_params(params_block: str, pname_marker: str = "[PARAM_NAME]",
                  pval_marker: str = "[PARAM_VALUE]", end_marker: str = "[TOOL_END]") -> Optional[Dict[str, str]]:
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
    name_pattern = re.escape(pname_marker) + r'\s*\n(.*?)(?=' + re.escape(pval_marker) + r'|' + re.escape(end_marker) + r'|\[TOOL_NAME\]|\Z)'
    value_pattern = re.escape(pval_marker) + r'\s*\n(.*?)(?=' + re.escape(pname_marker) + r'|' + re.escape(end_marker) + r'|\[TOOL_NAME\]|\Z)'

    name_matches = list(re.finditer(name_pattern, params_block, re.DOTALL))
    value_matches = list(re.finditer(value_pattern, params_block, re.DOTALL))

    if len(name_matches) != len(value_matches):
        # Fallback: try a simpler approach - just grab everything between tags
        # Split by [PARAM_NAME] and [PARAM_VALUE] tags
        parts = re.split(r'(' + re.escape(pname_marker) + r'|' + re.escape(pval_marker) + r')', params_block)
        if len(parts) >= 4:
            i = 0
            while i < len(parts) - 2:
                if parts[i].strip() == pname_marker:
                    key = parts[i+1].strip() if i+1 < len(parts) else ''
                    if i+2 < len(parts) and parts[i+2].strip() == pval_marker:
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


def is_done(response: str, prefix: str = "") -> Tuple[bool, str]:
    """Check if the LLM has indicated completion via task_completed tool call.

    Args:
        response: The LLM response text (raw, with tool blocks).
        prefix: Optional instance prefix. If set, also checks for
                <prefix>_task_completed as the completion signal.
    """
    markers = _prefixed_markers(prefix)
    m_start = markers["TOOL_START"]
    m_end = markers["TOOL_END"]
    m_name = markers["TOOL_NAME"]
    m_pval = markers["PARAM_VALUE"]

    # Build the task_completed name(s) to look for
    task_names = ["task_completed"]
    if prefix:
        task_names.append(f"{prefix}_task_completed")

    for task_name in task_names:
        task_match = re.search(
            re.escape(m_start) + r'.*?' + re.escape(m_name) + r'\s*' + re.escape(task_name) + r'\s.*?' + re.escape(m_end),
            response,
            flags=re.DOTALL,
        )
        if task_match:
            # Extract the summary from the task_completed tool call
            summary_match = re.search(
                re.escape(m_pval) + r'\s*(.*?)\s*' + re.escape(m_end),
                task_match.group(0),
                re.DOTALL,
            )
            if summary_match:
                return True, summary_match.group(1).strip()
    return False, ""


# ====================================================================
# File locking utility (pure Python — no platform-specific imports)
# ====================================================================

class FileLock:
    """Simple file-based lock for preventing concurrent writes.

    Uses a lock file + atomic rename. Works on all platforms
    (no fcntl/msvcrt dependency).
    """

    def __init__(self, lock_path: str, timeout: float = 30.0):
        self.lock_path = lock_path + ".lock"
        self.timeout = timeout
        self._lock_file = None

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, *args):
        self.release()

    def acquire(self):
        """Acquire the lock (blocking with timeout)."""
        import time as _time
        deadline = _time.time() + self.timeout
        while True:
            try:
                # Try to create the lock file atomically
                tmp_path = self.lock_path + ".tmp"
                with open(tmp_path, 'w') as f:
                    f.write(str(os.getpid()))
                os.replace(tmp_path, self.lock_path)
                self._lock_file = open(self.lock_path, 'r')
                return
            except (OSError, IOError):
                if _time.time() >= deadline:
                    # Clean up any stale lock file
                    try:
                        os.remove(self.lock_path)
                    except OSError:
                        pass
                    raise TimeoutError(
                        f"Could not acquire lock on {self.lock_path} "
                        f"within {self.timeout}s"
                    )
                _time.sleep(0.05)

    def release(self):
        """Release the lock."""
        if self._lock_file:
            try:
                self._lock_file.close()
            except OSError:
                pass
            finally:
                self._lock_file = None
            try:
                os.remove(self.lock_path)
            except OSError:
                pass


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
    5. Repeat until task_completed or max_steps reached
    """

    def __init__(self, project_config: Dict[str, Any], output_dir: Optional[str] = None,
                 step_callback=None, stop_event: Optional[_threading.Event] = None):
        self.project_config = project_config
        self.root_dir = project_config.get("rootDirectory", EngineConfig.get_root_directory())
        self.instructions = project_config.get("instructions", "")
        self.job_id = project_config.get("job_id", str(int(time.time() * 1000)))

        # Generate a unique instance prefix for this agent run using epoch ticks.
        # This prefix is prepended to ALL tool format markers ([TOOL_START],
        # [TOOL_NAME], [PARAM_NAME], [PARAM_VALUE], etc.) and tool names.
        # When the agent reads its own source code, tool call blocks in the code
        # use unprefixed markers (e.g. [TOOL_NAME]\nlist_directory), so the parser
        # won't extract them as tool calls because it expects the prefixed form
        # (e.g. [<prefix>_TOOL_NAME]\nlist_directory). This prevents the agent from
        # executing its own tool call syntax when reviewing/creating code.
        self.instance_prefix = f"{int(time.time() * 1000000) % 100000000:08d}"

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

        # --- Initialize persistent step files ---
        _init_status_file(self.output_dir)

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

        # Use the shared singleton ToolRegistry - all engines share the same
        # tool list, so newly-approved tools are instantly available.
        self.tools = get_registry(self.root_dir)
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
        self.system_prompt = build_system_prompt(
            self.tools.list_tools(
                project_output_dir=self.output_dir,
                disabled_tools=set(self.project_config.get("disabled_tools", [])),
            ),
            self.instance_prefix,
        )
        self.messages.append({"role": "system", "content": self.system_prompt})

        # Results tracking
        self.step_count = 0
        self.max_steps = EngineConfig.get_max_steps()
        self.step_history: List[Dict[str, Any]] = []

        # Callback for real-time event streaming (called from worker thread)
        self._step_callback = step_callback

        # Context management: manual compression prompt when context is large
        # Removed auto-compression; user now manually triggers compress_context tool
        self._context_warning_shown = False

        # Stop signal from the UI (set by /api/queue/running/stop)
        self._stop_event = stop_event

        # Allow user to continue after max_steps
        self._continue_requested = False

    def _deterministic_compress_context(self):
        """Deterministically compress context by removing low-value items.

        Instead of asking the LLM to summarize, we:
        1. Identify low-value messages (old list_directory, old file reads)
        2. Group consecutive low-value items
        3. Replace each group with a compact summary
        4. Keep high-value items (recent tool results, important context)

        This preserves key information while freeing up context space.
        """
        # Find tool result messages (user messages with [TOOL_RESULT]...)
        tool_results = []
        for i, msg in enumerate(self.messages):
            if msg.get("role") == "user":
                content = msg.get("content", "")
                if "[TOOL_RESULT]" in content:
                    tool_results.append(i)

        if len(tool_results) <= 10:
            # Not enough tool results to compress
            return

        # Identify which tool results are "low value" for removal:
        # - list_directory results (unless very recent)
        # - read_file results for files that are no longer being edited
        # - search_files/grep_code results (unless very recent)
        # We keep the last 10 tool results regardless of type

        low_value_indices = []
        keep_count = 10  # Always keep the last 10 tool results

        for idx in tool_results:
            # Extract tool name from the result
            content = self.messages[idx].get("content", "")
            try:
                import json as _json
                result_data = _json.loads(content)
                step_data = result_data.get("result", {})
                if isinstance(step_data, str):
                    step_data = _json.loads(step_data)
                tool_name = step_data.get("tool", "")
                was_truncated = step_data.get("truncated", False)
            except (json.JSONDecodeError, KeyError, TypeError):
                tool_name = ""
                was_truncated = False

            # Determine if this is a low-value tool result
            is_low_value = False
            if tool_name in ("list_directory", "list_directory_deep"):
                is_low_value = True
            elif tool_name in ("search_files", "search_files_dir", "grep_code", "grep_code_dir"):
                is_low_value = True
            elif tool_name == "read_file":
                # Read results are somewhat valuable, but old ones can be compressed
                is_low_value = True
            elif tool_name == "check_syntax":
                is_low_value = True

            # Never compress if the result was truncated (important context)
            if was_truncated:
                is_low_value = False

            # Mark for removal if it's low-value and not in the last 3
            if is_low_value and len(low_value_indices) < (len(tool_results) - keep_count):
                low_value_indices.append(idx)

        if not low_value_indices:
            return

        # Group consecutive low-value indices and replace each group
        groups = []
        current_group = [low_value_indices[0]]

        for i in range(1, len(low_value_indices)):
            if low_value_indices[i] == low_value_indices[i - 1] + 1:
                current_group.append(low_value_indices[i])
            else:
                groups.append(current_group)
                current_group = [low_value_indices[i]]
        groups.append(current_group)

        # Replace each group with a compact summary
        for group in groups:
            if not group:
                continue

            first_idx = group[0]
            last_idx = group[-1]

            # Count how many items were removed
            removed_count = len(group)

            # Build a summary of what was removed
            removed_tools = []
            for idx in group:
                content = self.messages[idx].get("content", "")
                try:
                    import json as _json
                    result_data = _json.loads(content)
                    step_data = result_data.get("result", {})
                    if isinstance(step_data, str):
                        step_data = _json.loads(step_data)
                    tool_name = step_data.get("tool", "unknown")
                    removed_tools.append(tool_name)
                except (json.JSONDecodeError, KeyError, TypeError):
                    removed_tools.append("unknown")

            # Count total tokens removed
            tokens_removed = sum(
                _estimate_tokens(self.messages[idx].get("content", ""))
                for idx in group
            )

            # Create the replacement message
            # Also remove the corresponding assistant messages (LLM responses)
            # that precede these tool results
            assistant_indices_to_remove = []
            for idx in group:
                # Look for the assistant message before this tool result
                for j in range(idx - 1, max(0, idx - 5), -1):
                    if self.messages[j].get("role") == "assistant":
                        assistant_indices_to_remove.append(j)
                        break

            # Remove duplicates and sort
            assistant_indices_to_remove = sorted(set(assistant_indices_to_remove), reverse=True)

            # Build the summary message
            tool_counts = {}
            for t in removed_tools:
                tool_counts[t] = tool_counts.get(t, 0) + 1

            summary_parts = []
            for tool_name, count in sorted(tool_counts.items()):
                summary_parts.append(f"  - {tool_name}: {count} result(s)")

            summary = (
                f"[COMPRESSED] Removed {removed_count} low-value tool result(s) "
                f"({tokens_removed} tokens) for brevity:\n"
                + "\n".join(summary_parts) +
                f"\n[Removed {removed_count} tool result(s), {tokens_removed} tokens]"
            )

            # Replace the first tool result with the summary
            self.messages[first_idx] = {
                "role": "user",
                "content": summary,
            }

            # Remove the rest of the tool results in this group
            for idx in reversed(group[1:]):
                self.messages.pop(idx)

            # Remove the corresponding assistant messages
            for idx in assistant_indices_to_remove:
                if idx < len(self.messages):
                    self.messages.pop(idx)

        self.logger.info(
            f"Deterministic context compression: removed {len(low_value_indices)} "
            f"low-value items ({tokens_removed} tokens)"
        )

    def reload_approved_tools(self):
        """Reload project-local tools and rebuild system prompt.

        Call this after tool approval to make newly approved tools
        visible to the LLM without restarting the engine.
        """
        # Reload project-local tools
        self._reload_project_tool_loader()
        self.system_prompt = build_system_prompt(
            self.tools.list_tools(
                project_output_dir=self.output_dir,
                disabled_tools=set(self.project_config.get("disabled_tools", [])),
            ),
            self.instance_prefix,
        )
        # Replace the system prompt message in-place so the LLM sees the
        # updated tool list on the next call.
        if self.messages and self.messages[0].get("role") == "system":
            self.messages[0]["content"] = self.system_prompt

    def _reload_project_tool_loader(self):
        """Reload the project-local tool loader for this project."""
        project_output_dir = self.output_dir
        disabled_tools = set(self.project_config.get("disabled_tools", []))
        self.tools.reload_project_tools(project_output_dir, disabled_tools)

    def _reload_project_settings(self):
        """Reload project settings from disk to pick up live changes.

        Checks if the project file has been modified since last load.
        If so, reloads rootDirectory and instructions.
        (enabled_tools filtering has been removed - all tools are always available.)
        """
        try:
            import json as _json
            # Determine the projects file path
            projects_file = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                "aib_instance", "projects.json"
            )
            # Also check the app-level projects file
            if not os.path.exists(projects_file):
                projects_file = os.path.join(
                    os.path.dirname(os.path.abspath(__file__)),
                    "..", "aib_instance", "projects.json"
                )
            if not os.path.exists(projects_file):
                return

            # Find the project by ID in the projects file
            project_id = self.project_config.get("id")
            if not project_id:
                return

            with open(projects_file, 'r', encoding='utf-8') as f:
                projects = _json.load(f)

            for p in projects:
                if p.get("id") == project_id:
                    # Check if any relevant settings changed
                    old_root = self.project_config.get("rootDirectory", "")
                    old_instructions = self.project_config.get("instructions", "")

                    new_root = p.get("rootDirectory", "")
                    new_instructions = p.get("instructions", "")

                    if new_root and new_root != old_root:
                        self.root_dir = new_root
                        self.project_config["rootDirectory"] = new_root
                    if new_instructions and new_instructions != old_instructions:
                        self.instructions = new_instructions
                        self.project_config["instructions"] = new_instructions
                    break
        except Exception as e:
            logging.debug(f"Project settings reload check failed (non-critical): {e}")

    def _check_pending_tools(self, emit_once=True):
        """Check for pending tools and emit events / inject reminder for the LLM.

        When there are tools awaiting approval, this:
        1. Emits a ``pending_approval`` event for each (so the UI banner shows).
        2. Injects a user message telling the LLM about the pending tools so it
           can inform the user and wait for approval before proceeding.

        Args:
            emit_once: When True (default), only inject the reminder message
                once per engine instance. When False, always emit events but
                still guard against duplicate reminder messages.
        """
        pending = self.tools.get_project_pending_tools(self.output_dir)
        if not pending:
            return

        # Guard: only inject the message once per engine instance
        if getattr(self, '_pending_tools_message_injected', False):
            # Still emit events even if reminder was already injected
            # (e.g., on resume after tool approval, new tools may have been added)
            for tool in pending:
                tool_name = tool.get("name", "unknown")
                self.logger.info(f"Pending tool detected (re-check): {tool_name}")
                if self._step_callback:
                    try:
                        self._step_callback({
                            "type": "pending_approval",
                            "tool_name": tool_name,
                            "output_dir": self.output_dir,
                        })
                    except Exception:
                        pass
            return

        self._pending_tools_message_injected = True

        # Emit a pending_approval event for each pending tool so the UI shows
        # the approval banner immediately.
        for tool in pending:
            tool_name = tool.get("name", "unknown")
            self.logger.info(f"Pending tool detected: {tool_name}")
            if self._step_callback:
                try:
                    self._step_callback({
                        "type": "pending_approval",
                        "tool_name": tool_name,
                        "output_dir": self.output_dir,
                    })
                except Exception:
                    pass

        # Inject a user message so the LLM knows about pending tools and can
        # inform the user via respond_to_user.  The LLM will wait for approval
        # before trying to use any of these tools.
        tool_names = ", ".join(t.get("name", "?") for t in pending)
        reminder = (
            f"[PENDING TOOL APPROVAL] There are {len(pending)} tool proposal(s) "
            f"awaiting your review: {tool_names}.\n\n"
            f"Please review and approve or reject them in the TOOLS tab.\n"
            f"Do NOT attempt to use any of these tools until they are approved.\n"
            f"Use respond_to_user to inform the user about these pending tools.\n"
        )
        self.messages.append({
            "role": "user",
            "content": reminder,
        })

    def _persist_step(self, step_num: int, step_data: Dict[str, Any]) -> None:
        """Write a step record to disk (file-based persistence) AND emit via callback."""
        # Write to persistent file
        _write_step_file(self.output_dir, step_num, step_data)
        # Also update the legacy steps.jsonl for backward compat
        try:
            with open(self.step_log_file, 'a', encoding='utf-8') as f:
                f.write(json.dumps(step_data, ensure_ascii=False) + '\n')
        except Exception:
            pass

    def _update_status(self, status: str, **extra) -> None:
        """Update status.json with the current status."""
        status_data = {
            "status": status,
            "step": self.step_count,
            "timestamp": time.time(),
        }
        status_data.update(extra)
        _write_status_file(self.output_dir, status_data)

    def run(self) -> Dict[str, Any]:
        """Execute the agentic revision loop."""
        # Reload approved tools so any tools approved since the last run
        # are visible to the LLM immediately.
        self.reload_approved_tools()

        # Check for pending tools and notify the UI / LLM
        self._check_pending_tools()

        self.logger.info(f"Starting agentic engine for: {self.root_dir}")
        self.logger.info(f"Instructions: {self.instructions}...")

        try:
            # Build initial prompt
            user_prompt = build_user_prompt(self.instructions, instance_prefix=self.instance_prefix)
            self.messages.append({"role": "user", "content": user_prompt})

            # Main loop
            final_summary = ""
            while self.step_count < self.max_steps or self._continue_requested:
                # Check if the user requested a stop
                if self._stop_event and self._stop_event.is_set():
                    self.logger.info("Engine stop requested by user.")
                    self._update_status("stopped")
                    return {
                        "status": "stopped",
                        "steps": self.step_count,
                        "summary": final_summary,
                        "max_steps": self.max_steps,
                        "step_history": self.step_history,
                    }
                if self.step_count >= self.max_steps and not self._continue_requested:
                    self.logger.info("Max steps reached. Waiting for user continuation.")
                    self._update_status("max_steps_reached")
                    return {
                        "status": "max_steps_reached",
                        "steps": self.step_count,
                        "summary": final_summary,
                        "max_steps": self.max_steps,
                        "step_history": self.step_history,
                    }

                self.step_count += 1
                self.logger.info(f"Step {self.step_count}/{self.max_steps}")

                # Check for tool approval resume signal (written by approval endpoint)
                # If a tool was approved while the engine was paused, the engine
                # needs to know to continue its loop and use the new tool.
                tool_approved_file = os.path.join(self.output_dir, "_tool_approved_resume.txt")
                if os.path.exists(tool_approved_file):
                    try:
                        approved_tool = open(tool_approved_file, 'r').read().strip()
                        os.remove(tool_approved_file)
                        self.logger.info(f"Tool approval resume detected - approved tool: {approved_tool}")
                        # Reload approved tools to ensure the new tool is in the registry
                        self.reload_approved_tools()
                    except Exception:
                        pass

                # State-based pending tool check: at the top of each loop iteration,
                # check if there are any tools in the pending folder. This replaces
                # the signal-file approach and is more reliable/idempotent — it checks
                # the actual filesystem state rather than relying on a transient file.
                self._check_pending_tools()

                # Check for live instructions injected mid-run
                live_instruction = EngineConfig.get_live_instruction(
                    self.job_id, base_dir=self.output_dir
                )
                if live_instruction:
                    self.logger.info(f"Received live instruction: {live_instruction}...")
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

                # Check for resume input (user response to request_user_input)
                resume_input = EngineConfig.get_resume_input(
                    self.job_id, base_dir=self.output_dir
                )
                if resume_input:
                    self.logger.info(f"Received resume input: {resume_input}...")
                    self.messages.append({
                        "role": "user",
                        "content": (
                            f"========== USER RESPONSE ==========\n"
                            f"{resume_input}\n"
                            "========== END USER RESPONSE ==========\n\n"
                            "Use this response to continue your task. "
                            "Respond with EXACTLY ONE tool call."
                        )
                    })

                # Check if context is getting large - apply deterministic compression
                if (not self._context_warning_shown and
                    self.max_context_tokens > 0):
                    current_tokens = sum(_estimate_tokens(m.get("content", "")) for m in self.messages)
                    usage_pct = current_tokens / self.max_context_tokens if self.max_context_tokens > 0 else 0
                    if usage_pct >= 0.5:
                        # Emit context warning event for UI
                        if self._step_callback:
                            try:
                                self._step_callback({
                                    "type": "context_warning",
                                    "step": self.step_count,
                                    "current_tokens": current_tokens,
                                    "max_tokens": self.max_context_tokens,
                                    "usage_pct": round(usage_pct * 100, 1),
                                })
                            except Exception:
                                pass
                        self._context_warning_shown = True

                        # Apply deterministic context compression
                        self._deterministic_compress_context()
                        self.logger.info(
                            f"Context compression triggered at step {self.step_count}, "
                            f"context at {round(usage_pct * 100, 1)}% of max"
                        )

                        # Add a user message explaining the compression
                        self.messages.append({
                            "role": "user",
                            "content": (
                                f"[CONTEXT COMPRESSED] Your conversation context was at {round(usage_pct * 100, 1)}% of the context window. "
                                f"Low-value items (old tool results, repetitive outputs) have been removed for brevity. "
                                f"Key information has been preserved. Continue with your task."
                            ),
                        })

                # Call LLM
                # Reload project settings to pick up live changes (instructions,
                # enabled_tools, rootDirectory) before each LLM call.
                self._reload_project_settings()
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
                    # Persist the LLM call step to disk
                    self._persist_step(self.step_count, llm_entry)
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
                    self._update_status("error", error=str(e))
                    return {"status": "error", "error": str(e), "steps": self.step_count}

                # Log response
                with open(self.response_file, 'w', encoding='utf-8') as f:
                    f.write(response)

                # Strip code blocks first to prevent extracting tool calls from
                # code examples embedded in the response.
                cleaned = _strip_code_blocks(response)

                # Strip anything outside valid tool call blocks - only keep
                # [TOOL_START]...[TOOL_END] blocks (or prefixed variants).
                # This keeps conversation history clean and prevents the LLM from
                # seeing its own stray text on subsequent turns.
                m_start = _marker(self.instance_prefix, "TOOL_START")
                m_end = _marker(self.instance_prefix, "TOOL_END")
                tool_blocks = re.findall(
                    re.escape(m_start) + r'.*?' + re.escape(m_end),
                    cleaned,
                    flags=re.DOTALL,
                )
                # Keep only tool blocks (task_completed will be extracted via is_done)
                cleaned_parts = list(tool_blocks)
                cleaned_response = "\n\n".join(cleaned_parts).strip()

                # Parse tool calls FIRST - before checking for task_completed
                tool_calls = parse_tool_calls(cleaned, self.instance_prefix)
                done, summary = is_done(cleaned, self.instance_prefix)

                # If LLM produced tool calls (with or without task_completed):
                #   - Take ONLY the first tool call
                #   - If it's task_completed, CONCLUDE the run immediately
                #   - Otherwise, continue the loop normally
                if tool_calls:
                    tool_calls = [tool_calls[0]]  # Only first tool call

                    # Check if the first tool call is task_completed - this CONCLUDES the run
                    if tool_calls[0][0] == "task_completed":
                        # Extract summary from params
                        task_summary = tool_calls[0][1].get("summary", "Task completed.")
                        # Append cleaned response for history
                        if cleaned_response:
                            self.messages.append({
                                "role": "assistant",
                                "content": cleaned_response,
                            })
                        # Log the tool call
                        self.logger.info(f"  Tool: {tool_calls[0][0]}({json.dumps(tool_calls[0][1])})")
                        step_entry = {
                            "step": self.step_count,
                            "tool": "task_completed",
                            "params": tool_calls[0][1],
                        }
                        if tool_calls[0][2]:
                            step_entry["rationale"] = tool_calls[0][2]
                        # Execute the tool (returns a ToolResult)
                        try:
                            if self._step_callback:
                                try:
                                    self._step_callback({
                                        "type": "tool_start",
                                        "step": self.step_count,
                                        "tool": "task_completed",
                                    })
                                except Exception:
                                    pass
                            result = self.tools.execute("task_completed", tool_calls[0][1], self.root_dir, self.output_dir, set(self.project_config.get("disabled_tools", [])))
                            result_dict = result.to_dict()
                            step_entry["result"] = result_dict
                        except Exception as e:
                            step_entry["result"] = ToolResult(False, "", error=str(e)).to_dict()
                            self.logger.error(f"task_completed execution error: {e}")

                        # Append tool result to messages for history
                        self.messages.append({
                            "role": "user",
                            "content": f"[TOOL_RESULT]\n{json.dumps(step_entry['result'], indent=2)}\n[TOOL_RESULT]",
                        })
                        self.step_history.append(step_entry)
                        # Persist the step to disk
                        self._persist_step(self.step_count, step_entry)
                        if self._step_callback:
                            try:
                                self._step_callback({
                                    "type": "step",
                                    "step": self.step_count,
                                    "tool": "task_completed",
                                    "params": tool_calls[0][1],
                                    "result": step_entry["result"],
                                })
                            except Exception:
                                pass

                        # CONCLUDE THE RUN - task_completed is the final action
                        final_summary = task_summary
                        self.messages.append({
                            "role": "user",
                            "content": f"[COMPLETION]\n{final_summary}",
                        })
                        self.logger.info(f"Agent completed via task_completed: {final_summary}")
                        self._update_status("completed", summary=final_summary)
                        break

                    # Not task_completed - process as regular tool call
                    # Append cleaned response (may be empty or just text)
                    if cleaned_response:
                        self.messages.append({
                            "role": "assistant",
                            "content": cleaned_response,
                        })

                    # Log the first tool call only
                    self.logger.info(f"  Tool: {tool_calls[0][0]}({json.dumps(tool_calls[0][1])})")

                    # Process only the first tool call
                    tool_name, params, rationale = tool_calls[0]
                    step_entry = {
                        "step": self.step_count,
                        "tool": tool_name,
                        "params": params,
                    }
                    if rationale:
                        step_entry["rationale"] = rationale

                    try:
                        # Emit tool_start event before executing
                        if self._step_callback:
                            try:
                                self._step_callback({
                                    "type": "tool_start",
                                    "step": self.step_count,
                                    "tool": tool_name,
                                })
                            except Exception:
                                pass
                        result = self.tools.execute(tool_name, params, self.root_dir, self.output_dir, set(self.project_config.get("disabled_tools", [])))
                        result_dict = result.to_dict()

                        # Truncate tool result content to prevent context overflow.
                        # The LLM can only see the first N characters; if the
                        # result is longer, it gets a notice and guidance on
                        # how to request a narrower query.
                        # NOTE: respond_to_user and request_user_input are NOT
                        # truncated - the user must see the full message.
                        raw_content = result_dict.get("content", "")
                        if (raw_content
                                and self.max_tool_result_length > 0
                                and tool_name not in ("respond_to_user", "request_user_input")):
                            truncated, was_truncated = truncate_tool_result(
                                raw_content, self.max_tool_result_length, tool_name
                            )
                            result_dict["content"] = truncated
                            result_dict["truncated"] = was_truncated
                            if was_truncated:
                                self.logger.info(
                                    f"  Truncated tool '{tool_name}' result: "
                                    f"{len(raw_content)} -> {len(truncated)} chars "
                                    f"(limit: {self.max_tool_result_length})"
                                )
                        step_entry["result"] = result_dict
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
                        # Append the create_tool step to history BEFORE returning
                        # (the normal path appends at line 1610, but create_tool
                        # returns early, so we must do it here to avoid losing it)
                        self.step_history.append(step_entry)
                        # Persist the step to disk
                        self._persist_step(self.step_count, step_entry)
                        if self._step_callback:
                            try:
                                self._step_callback({
                                    "type": "step",
                                    "step": self.step_count,
                                    "tool": tool_name,
                                    "params": params,
                                    "result": step_entry.get("result", {}),
                                })
                            except Exception:
                                pass
                        # Emit pending_approval event for UI
                        if self._step_callback:
                            try:
                                tool_name_val = params.get("name", "unknown")
                                self._step_callback({
                                    "type": "pending_approval",
                                    "tool_name": tool_name_val,
                                    "output_dir": self.output_dir,
                                })
                            except Exception:
                                pass
                        self._update_status("pending_approval")
                        return {
                            "status": "pending_approval",
                            "steps": self.step_count,
                            "summary": summary if done else "Pending tool approval",
                            "max_steps": self.max_steps,
                            "step_history": self.step_history,
                        }

                    # If request_user_input was used, PAUSE the agent for user response
                    if tool_name == "request_user_input":
                        question = params.get("question", "Please provide input:")
                        # Append the step entry to history BEFORE returning
                        self.step_history.append(step_entry)
                        # Persist the step to disk
                        self._persist_step(self.step_count, step_entry)
                        if self._step_callback:
                            try:
                                self._step_callback({
                                    "type": "step",
                                    "step": self.step_count,
                                    "tool": tool_name,
                                    "params": params,
                                    "result": step_entry.get("result", {}),
                                })
                            except Exception:
                                pass
                        # Write the question to a file so the UI can read it
                        os.makedirs(self.output_dir, exist_ok=True)
                        question_file = os.path.join(self.output_dir, "user_input_request.txt")
                        with open(question_file, "w") as f:
                            f.write(question)
                        if self._step_callback:
                            try:
                                self._step_callback({
                                    "type": "pending_user_input",
                                    "step": self.step_count,
                                    "question": question,
                                })
                            except Exception:
                                pass
                        self._update_status("pending_user_input", question=question)
                        return {
                            "status": "pending_user_input",
                            "steps": self.step_count,
                            "summary": f"Waiting for user input: {question}",
                            "max_steps": self.max_steps,
                            "step_history": self.step_history,
                            "question": question,
                        }

                    # Feed tool result back to LLM
                    self.logger.info(
                        f"  Fed tool result for '{tool_name}' back to LLM "
                        f"(msg length: {len(json.dumps(self.messages))} chars)"
                    )
                    # Log directory listing details for debugging
                    if tool_name in ("list_directory", "list_directory_deep"):
                        dir_path = params.get("path", ".")
                        result_content = step_entry.get("result", {}).get("content", "")
                        result_len = len(result_content) if result_content else 0
                        # Extract entry names for quick inspection
                        try:
                            entries = json.loads(result_content) if result_content else []
                            entry_names = [e.get("name", "?") for e in entries]
                            self.logger.info(
                                f"  list_directory step={self.step_count} path='{dir_path}' "
                                f"entries={len(entries)} names={entry_names}"
                            )
                        except json.JSONDecodeError:
                            self.logger.info(
                                f"  list_directory step={self.step_count} path='{dir_path}' "
                                f"result_len={result_len} (not valid JSON)"
                            )
                    self.messages.append({
                        "role": "user",
                        "content": f"[TOOL_RESULT]\n{json.dumps(step_entry['result'], indent=2)}\n[TOOL_RESULT]",
                    })

                    # Log the step
                    self.step_history.append(step_entry)
                    # Persist the step to disk
                    self._persist_step(self.step_count, step_entry)
                    if self._step_callback:
                        try:
                            self._step_callback({
                                "type": "step",
                                "step": self.step_count,
                                "tool": tool_name,
                                "params": params,
                                "result": step_entry["result"],
                            })
                        except Exception:
                            pass

                    # Continue to next step
                    continue

                # No tool calls - check for completion
                if done:
                    final_summary = summary
                    # Add the DONE summary as a user-visible message so it shows up nicely in the UI
                    self.messages.append({
                        "role": "user",
                        "content": f"[COMPLETION]\n{summary}",
                    })
                    self.logger.info(f"Agent completed: {summary}")
                    self._update_status("completed", summary=final_summary)
                    break

                # No tool calls - LLM didn't produce a valid tool call.
                # Inject "Please continue" to nudge it back on track.
                self.logger.warning(
                    f"No tool calls in response (step {self.step_count}). "
                    f"Response preview: {response}"
                )
                # Append the raw response as-is so the LLM can see its own output
                self.messages.append({
                    "role": "assistant",
                    "content": response,
                })
                # Nudge the LLM to take action
                self.messages.append({
                    "role": "user",
                    "content": "Please continue with your next action.",
                })
                self.step_history.append({
                    "step": self.step_count,
                    "tool": "llm_response",
                    "params": {},
                    "result": {"content": response, "success": False, "error": "no_tool_call"},
                })
                # Persist the failed step to disk
                self._persist_step(self.step_count, self.step_history[-1])
                if self._step_callback:
                    try:
                        self._step_callback({
                            "type": "step",
                            "step": self.step_count,
                            "tool": "llm_response",
                            "params": {},
                            "result": {"success": False, "content": "No tool call - LLM continued"},
                        })
                    except Exception:
                        pass
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
            self._update_status("error", error=str(e))
            return {"status": "error", "error": str(e), "steps": self.step_count}

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
