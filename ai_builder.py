import os
import platform
import re
import logging
import shutil
import subprocess
import time
import uuid
import xml.etree.ElementTree as ET
from typing import List, Dict, Any, Optional
from dotenv import load_dotenv
from azure.ai.inference import ChatCompletionsClient
from azure.ai.inference.models import SystemMessage, UserMessage
from azure.core.credentials import AzureKeyCredential
from config import Config

load_dotenv()

LINE_DELIMITER = f"<<<AI_BUILDER_LINE_DELIMITER_{uuid.uuid4().hex}>>>"
IS_LEGACY = False

class FileParser:
    @staticmethod
    def _safe_split(content: str) -> List[str]:
        return content.replace(f"{chr(10)}", LINE_DELIMITER).split(f"{chr(10)}")

    @staticmethod
    def _safe_join(lines: List[str]) -> str:
        return f"{chr(10)}".join(lines).replace(LINE_DELIMITER, f"{chr(10)}")

    @staticmethod
    def parse_custom_format(content: str) -> List[Dict[str, Any]]:
        try:
            if "</think>" in content:
                split_content = re.split(r'<\/think>\s*\[?aibuilder', content, flags=re.DOTALL)
                if len(split_content) > 1:
                    content = "[aibuilder" + split_content[1]
                else:
                    content = split_content[0]
            content = re.sub(r'^.*?\[?aibuilder_change', '[aibuilder_change', content, flags=re.DOTALL)
            changes = []
            change_blocks = re.finditer(
                r'\[?aibuilder_change\s+file\s*=\s*"([^"]+)"\](.*?)(?=\[?aibuilder_change|$)',
                content,
                re.DOTALL
            )
            for block in change_blocks:
                file = block.group(1)
                actions = FileParser._parse_actions(block.group(2))
                changes.append({'file': file, 'actions': actions})
            return changes
        except Exception as e:
            logging.error(f"Error parsing custom format: {e}")
            raise

    @staticmethod
    def _parse_actions(content: str) -> List[Dict[str, Any]]:
        try:
            actions = []
            action_blocks = re.finditer(
                r'\[?aibuilder_action\s+type\s*=\s*"([^"]+)"\](.*?)\[?aibuilder_end_action\]',
                content,
                re.DOTALL
            )
            for action_block in action_blocks:
                action_type = action_block.group(1)
                action_content = action_block.group(2)
                if action_type == 'create_file':
                    action = FileParser._parse_create_action(action_content)
                elif action_type == 'remove_file':
                    action = {'action': 'remove_file'}
                elif action_type == 'replace_file':
                    action = FileParser._parse_replace_file_action(action_content)
                elif action_type == 'replace_section':
                    action = FileParser._parse_replace_section_action(action_content)
                else:
                    continue
                if action:
                    actions.append(action)
            return actions
        except Exception as e:
            logging.error(f"Error parsing actions: {e}")
            raise

    @staticmethod
    def _parse_create_action(content: str) -> Optional[Dict[str, Any]]:
        try:
            file_content_pattern = r'\[?aibuilder_file_content\](.*?)\[?aibuilder_end_file_content\]'
            file_content_match = re.search(file_content_pattern, content, re.DOTALL)
            if file_content_match:
                file_content = file_content_match.group(1)
                return {
                    'action': 'create_file',
                    'file_content': FileParser._safe_split(file_content)
                }
            return None
        except Exception as e:
            logging.error(f"Error parsing create action: {e}")
            raise

    @staticmethod
    def _parse_replace_file_action(content: str) -> Optional[Dict[str, Any]]:
        try:
            file_content_pattern = r'\[?aibuilder_file_content\](.*?)\[?aibuilder_end_file_content\]'
            file_content_match = re.search(file_content_pattern, content, re.DOTALL)
            if file_content_match:
                file_content = file_content_match.group(1)
                return {
                    'action': 'replace_file',
                    'file_content': FileParser._safe_split(file_content)
                }
            return None
        except Exception as e:
            logging.error(f"Error parsing replace file action: {e}")
            raise

    @staticmethod
    def _parse_replace_section_action(content: str) -> Optional[Dict[str, Any]]:
        try:
            original_content_pattern = r'\[?aibuilder_original_content\](.*?)\[?aibuilder_end_original_content\]'
            file_content_pattern = r'\[?aibuilder_file_content\](.*?)\[?aibuilder_end_file_content\]'
            original_content_match = re.search(original_content_pattern, content, re.DOTALL)
            file_content_match = re.search(file_content_pattern, content, re.DOTALL)
            if original_content_match and file_content_match:
                original_content = original_content_match.group(1)
                file_content = file_content_match.group(1)
                return {
                    'action': 'replace_section',
                    'original_content': original_content,
                    'file_content': FileParser._safe_split(file_content)
                }
            return None
        except Exception as e:
            logging.error(f"Error parsing replace section action: {e}")
            raise

