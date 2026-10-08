"""AIBuilder — the one-shot execution engine and agent-engine integration."""

import os
import platform
import re
import logging
import shutil
import subprocess
import time
import uuid
import json
import xml.etree.ElementTree as ET
from typing import List, Dict, Any, Optional

from dotenv import load_dotenv
from azure.ai.inference import ChatCompletionsClient
from azure.ai.inference.models import SystemMessage, UserMessage
from azure.core.credentials import AzureKeyCredential

from config import Config
from oneshot_engine.parser import FileParser
from oneshot_engine.modifier import FileModifier
from oneshot_engine.action_manager import ActionManager
from oneshot_engine.code_utility import CodeUtility

load_dotenv()

# ---------------------------------------------------------------------------
# Agent Engine Integration
# ---------------------------------------------------------------------------
try:
    from agent_engine import run as agent_run
    _HAS_AGENT_ENGINE = True
except ImportError:
    _HAS_AGENT_ENGINE = False


class AIBuilder:
    """One-shot code-engine: collect code, prompt LLM, parse & apply changes."""

    def __init__(self, job_id: str, project_config: Optional[Dict[str, Any]] = None):
        self.project_config = project_config
        self.clean_mode = project_config is not None
        self.use_git_diff = False

        if self.clean_mode:
            self.root_directory = project_config.get("rootDirectory", None)
            self.ai_builder_dir = os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                "aib_instance", "output", job_id,
            )
            if not self.root_directory:
                logging.warning(
                    "No rootDirectory provided. Assuming includePatterns are full paths."
                )
        else:
            self.root_directory = Config.get_root_directory()
            self.ai_builder_dir = Config.get_ai_builder_dir(self.root_directory)
            self.use_git_diff = Config.get_use_git_diff()

        os.makedirs(self.ai_builder_dir, exist_ok=True)
        self.response_file = os.path.join(self.ai_builder_dir, "current_response.txt")

        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(
                    Config.get_log_file_path(self.root_directory)
                    if not self.clean_mode
                    else os.path.join(self.ai_builder_dir, "log.txt")
                ),
                logging.StreamHandler(),
            ],
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def get_git_diff_files(self) -> List[str]:
        try:
            git_diff_command = Config.get_git_diff_command()
            result = subprocess.run(
                git_diff_command.split(),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=True,
                cwd=self.root_directory if self.root_directory else None,
            )
            return [line.strip() for line in result.stdout.splitlines() if line.strip()]
        except Exception as e:
            logging.error(f"Error getting git diff files: {e}")
            return []

    def run_pre_post_scripts(self, script_name: str) -> None:
        try:
            if self.clean_mode:
                script_content = (
                    self.project_config.get("preScript", "")
                    if script_name == "pre.ps1"
                    else self.project_config.get("postScript", "")
                )
                if not script_content.strip():
                    return

                temp_script_path = os.path.join(
                    self.ai_builder_dir, f"{script_name}_{uuid.uuid4().hex}.ps1"
                )
                with open(temp_script_path, "w", encoding='utf-8') as f:
                    f.write(script_content)

                powershell = "powershell" if platform.system() == "Windows" else "pwsh"
                subprocess.run(
                    [powershell, "-File", temp_script_path],
                    check=True,
                    cwd=self.root_directory,
                )
                logging.info(f"Successfully executed {script_name} (clean mode)")
                os.remove(temp_script_path)
            else:
                script_path = os.path.join(os.getcwd(), script_name)
                if not os.path.exists(script_path):
                    raise FileNotFoundError(f"Script {script_name} not found.")
                if not script_path.startswith(os.getcwd()):
                    raise ValueError(
                        f"Script path {script_path} is outside current working directory"
                    )

                powershell = "powershell" if platform.system() == "Windows" else "pwsh"
                subprocess.run(
                    [powershell, "-File", script_path],
                    check=True,
                    cwd=self.root_directory,
                )
                logging.info(f"Successfully executed {script_name}")
        except subprocess.CalledProcessError as e:
            logging.error(f"Failed to execute {script_name}: {e}")
            raise
        except Exception as e:
            logging.error(f"Error executing script {script_name}: {e}")
            raise

    def cleanup_bak_files(self, directory: str, patterns: List[str]) -> None:
        try:
            absolute_mode = not directory

            if absolute_mode:
                logging.info(
                    "Directory is blank — treating patterns as absolute .bak file paths."
                )
            else:
                logging.info(
                    f"Directory provided — treating patterns as relative .bak paths "
                    f"inside: {directory}"
                )

            file_paths = []
            for p in patterns:
                p = p.strip()
                if absolute_mode or os.path.isabs(p):
                    full_path = p
                else:
                    full_path = os.path.join(directory, p)
                file_paths.append(full_path + ".bak")

            for full_path in file_paths:
                try:
                    if os.path.exists(full_path):
                        os.remove(full_path)
                        logging.info(f"Removed backup file: {full_path}")
                except Exception as e:
                    logging.error(f"Error removing backup file {full_path}: {e}")

        except Exception as e:
            logging.error(f"Error cleaning up backup files: {e}")
            raise

    # ------------------------------------------------------------------
    # LLM interaction
    # ------------------------------------------------------------------
    def build_prompt(self, current_code: str, instructions: str) -> str:
        escaped_code = FileParser.escape_newline_sequences(current_code)
        escaped_instructions = FileParser.escape_newline_sequences(instructions)

        return f"""
Generate a line-delimited format file that describes file modifications to apply using the `create_file`, `remove_file`, `replace_file`, and `replace_section` action types.
Ensure all content is provided using line-delimited format-compatible entities.
Focus on small, specific sections of code rather than large blocks.
Ensure you do not omit any existing code and only modify the sections specified.
Available operations:
1. `create_file`:
    - `file_content`: List of strings (lines of the file content)
2. `remove_file`:
    - No additional parameters needed.
3. `replace_file`:
    - `file_content`: List of strings (lines of the new file content)
    - The revision must be entirely complete
4. `replace_section`:
    - `original_content`: The original content in the file
    - `file_content`: List of strings (lines of the new file content to replace the original content)
Example output format:
[aibuilder_change file="new_file.py"]
[aibuilder_action type="create_file"]
[aibuilder_file_content]
# Content line 1 with whitespace preserved
\t# Content line 2 with whitespace preserved
\t# Content line 3 with whitespace preserved
[aibuilder_end_file_content]
[aibuilder_end_action]
[aibuilder_change file="old_file.py"]
[aibuilder_action type="remove_file"]
[aibuilder_end_action]
[aibuilder_change file="file_to_replace.py"]
[aibuilder_action type="replace_file"]
[aibuilder_file_content]
# New content line 1 with whitespace preserved
\t# New content line 2 with whitespace preserved
\t# New content line 3 with whitespace preserved
[aibuilder_end_file_content]
[aibuilder_end_action]
[aibuilder_change file="file_to_modify.py"]
[aibuilder_action type="replace_section"]
[aibuilder_original_content]
# Original content line 1
\t# Original content line 2
[aibuilder_end_original_content]
[aibuilder_file_content]
# New content line 1 with whitespace preserved
\t# New content line 2 with whitespace preserved
\t# New content line 3 with whitespace preserved
[aibuilder_end_file_content]
[aibuilder_end_action]
Generate modifications logically based on the desired changes.
Current code:
{escaped_code}
Instructions:
{escaped_instructions}
Reply ONLY in the specified format with no commentary. THAT'S AN ORDER, SOLDIER!
"""

    def run_model(self, prompt: str) -> str:
        response_content = ""
        if Config.use_local_model():
            model_path = Config.get_model_path()
            if not model_path:
                raise ValueError("MODEL_PATH environment variable not set for local model.")
            llama_binary = Config.get_llama_binary_path()
            if not os.path.isfile(llama_binary):
                raise FileNotFoundError(f"llama binary not found at: {llama_binary}")

            ticks = int(time.time() * 1000)
            filename = os.path.join(self.ai_builder_dir, f"aibuilder_prompt_{ticks}.txt")

            if not os.path.dirname(filename).startswith(self.ai_builder_dir):
                raise ValueError("Prompt file path is outside allowed directory")

            with open(filename, "w", encoding='utf-8') as f:
                f.write(prompt)

            cmd = [
                llama_binary,
                "-m", model_path,
                "-f", filename,
                "--temp", str(Config.get_temperature()),
                "--top-p", str(Config.get_top_p()),
                "--top-k", str(Config.get_top_k()),
                "--min-p", str(Config.get_min_p()),
                "-n", str(Config.get_output_tokens()),
                "--ctx-size", str(Config.get_model_context()),
                "--jinja",
                "--no-display-prompt",
                "-st",
            ]

            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
            )

            current_iteration = 0
            while True:
                token = process.stdout.read(1)
                if current_iteration % 100 == 0 or not token:
                    with open(self.response_file, 'w', encoding='utf-8') as response_log:
                        response_log.write(response_content)
                if not token:
                    if os.path.exists(filename):
                        try:
                            os.remove(filename)
                        except Exception as e:
                            logging.error(f"Failed to remove temporary prompt file: {e}")
                    break
                response_content += token
                current_iteration += 1

            process.wait()
        else:
            endpoint = Config.get_endpoint()
            model_name = Config.get_model_name()
            api_key = Config.get_api_key()
            verify_ssl = Config.verify_ssl()
            if not all([endpoint, model_name, api_key]):
                logging.error(
                    "Missing one or more required environment variables: "
                    "ENDPOINT, MODEL_NAME, API_KEY"
                )
                raise ValueError("Missing required environment variables.")

            client = ChatCompletionsClient(
                endpoint=endpoint,
                credential=AzureKeyCredential(api_key),
                api_version="2024-05-01-preview",
                connection_verify=verify_ssl,
            )
            response = client.complete(
                stream=True,
                messages=[
                    SystemMessage(content="You are a helpful assistant."),
                    UserMessage(content=prompt),
                ],
                max_tokens=Config.get_output_tokens(),
                model=model_name,
            )
            current_iteration = 0
            try:
                for update in response:
                    if update.choices and isinstance(update.choices, list) and len(update.choices) > 0:
                        content = update.choices[0].get("delta", {}).get("content", "")
                        if content is not None:
                            response_content += content
                        if current_iteration % 100 == 0:
                            with open(self.response_file, 'w', encoding='utf-8') as response_log:
                                response_log.write(response_content)
                        current_iteration += 1
                    else:
                        break
            finally:
                response.close()

        logging.info("Successfully obtained response from client.")
        return response_content

    # ------------------------------------------------------------------
    # Main run loop
    # ------------------------------------------------------------------
    def run(self) -> None:
        try:
            if self.clean_mode:
                iterations = self.project_config.get("iterations", 1)
                mode = self.project_config.get("mode", "include")
                raw_patterns = self.project_config.get("includePatterns", "")
                patterns = (
                    [p.strip() for p in raw_patterns.split(",") if p.strip()]
                    if isinstance(raw_patterns, str)
                    else (raw_patterns if isinstance(raw_patterns, list) else [])
                )
                raw_exclude = self.project_config.get("excludePatterns", "")
                exclude_patterns = (
                    [p.strip() for p in raw_exclude.split(",") if p.strip()]
                    if isinstance(raw_exclude, str)
                    else (raw_exclude if isinstance(raw_exclude, list) else [])
                )
                instructions = self.project_config.get("instructions", "")

                diff_files = []
                for p in patterns:
                    p = p.strip()
                    if os.path.isabs(p):
                        diff_files.append(p)
                    elif self.root_directory:
                        diff_files.append(os.path.join(self.root_directory, p))
                    else:
                        diff_files.append(p)
            else:
                base_config_path = os.path.join("base_config.xml")
                user_config_path = os.path.join(self.ai_builder_dir, "user_config.xml")
                shutil.copy(base_config_path, user_config_path)
                logging.info("Copied base_config.xml to user_config.xml")
                os.chdir(self.root_directory)
                logging.info(f"Changed working directory to: {self.root_directory}")
                config = ET.parse(user_config_path).getroot()
                iterations = int(config.find('iterations').text)
                mode = config.find('mode').text
                patterns = [pattern.text for pattern in config.findall('patterns/pattern')]
                exclude_patterns = []
                with open('instructions.txt', 'r', encoding='utf-8') as file:
                    instructions = file.read()
                logging.info("Successfully read instructions.txt")

            self.utility = CodeUtility(
                self.root_directory, self.ai_builder_dir, self.use_git_diff
            )
            actions_file_path = os.path.join(self.ai_builder_dir, "actions.txt")

            for iteration in range(iterations):
                logging.info(f"Starting iteration {iteration + 1}")
                self.run_pre_post_scripts("pre.ps1")
                try:
                    modifications_format_path = os.path.join(
                        self.ai_builder_dir, "modifications.txt"
                    )
                    if os.path.exists(modifications_format_path):
                        with open(modifications_format_path, 'r', encoding='utf-8') as modifications_file:
                            response_content = modifications_file.read()
                    else:
                        if os.path.exists(self.utility.output_file):
                            os.remove(self.utility.output_file)

                        if self.use_git_diff:
                            logging.info(
                                "use_git_diff enabled — collecting files from git diff "
                                "instead of walking directory."
                            )
                            diff_files = self.get_git_diff_files()
                            if diff_files:
                                self.utility.collect_files(diff_files)
                            else:
                                logging.info(
                                    "No files in git diff, falling back to directory walk."
                                )
                                self.utility.process_directory(
                                    self.root_directory, exclude_patterns, patterns, mode
                                )
                        else:
                            self.utility.process_directory(
                                "", exclude_patterns, diff_files, mode
                            )

                        if not os.path.exists(self.utility.output_file):
                            logging.warning("output.txt was not created by process_directory.")
                            continue

                        with open(self.utility.output_file, 'r', encoding='utf-8') as file:
                            current_code = file.read()
                        logging.info("Successfully read output.txt")

                        prompt = self.build_prompt(current_code, instructions)
                        response_content = self.run_model(prompt)
                        response_content = FileParser.unescape_newline_sequences(response_content)

                        with open(modifications_format_path, 'w', encoding='utf-8') as modifications_file:
                            modifications_file.write(response_content)
                        logging.info(
                            f"Successfully wrote modifications file to "
                            f"{modifications_format_path}"
                        )

                    if not Config.generate_but_do_not_apply():
                        changes = FileParser.parse_custom_format(response_content)
                        incomplete_actions = FileModifier.apply_modifications(
                            changes,
                            self.root_directory,
                            dry_run=False,
                            output_dir=self.ai_builder_dir,
                            scope_paths=diff_files,
                        )
                        ActionManager.save_actions(incomplete_actions, actions_file_path)

                except Exception as e:
                    logging.error(f"An error occurred: {str(e)}", exc_info=True)
                    try:
                        with open(actions_file_path, 'w', encoding='utf-8') as f:
                            f.write(f"ERROR: {str(e)}\n")
                    except Exception as save_err:
                        logging.error(f"Failed to save error to actions.txt: {save_err}")

                self.run_pre_post_scripts("post.ps1")
                self.cleanup_bak_files(self.root_directory, patterns)

        except Exception as e:
            logging.error(f"An error occurred during execution: {str(e)}", exc_info=True)
            try:
                with open(actions_file_path, 'w', encoding='utf-8') as f:
                    f.write(f"FATAL ERROR: {str(e)}\n")
            except Exception:
                pass


def run_with_agent_engine(project_config: Dict[str, Any]) -> Dict[str, Any]:
    """Run the multi-step agentic engine (delegates to agent_engine)."""
    if not _HAS_AGENT_ENGINE:
        logging.warning(
            "agent_engine.py not found — falling back to legacy single-pass mode."
        )
        return {}

    if "job_id" not in project_config:
        project_config["job_id"] = str(int(time.time() * 1000))

    root_dir = project_config.get("rootDirectory", "")
    output_dir = os.path.join(
        root_dir, "aib_instance", "output", project_config["job_id"]
    )

    os.environ["AIB_ROOT"] = root_dir
    os.environ["AIB_INSTRUCTIONS"] = project_config.get("instructions", "")
    os.environ["AIB_PRE_SCRIPT"] = project_config.get("preScript", "")
    os.environ["AIB_POST_SCRIPT"] = project_config.get("postScript", "")

    enabled_tools = project_config.get("enabled_tools")
    if enabled_tools:
        os.environ["AIB_ENABLED_TOOLS"] = json.dumps(enabled_tools)

    return agent_run(project_config, output_dir=output_dir)
