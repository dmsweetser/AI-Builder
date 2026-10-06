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


class LLMClient:
    """Interface for calling the LLM (local or Azure)."""

    def __init__(self):
        self._prompt_file_counter = 0

    def call(self, messages: List[Dict[str, str]], response_file: str = None) -> str:
        if EngineConfig.use_local_model():
            return self._call_local(messages, response_file)
        elif EngineConfig.use_custom_endpoint():
            return self._call_custom_endpoint(messages, response_file)
        else:
            return self._call_azure(messages)

    def _call_local(self, messages: List[Dict[str, str]], response_file: str) -> str:
        model_path = EngineConfig.get_model_path()
        if not model_path:
            raise EngineError("MODEL_PATH not set for local model")

        llama_binary = EngineConfig.get_llama_binary_path()
        if not llama_binary or not os.path.isfile(llama_binary):
            raise EngineError(f"llama binary not found at: {llama_binary}")

        # Write prompt to temp file
        self._prompt_file_counter += 1
        filename = f"aibuilder_prompt_{self._prompt_file_counter}.txt"
        if response_file:
            prompt_dir = os.path.dirname(response_file)
        else:
            prompt_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "aib_instance", "output")
        os.makedirs(prompt_dir, exist_ok=True)
        full_path = os.path.join(prompt_dir, filename)

        # Build llama.cpp prompt from messages
        prompt_text = ""
        for msg in messages:
            role = msg["role"]
            content = msg["content"]
            if role == "system":
                prompt_text += f"<|system|>\n{content}\n<|end|>\n"
            elif role == "user":
                prompt_text += f"<|user|>\n{content}\n<|end|>\n"
            elif role == "assistant":
                prompt_text += f"<|assistant|>\n{content}\n<|end|>\n"

        with open(full_path, "w", encoding='utf-8') as f:
            f.write(prompt_text)

        cmd = [
            llama_binary,
            "-m", model_path,
            "-f", full_path,
            "--temp", str(EngineConfig.get_temperature()),
            "--top-p", str(EngineConfig.get_top_p()),
            "--top-k", str(EngineConfig.get_top_k()),
            "--min-p", str(EngineConfig.get_min_p()),
            "-n", str(EngineConfig.get_output_tokens()),
            "--ctx-size", str(EngineConfig.get_model_context()),
            "--jinja",
            "--no-display-prompt",
            "-st",
        ]

        response_content = ""
        try:
            process = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, bufsize=1
            )
            while True:
                token = process.stdout.read(1)
                if not token:
                    break
                response_content += token
                if response_file and len(response_content) % 100 == 0:
                    with open(response_file, 'w', encoding='utf-8') as rf:
                        rf.write(response_content)
            process.wait()
        finally:
            try:
                os.remove(full_path)
            except OSError:
                pass

        return response_content

    def _call_azure(self, messages: List[Dict[str, str]]) -> str:
        from azure.ai.inference import ChatCompletionsClient
        from azure.ai.inference.models import SystemMessage, UserMessage, AssistantMessage
        from azure.core.credentials import AzureKeyCredential

        endpoint = EngineConfig.get_endpoint()
        model_name = EngineConfig.get_model_name()
        api_key = EngineConfig.get_api_key()

        if not all([endpoint, model_name, api_key]):
            raise EngineError("Missing Azure AI credentials")

        client = ChatCompletionsClient(
            endpoint=endpoint,
            credential=AzureKeyCredential(api_key),
            api_version="2024-05-01-preview",
            connection_verify=EngineConfig.verify_ssl()
        )

        azure_messages = []
        for msg in messages:
            if msg["role"] == "system":
                azure_messages.append(SystemMessage(content=msg["content"]))
            elif msg["role"] == "user":
                azure_messages.append(UserMessage(content=msg["content"]))
            elif msg["role"] == "assistant":
                azure_messages.append(AssistantMessage(content=msg["content"]))

        response = client.complete(
            stream=True,
            messages=azure_messages,
            max_tokens=EngineConfig.get_output_tokens(),
            model=model_name,
        )

        content = ""
        try:
            for update in response:
                if update.choices and len(update.choices) > 0:
                    delta = update.choices[0].get("delta", {})
                    c = delta.get("content")
                    if c:
                        content += c
        finally:
            response.close()

        return content

    def _call_custom_endpoint(self, messages: List[Dict[str, str]], response_file: str) -> str:
        """Call a custom OpenAI-compatible endpoint (Ollama, LM Studio, vLLM, etc.)."""
        import urllib.request
        import ssl

        endpoint_url = EngineConfig.get_custom_endpoint_url()
        api_key = EngineConfig.get_custom_api_key()
        model_name = EngineConfig.get_custom_model_name()

        if not all([endpoint_url, model_name]):
            raise EngineError("Missing custom endpoint credentials: CUSTOM_ENDPOINT_URL and CUSTOM_MODEL_NAME required")

        # Build OpenAI-format messages
        openai_messages = []
        for msg in messages:
            openai_messages.append({
                "role": msg["role"],
                "content": msg["content"],
            })

        payload = {
            "model": model_name,
            "messages": openai_messages,
            "temperature": EngineConfig.get_temperature(),
            "top_p": EngineConfig.get_top_p(),
            "max_tokens": EngineConfig.get_custom_max_tokens(),
            "stream": True,
        }

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
            with urllib.request.urlopen(req, context=context, timeout=300) as response:
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
        except Exception as e:
            raise EngineError(f"Custom endpoint call failed: {e}")

        return content