class FileModifier:
    @staticmethod
    def _sanitize_path(filepath: str, root_directory: str) -> str:
        """Sanitize file path to prevent directory traversal."""
        if os.path.isabs(filepath):
            return filepath  # Absolute paths are allowed as-is

        if not root_directory:
            return filepath

        full_path = os.path.join(root_directory, filepath)
        full_path = os.path.normpath(full_path)

        root_dir = os.path.normpath(root_directory)
        if not full_path.startswith(root_dir + os.sep) and full_path != root_dir:
            raise ValueError(f"Path traversal detected: {filepath} resolves to {full_path} which is outside {root_dir}")

        return full_path

    @staticmethod
    def apply_modifications(changes: List[Dict[str, Any]], root_directory: str, dry_run: bool = False, output_dir: str = None) -> List[Dict[str, Any]]:
        try:
            incomplete_actions = []
            processed_files = set()
            created_files = []

            for change in changes:
                filepath = change['file']
                try:
                    # Use _sanitize_path only if the path is not absolute
                    full_path = filepath if os.path.isabs(filepath) else FileModifier._sanitize_path(filepath, root_directory)

                    logging.info(f"Processing file: {full_path}")

                    if full_path not in processed_files:
                        processed_files.add(full_path)
                        if not dry_run:
                            try:
                                backup_filepath = f"{full_path}.bak"
                                if os.path.exists(full_path):
                                    shutil.copy2(full_path, backup_filepath)
                                    logging.info(f"Created backup: {backup_filepath}")
                                else:
                                    created_files.append(full_path)
                            except Exception as e:
                                logging.error(f"Could not back up file: {full_path}: {e}")

                    for action in change['actions']:
                        try:
                            if dry_run:
                                logging.info(f"Dry run: Would apply action {action['action']} to {full_path}")
                            else:
                                if action['action'] == 'create_file':
                                    if full_path not in created_files:
                                        created_files.append(full_path)
                                if not FileModifier._apply_action(full_path, action):
                                    incomplete_actions.append({'file': full_path, 'action': action})
                        except Exception as e:
                            logging.error(f"Error applying modifications to {full_path}: {e}")
                            incomplete_actions.append({'file': full_path, 'action': action})
                            if not dry_run and os.path.exists(backup_filepath):
                                try:
                                    shutil.copy2(backup_filepath, full_path)
                                    logging.info(f"Restored backup for {full_path}")
                                except Exception as restore_err:
                                    logging.error(f"Failed to restore backup for {full_path}: {restore_err}")
                except Exception as e:
                    logging.error(f"Error processing change for file {filepath}: {e}")
                    incomplete_actions.append({'file': filepath, 'action': {'error': str(e)}})

            if created_files and output_dir and not dry_run:
                try:
                    created_files_path = os.path.join(output_dir, "created_files.txt")
                    with open(created_files_path, 'w', encoding='utf-8') as f:
                        for file_path in created_files:
                            f.write(f"{file_path}\n")
                    logging.info(f"Saved created files list to {created_files_path}")
                except Exception as e:
                    logging.error(f"Error saving created files list: {e}")

            return incomplete_actions
        except Exception as e:
            logging.error(f"Error applying modifications: {e}")
            raise

    @staticmethod
    def _apply_action(filepath: str, action: Dict[str, Any]) -> bool:
        try:
            action_type = action['action']
            if os.path.dirname(filepath):
                os.makedirs(os.path.dirname(filepath), exist_ok=True)

            if action_type == 'create_file':
                content_to_write = FileParser._safe_join(action['file_content']).strip()
                with open(filepath, 'w', encoding='utf-8') as f:
                    f.write(content_to_write)
                logging.info(f"Created/Replaced: {filepath}")
                return True
            elif action_type == 'remove_file':
                if os.path.isfile(filepath) and not any(
                    forbidden in filepath.lower()
                    for forbidden in ['pre.ps1', 'post.ps1', '.bak', '.backup']
                ):
                    os.remove(filepath)
                    logging.info(f"Removed: {filepath}")
                    return True
                else:
                    logging.warning(f"Refusing to remove protected file: {filepath}")
                    return False
            elif action_type == 'replace_file':
                try:
                    dir_path = os.path.dirname(filepath)
                    if dir_path:
                        os.makedirs(dir_path, exist_ok=True)
                    content_to_write = FileParser._safe_join(action['file_content']).strip()
                    with open(filepath, 'w', encoding='utf-8') as f:
                        f.write(content_to_write)
                    logging.info(f"Replaced entire content of: {filepath}")
                    return True
                except Exception as e:
                    logging.error(f"Failed to replace file {filepath}: {e}")
                    return False
            elif action_type == 'replace_section':
                return FileModifier._replace_section(filepath, action['original_content'], action['file_content'])
            return False
        except Exception as e:
            logging.error(f"Error applying action: {e}")
            raise

    @staticmethod
    def _replace_section(filepath: str, original_content: str, new_content: List[str]) -> bool:
        try:
            if not os.path.exists(filepath):
                logging.warning(f"File does not exist for section replacement: {filepath}")
                return False

            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()

            new_section_str = FileParser._safe_join(new_content).strip()

            normalized_original = original_content.replace(f"{chr(13)}{chr(10)}", f"{chr(10)}").strip()
            normalized_content = content.replace(f"{chr(13)}{chr(10)}", f"{chr(10)}")

            match_original = f"{chr(10)}".join([line.strip() for line in normalized_original.split(f"{chr(10)}") if line.strip()])
            match_content = f"{chr(10)}".join([line.strip() for line in normalized_content.split(f"{chr(10)}") if line.strip()])

            if match_original in match_content:
                modified_content = content.replace(original_content.strip(), new_section_str)
                with open(filepath, 'w', encoding='utf-8') as f:
                    f.write(modified_content)
                logging.info(f"Replaced section in: {filepath}")
                return True
            else:
                logging.warning(f"Original content not found in: {filepath}")
                if original_content.strip().lower().replace(" ", "").replace("\t", "") in \
                   content.lower().replace(" ", "").replace("\t", ""):
                    modified_content = content.replace(original_content.strip(), new_section_str)
                    with open(filepath, 'w', encoding='utf-8') as f:
                        f.write(modified_content)
                    logging.info(f"Replaced section in: {filepath} (flexible match)")
                    return True
                return False
        except Exception as e:
            logging.error(f"Error replacing section: {e}")
            raise

class ActionManager:
    @staticmethod
    def save_actions(actions: List[Dict[str, Any]], filepath: str) -> None:
        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                for action in actions:
                    f.write(f"File: {action['file']}{chr(10)}")
                    f.write(f"Action: {action['action']['action']}{chr(10)}")
                    if action['action']['action'] in ['create_file', 'replace_file', 'replace_section']:
                        f.write(f"Content:{chr(10)}")
                        f.write(FileParser._safe_join(action['action']['file_content']) + f"{chr(10)}")
                    if action['action']['action'] == 'replace_section':
                        f.write(f"Original Content:{chr(10)}{action['action']['original_content']}{chr(10)}")
                    f.write(f"{chr(10)}")
            logging.info(f"Saved actions to {filepath}")
        except Exception as e:
            logging.error(f"Error saving actions: {e}")
            raise

    @staticmethod
    def load_actions(filepath: str) -> List[Dict[str, Any]]:
        try:
            actions = []
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()
                action_blocks = re.finditer(
                    r'File: (.*?)\nAction: (.*?)\n(?:Content:\n(.*?)(?=\nFile:|\Z))?(?:Original Content:\n(.*?)(?=\nFile:|\Z))?',
                    content,
                    re.DOTALL
                )
                for block in action_blocks:
                    file = block.group(1)
                    action_type = block.group(2)
                    file_content = FileParser._safe_split(block.group(3)) if block.group(3) else []
                    original_content = block.group(4) if block.group(4) else None
                    action = {'action': action_type}
                    if action_type in ['create_file', 'replace_file', 'replace_section']:
                        action['file_content'] = file_content
                    if action_type == 'replace_section':
                        action['original_content'] = original_content
                    actions.append({'file': file, 'action': action})
            logging.info(f"Loaded actions from {filepath}")
            return actions
        except Exception as e:
            logging.error(f"Error loading actions: {e}")
            raise