def build_system_prompt(tools: List[Dict[str, Any]]) -> str:
    """Build the system prompt that defines the agentic workflow."""
    tool_defs = ""
    for t in tools:
        tool_defs += f"\n  - {t['name']}: {t['description']}"
        if t.get('parameters'):
            tool_defs += "\n    Parameters:"
            for pk, pv in t['parameters'].items():
                tool_defs += f" {pk} ({pv})"

    return f"""You are an expert code engineer working inside a bounded tool environment.
You NEVER execute code directly. You ONLY use the tools below to explore, read, modify, and verify code.

AVAILABLE TOOLS:{tool_defs}

WORKFLOW:
1. EXPLORE: Use list_directory, search_files, and grep_code to understand the project structure.
2. UNDERSTAND: Use read_file, find_symbol, and get_file_info to inspect relevant code.
3. PLAN: Decide what changes are needed. For large codebases, focus on specific files.
4. MODIFY: Use write_file (new files), edit_file (targeted changes), or delete_file.
5. VERIFY: Use check_syntax to validate your changes before moving on.
6. ITERATE: If syntax errors or issues are found, fix them. Repeat until done.

RULES:
- ALWAYS use read_file before edit_file to get the exact text to replace.
- ALWAYS use check_syntax after editing to verify correctness.
- Keep edits focused and small - one change at a time.
- For Java projects with JAR dependencies, use decompile_jar to inspect them.
- For large codebases, be selective: grep for relevant code, don't read everything.
- You have a maximum of {EngineConfig.get_max_steps()} steps total. Use them wisely.
- After making changes, verify them. If check_syntax fails, fix the errors.
- When done, respond with: [DONE] followed by a summary of all changes made.

RESPONSE FORMAT:
After each tool result, you will respond with either:
1. A tool call: [TOOL:tool_name{{param1:"value1",param2:"value2"}}]
2. Or a final response: [DONE] Your summary of changes.

You may interleave thinking/reasoning text between tool calls, but tool calls MUST use the exact format above.
Each [TOOL:...] call will be executed and the result will be fed back to you.
You may call multiple tools in one response by listing them on separate lines.

IMPORTANT: You are bounded to the project root directory. All file paths are relative to it.
You CANNOT read or write files outside the project root.
"""


def build_user_prompt(instructions: str, context: str = "") -> str:
    """Build the initial user prompt with the task instructions."""
    prompt = f"TASK INSTRUCTIONS:\n{instructions}\n\n"
    if context:
        prompt += f"RELEVANT CONTEXT:\n{context}\n\n"
    prompt += "Begin by exploring the project structure. Use list_directory to understand the layout."
    return prompt


def parse_tool_calls(response: str) -> List[Tuple[str, Dict[str, str]]]:
    """
    Parse tool calls from LLM response.
    Format: [TOOL:tool_name{param1:"value1",param2:"value2"}]
    Supports optional whitespace around colons/braces and mixed-case tool names.
    Returns list of (tool_name, params_dict) tuples.
    """
    calls = []
    # More permissive: allow optional whitespace around ':', '{', '}',
    # and support hyphens in tool names
    pattern = r'\[TOOL:\s*([a-zA-Z_][a-zA-Z0-9_-]*)\s*\{([^}]*)\}\s*\]'
    for match in re.finditer(pattern, response):
        tool_name = match.group(1)
        params_str = match.group(2)

        params = {}
        for pm in re.finditer(r'(\w+)\s*:\s*"([^"]*)"', params_str):
            params[pm.group(1)] = pm.group(2)

        calls.append((tool_name, params))

    return calls