class CodeUtility:
    def __init__(self, base_dir: str, ai_builder_dir: str, use_git_diff: bool):
        self.base_dir = base_dir
        self.output_file = os.path.join(ai_builder_dir, "output.txt")
        self.log_file = os.path.join(ai_builder_dir, "utility.log")
        self.use_git_diff = use_git_diff
        self.processed_files = set()

    def parse_gitignore(self, directory: str) -> List[str]:
        try:
            gitignore_path = os.path.join(directory, ".gitignore")
            if os.path.exists(gitignore_path):
                with open(gitignore_path, 'r', encoding='utf-8') as file:
                    return [line.strip() for line in file if line.strip() and not line.strip().startswith('#')]
            return []
        except Exception as e:
            logging.error(f"Error parsing .gitignore: {e}")
            raise

    def should_process_file(self, path: str, rules: List[str], patterns: List[str], mode: str) -> bool:
        try:
            if IS_LEGACY:
                file_name = os.path.basename(path)
                for rule in rules:
                    if rule in path:
                        return False
                for pattern in patterns:
                    if pattern in file_name or pattern in path:
                        return mode == "include"
                return mode == "exclude"
            else:
                file_name = os.path.basename(path)
                if not patterns:
                    return mode == "include"

                normalized_patterns = [p.rstrip('/').rstrip('\\') for p in patterns]
                normalized_path = path.rstrip('/').rstrip('\\')

                for pattern in normalized_patterns:
                    pattern_clean = pattern.rstrip('/').rstrip('\\')
                    if pattern_clean == normalized_path:
                        return mode == "include"
                    if normalized_path.startswith(pattern_clean + '/') or normalized_path.startswith(pattern_clean + '\\'):
                        return mode == "include"
                    if pattern_clean in normalized_path.split(os.sep):
                        return mode == "include"
                return mode == "exclude"
        except Exception as e:
            logging.error(f"Error determining if file should be processed: {e}")
            raise

    def process_directory(self, directory: str, parent_rules: List[str], patterns: List[str], mode: str) -> None:
        try:
            if not isinstance(parent_rules, list):
                parent_rules = [parent_rules] if parent_rules else []

            absolute_mode = not directory  # If directory is blank, treat patterns as absolute

            if absolute_mode:
                logging.info("Directory is blank — treating patterns as absolute file paths.")
            else:
                logging.info(f"Directory provided — treating patterns as relative paths inside: {directory}")

            file_paths = []
            for p in patterns:
                p = p.strip()
                if absolute_mode or os.path.isabs(p):
                    full_path = p  # Treat as absolute
                else:
                    full_path = os.path.join(directory, p)  # Treat as relative

                full_path = os.path.normpath(full_path)

                if directory and not absolute_mode:
                    directory = os.path.normpath(directory)
                    if not full_path.startswith(directory + os.sep) and full_path != directory:
                        logging.warning(f"Skipping path that would traverse outside root directory: {p}")
                        continue

                file_paths.append(full_path)

            all_rules = parent_rules
            if not absolute_mode and directory:
                current_rules = self.parse_gitignore(directory)
                all_rules += current_rules

            for full_path in file_paths:
                if full_path in self.processed_files:
                    logging.info(f"Skipping already processed file: {full_path}")
                    continue

                self.processed_files.add(full_path)

                if absolute_mode:
                    relative_path = full_path
                else:
                    relative_path = os.path.relpath(full_path, self.base_dir)

                logging.info(f"Checking file: {relative_path}")

                if absolute_mode or self.should_process_file(relative_path, all_rules, patterns, mode):
                    try:
                        if os.path.isfile(full_path):
                            with open(full_path, 'r', encoding='utf-8') as f:
                                content = f.read()

                            with open(self.output_file, 'a', encoding='utf-8') as out_file:
                                out_file.write(
                                    f"\n### {relative_path}\n```\n{content}\n```\n"
                                )

                            logging.info(f"Successfully wrote content from {relative_path} to {self.output_file}")
                        else:
                            logging.warning(f"Path is not a file, skipping: {full_path}")
                    except Exception as e:
                        logging.warning(f"Skipped unreadable file: {relative_path} - Error: {e}")
                        with open(self.output_file, 'a', encoding='utf-8') as out_file:
                            out_file.write(
                                f"\n### {relative_path}\n```\nCONTENT UNREADABLE / POTENTIAL BINARY\n```\n"
                            )

        except Exception as e:
            logging.error(f"Error processing directory: {e}")
            raise

    def collect_files(self, diff_files: List[str]) -> None:
        try:
            if os.path.exists(self.output_file):
                os.remove(self.output_file)

            for rel_path in diff_files:
                if rel_path in self.processed_files:
                    continue
                self.processed_files.add(rel_path)

                abs_path = os.path.join(self.base_dir, rel_path) if self.base_dir else rel_path
                if not os.path.isfile(abs_path):
                    continue
                try:
                    with open(abs_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                    with open(self.output_file, 'a', encoding='utf-8') as out_file:
                        out_file.write(f"{chr(10)}### {rel_path}{chr(10)}```{chr(10)}{content}{chr(10)}```{chr(10)}")
                except Exception as e:
                    logging.warning(f"Skipped unreadable diff file: {rel_path} - Error: {e}")
        except Exception as e:
            logging.error(f"Error collecting diff files: {e}")
            raise

class AIBuilder:
    def __init__(self, project_config: Dict[str, Any] = None):
        self.project_config = project_config
        self.clean_mode = project_config is not None
        self.use_git_diff = False

        if self.clean_mode:
            self.root_directory = project_config.get("rootDirectory", None)
            self.ai_builder_dir = os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                "aib_instance",
                "output",
                project_config["id"]
            )
            if not self.root_directory:
                logging.warning("No rootDirectory provided. Assuming includePatterns are full paths.")
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
                logging.FileHandler(Config.get_log_file_path(self.root_directory) if not self.clean_mode else os.path.join(self.ai_builder_dir, "log.txt")),
                logging.StreamHandler()
            ]
        )

    def get_git_diff_files(self) -> List[str]:
        try:
            git_diff_command = Config.get_git_diff_command()
            result = subprocess.run(
                git_diff_command.split(),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=True,
                cwd=self.root_directory if self.root_directory else None
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

                temp_script_path = os.path.join(self.ai_builder_dir, f"{script_name}_{uuid.uuid4().hex}.ps1")
                with open(temp_script_path, "w", encoding='utf-8') as f:
                    f.write(script_content)

                powershell = "powershell" if platform.system() == "Windows" else "pwsh"
                subprocess.run([powershell, "-File", temp_script_path], check=True, cwd=self.root_directory)
                logging.info(f"Successfully executed {script_name} (clean mode)")
                os.remove(temp_script_path)
            else:
                script_path = os.path.join(os.getcwd(), script_name)
                if not os.path.exists(script_path):
                    raise FileNotFoundError(f"Script {script_name} not found.")

                if not script_path.startswith(os.getcwd()):
                    raise ValueError(f"Script path {script_path} is outside current working directory")

                if platform.system() == "Windows":
                    powershell = "powershell"
                else:
                    powershell = "pwsh"
                subprocess.run([powershell, "-File", script_path], check=True, cwd=self.root_directory)
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
                logging.info("Directory is blank — treating patterns as absolute .bak file paths.")
            else:
                logging.info(f"Directory provided — treating patterns as relative .bak paths inside: {directory}")

            file_paths = []
            for p in patterns:
                p = p.strip()
                if absolute_mode or os.path.isabs(p):
                    full_path = p  # Treat as absolute
                else:
                    full_path = os.path.join(directory, p)  # Treat as relative
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

    def build_prompt(self, current_code: str, instructions: str) -> str:
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
{current_code}
Instructions:
{instructions}
Reply ONLY in the specified format with no commentary. THAT'S AN ORDER, SOLDIER!
"""

    def run_model(self, prompt: str) -> str:
        response_content = ""
        if Config.use_local_model():
            model_path = Config.get_model_path()
            if not model_path:
                raise ValueError("MODEL_PATH environment variable not set for local model.")
            base_dir = os.path.dirname(os.path.abspath(__file__))
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
                "-st"
            ]

            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1
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
                logging.error("Missing one or more required environment variables: ENDPOINT, MODEL_NAME, API_KEY")
                raise ValueError("Missing required environment variables.")

            client = ChatCompletionsClient(
                endpoint=endpoint,
                credential=AzureKeyCredential(api_key),
                api_version="2024-05-01-preview",
                connection_verify=verify_ssl
            )
            response = client.complete(
                stream=True,
                messages=[
                    SystemMessage(content="You are a helpful assistant."),
                    UserMessage(content=prompt)
                ],
                max_tokens=Config.get_output_tokens(),
                model=model_name
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

    def run(self) -> None:
        try:
            if self.clean_mode:
                iterations = self.project_config.get("iterations", 1)
                mode = self.project_config.get("mode", "include")
                raw_patterns = self.project_config.get("includePatterns", "")
                patterns = [p.strip() for p in raw_patterns.split(",") if p.strip()] if isinstance(raw_patterns, str) else (raw_patterns if isinstance(raw_patterns, list) else [])
                raw_exclude = self.project_config.get("excludePatterns", "")
                exclude_patterns = [p.strip() for p in raw_exclude.split(",") if p.strip()] if isinstance(raw_exclude, str) else (raw_exclude if isinstance(raw_exclude, list) else [])
                instructions = self.project_config.get("instructions", "")

                # Handle both absolute and relative paths
                diff_files = []
                for p in patterns:
                    p = p.strip()
                    if os.path.isabs(p):
                        diff_files.append(p)  # Use absolute path as-is
                    elif self.root_directory:
                        full_path = os.path.join(self.root_directory, p)
                        diff_files.append(full_path)
                    else:
                        # If no root directory, treat as absolute (user responsibility)
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

            self.utility = CodeUtility(self.root_directory, self.ai_builder_dir, self.use_git_diff)
            actions_file_path = os.path.join(self.ai_builder_dir, "actions.txt")

            for iteration in range(iterations):
                logging.info(f"Starting iteration {iteration + 1}")
                self.run_pre_post_scripts("pre.ps1")
                try:
                    modifications_format_path = os.path.join(self.ai_builder_dir, "modifications.txt")
                    if os.path.exists(modifications_format_path):
                        with open(modifications_format_path, 'r', encoding='utf-8') as modifications_file:
                            response_content = modifications_file.read()
                    else:
                        if os.path.exists(self.utility.output_file):
                            os.remove(self.utility.output_file)
                        if self.use_git_diff:
                            logging.info("use_git_diff enabled — collecting files from git diff instead of walking directory.")
                            diff_files = self.get_git_diff_files()
                            if diff_files:
                                self.utility.collect_files(diff_files)
                            else:
                                logging.info("No files in git diff, falling back to directory walk.")
                                self.utility.process_directory(self.root_directory, exclude_patterns, patterns, mode)
                        else:
                            self.utility.process_directory(self.root_directory, exclude_patterns, patterns, mode)

                        if not os.path.exists(self.utility.output_file):
                            logging.warning("output.txt was not created by process_directory.")
                            continue

                        with open(self.utility.output_file, 'r', encoding='utf-8') as file:
                            current_code = file.read()
                        logging.info("Successfully read output.txt")

                        prompt = self.build_prompt(current_code, instructions)
                        response_content = self.run_model(prompt)

                        with open(modifications_format_path, 'w', encoding='utf-8') as modifications_file:
                            modifications_file.write(response_content)
                        logging.info(f"Successfully wrote modifications file to {modifications_format_path}")

                    if not Config.generate_but_do_not_apply():
                        changes = FileParser.parse_custom_format(response_content)
                        # Pass output_dir to track created files
                        incomplete_actions = FileModifier.apply_modifications(
                            changes,
                            self.root_directory,
                            dry_run=False,
                            output_dir=self.ai_builder_dir
                        )
                        ActionManager.save_actions(incomplete_actions, actions_file_path)

                except Exception as e:
                    logging.error(f"An error occurred: {str(e)}", exc_info=True)
                    # Save error to actions.txt for UI display
                    try:
                        with open(actions_file_path, 'w', encoding='utf-8') as f:
                            f.write(f"ERROR: {str(e)}\n")
                    except Exception as save_err:
                        logging.error(f"Failed to save error to actions.txt: {save_err}")

                self.run_pre_post_scripts("post.ps1")
                self.cleanup_bak_files(self.root_directory, patterns)

        except Exception as e:
            logging.error(f"An error occurred during execution: {str(e)}", exc_info=True)
            # Save error to actions.txt for UI display
            try:
                with open(actions_file_path, 'w', encoding='utf-8') as f:
                    f.write(f"FATAL ERROR: {str(e)}\n")
            except Exception:
                pass

if __name__ == "__main__":
    IS_LEGACY = True
    try:
        ai_builder = AIBuilder()
        ai_builder.run()
    except Exception as e:
        logging.error(f"An error occurred during AIBuilder execution: {str(e)}", exc_info=True)