def is_done(response: str) -> Tuple[bool, str]:
    """Check if the LLM has indicated completion."""
    match = re.search(r'\[DONE\]\s*(.*)', response, re.DOTALL)
    if match:
        return True, match.group(1).strip()
    return False, ""


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

    def __init__(self, project_config: Dict[str, Any]):
        self.project_config = project_config
        self.root_dir = project_config.get("rootDirectory", EngineConfig.get_root_directory())
        self.instructions = project_config.get("instructions", "")
        self.job_id = project_config.get("job_id", str(int(time.time() * 1000)))
        self.output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                        "aib_instance", "output",
                                        self.job_id)
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
        enabled_tools = EngineConfig.get_enabled_tools()
        self.tools = ToolRegistry(self.root_dir, enabled_tools=enabled_tools)
        self.llm = LLMClient()

        # Conversation history
        self.messages: List[Dict[str, str]] = []
        self.system_prompt = build_system_prompt(self.tools.list_tools())
        self.messages.append({"role": "system", "content": self.system_prompt})

        # Results tracking
        self.step_count = 0
        self.max_steps = EngineConfig.get_max_steps()
        self.step_history: List[Dict[str, Any]] = []
        self._recent_tool_calls: List[str] = []  # Track recent tool names for loop detection

    def run(self) -> Dict[str, Any]:
        """Execute the agentic revision loop."""
        self.logger.info(f"Starting agentic engine for: {self.root_dir}")
        self.logger.info(f"Instructions: {self.instructions[:200]}...")

        # Run pre-script if configured
        pre_script = EngineConfig.get_pre_script()
        if pre_script:
            self._run_script("pre", pre_script)

        try:
            # Build initial prompt
            user_prompt = build_user_prompt(self.instructions)
            self.messages.append({"role": "user", "content": user_prompt})

            # Main loop
            final_summary = ""
            while self.step_count < self.max_steps:
                self.step_count += 1
                self.logger.info(f"Step {self.step_count}/{self.max_steps}")

                # Check for live instructions injected mid-run
                live_instruction = EngineConfig.get_live_instruction(self.job_id)
                if live_instruction:
                    self.logger.info(f"Received live instruction: {live_instruction[:100]}...")
                    self.messages.append({
                        "role": "system",
                        "content": f"[LIVE INJECTION] User has sent new instructions: {live_instruction}\n\nConsider this as an update to your task. You may need to adjust your approach or add to what you're doing.\n\nContinue with your next action."
                    })

                # Call LLM
                try:
                    response = self.llm.call(self.messages, self.response_file)
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
                        # LLM is stuck in a loop — tell it to stop and use [DONE]
                        stuck_msg = (
                            "\n\n[LOOP DETECTED] You are repeating the same output. "
                            "Either complete the task with [DONE] and a summary, "
                            "or use a different tool call. Do NOT repeat the same tool call."
                        )
                        self.messages.append({"role": "assistant", "content": response + stuck_msg})
                    else:
                        reminder = (
                            "\n\n[REMINDER] You must take action using the available tools. "
                            "Use [TOOL:tool_name{param:\"value\"}] format to call tools, "
                            "or [DONE] when you have finished all changes."
                        )
                        self.messages.append({"role": "assistant", "content": response + reminder})
                    continue

                # Strip tool call markers from the response before appending to history.
                # This prevents the LLM from seeing its own tool calls in the conversation,
                # which causes it to repeat them verbatim.
                cleaned_response = re.sub(
                    r'\[TOOL:\s*[a-zA-Z_][a-zA-Z0-9_-]*\s*\{[^}]*\}\s*\]\s*',
                    '',
                    response
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
                        result_text = json.dumps(result.to_dict(), indent=2)
                    except SecurityError as e:
                        step_entry["result"] = ToolResult(False, "", error=f"SECURITY: {e}").to_dict()
                        result_text = json.dumps(ToolResult(False, "", error=f"SECURITY: {e}").to_dict())
                        self.logger.warning(f"Security violation: {e}")
                    except ToolError as e:
                        step_entry["result"] = ToolResult(False, "", error=str(e)).to_dict()
                        result_text = json.dumps(ToolResult(False, "", error=str(e)).to_dict())
                        self.logger.warning(f"Tool error: {e}")
                    except Exception as e:
                        step_entry["result"] = ToolResult(False, "", error=f"Unexpected error: {e}").to_dict()
                        result_text = json.dumps(ToolResult(False, "", error=f"Unexpected error: {e}").to_dict())
                        self.logger.error(f"Unexpected tool error: {e}")

                    # Save step to history
                    self.step_history.append(step_entry)
                    with open(self.step_log_file, 'a', encoding='utf-8') as f:
                        f.write(json.dumps(step_entry) + '\n')

                    # Feed tool result back to conversation
                    self.messages.append({
                        "role": "system",
                        "content": f"[TOOL RESULT for {tool_name}]\n{result_text}\n[END TOOL RESULT]\n\nNow continue with your next action."
                    })

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
                        f"find_symbol, decompile_jar, list_dependencies, check_syntax, get_file_info. "
                        f"Think about what you've learned so far and what you need to do next. "
                        f"Either make a concrete change with write_file/edit_file, or gather specific information with a different tool. "
                        f"DO NOT call {repeated_tool} again."
                    )
                    self.messages.append({"role": "system", "content": intervention})
                    continue

            # Run post-script
            post_script = EngineConfig.get_post_script()
            if post_script:
                self._run_script("post", post_script)

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


def run(project_config: Dict[str, Any]) -> Dict[str, Any]:
    """Run the agentic engine with the given project configuration."""
    engine = AgentEngine(project_config)
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
