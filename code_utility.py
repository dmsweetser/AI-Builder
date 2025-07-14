import os
import re
import logging
import subprocess
from typing import List, Dict, Optional

class CodeUtility:
    def __init__(self, base_dir: str = os.getcwd()):
        self.base_dir = base_dir
        self.output_file = os.path.join(base_dir, "output.txt")
        self.log_file = os.path.join(base_dir, "utility.log")
        self.setup_logging()

    def setup_logging(self):
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(self.log_file),
                logging.StreamHandler()
            ]
        )

    def parse_gitignore(self, directory: str) -> List[str]:
        gitignore_path = os.path.join(directory, ".gitignore")
        if os.path.exists(gitignore_path):
            with open(gitignore_path, 'r') as file:
                return [line.strip() for line in file if line.strip() and not line.strip().startswith('#')]
        return []

    def should_process_file(self, path: str, rules: List[str], patterns: List[str], mode: str) -> bool:
        file_name = os.path.basename(path)
        for rule in rules:
            if rule in path:
                return mode == "exclude"
        if file_name in patterns:
            return mode == "include"
        for pattern in patterns:
            if pattern in file_name or pattern in path:
                return mode == "include"
        return mode != "include"

    def process_directory(self, directory: str, parent_rules: List[str], patterns: List[str], mode: str):
        current_rules = self.parse_gitignore(directory)
        all_rules = parent_rules + current_rules
        for root, dirs, files in os.walk(directory):
            for file in files:
                full_path = os.path.join(root, file)
                relative_path = os.path.relpath(full_path, self.base_dir)
                if self.should_process_file(relative_path, all_rules, patterns, mode):
                    try:
                        with open(full_path, 'r') as f:
                            content = f.read()
                        with open(self.output_file, 'a') as out_file:
                            out_file.write(f"\n### {relative_path}\n```\n{content}\n```\n")
                    except Exception as e:
                        logging.error(f"Skipped unreadable file: {relative_path} - Error: {e}")

    def sanitize_path_component(self, path_component: str) -> str:
        sanitized_component = re.sub(r'[<>:"\\|?*]', '_', path_component)
        sanitized_component = re.sub(r'\p{C}', '', sanitized_component, flags=re.UNICODE)
        return sanitized_component.strip("#` ")

    def resolve_file_path(self, file_path_string: str) -> Dict[str, str]:
        trimmed = file_path_string.strip('"`')
        parts = re.split(r'[\\/]+', trimmed)
        file_name = self.sanitize_path_component(parts[-1])
        directory = self.base_dir
        if len(parts) > 1:
            directory = os.path.join(directory, *map(self.sanitize_path_component, parts[:-1]))
        return {"Directory": directory, "FileName": file_name}

    def parse_markdown_content(self, markdown_content: str):
        lines = markdown_content.split("\n")
        inside_code_block = False
        file_content = ""
        file_name = None
        current_dir = self.base_dir
        for i, line in enumerate(lines):
            line = line.rstrip()
            if line.startswith("```"):
                if not inside_code_block:
                    inside_code_block = True
                    match = re.match(r'^```\s*(\S*)\s*$', line)
                    if match and match.group(1):
                        if '.' in match.group(1):
                            resolved = self.resolve_file_path(match.group(1))
                            file_name = resolved["FileName"]
                            current_dir = resolved["Directory"]
                        else:
                            if i + 1 < len(lines):
                                next_line = lines[i + 1].rstrip()
                                if next_line and '.' in next_line:
                                    resolved = self.resolve_file_path(next_line)
                                    file_name = resolved["FileName"]
                                    current_dir = resolved["Directory"]
                                    i += 1
                else:
                    inside_code_block = False
                    if file_name and file_content:
                        if not os.path.exists(current_dir):
                            os.makedirs(current_dir, exist_ok=True)
                        file_path = os.path.join(current_dir, file_name)
                        with open(file_path, 'w', encoding='utf-8') as f:
                            f.write(file_content)
                        logging.info(f"File created: {file_path}")
                    file_content = ""
                    file_name = None
            elif not inside_code_block and re.match(r'^###\s*`?(.+?)`?\s*$', line):
                file_path = re.match(r'^###\s*`?(.+?)`?\s*$', line).group(1).strip()
                resolved = self.resolve_file_path(file_path)
                file_name = resolved["FileName"]
                current_dir = resolved["Directory"]
            elif inside_code_block and file_name:
                file_content += line + "\n"
        if inside_code_block and file_name and file_content:
            if not os.path.exists(current_dir):
                os.makedirs(current_dir, exist_ok=True)
            file_path = os.path.join(current_dir, file_name)
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(file_content)
            logging.info(f"File created: {file_path}")

    def split_patch_file(self, patch_file_path: str):
        with open(patch_file_path, 'r') as file:
            content = file.read()
        patches = content.split('diff --git')
        for i, patch in enumerate(patches):
            if i == 0:
                continue
            with open(f'patch_{i}.patch', 'w') as patch_file:
                patch_file.write(f"diff --git{patch}")

    def split_and_apply_patches(self, patch_file_path: str):
        self.split_patch_file(patch_file_path)
        patch_files = sorted([f for f in os.listdir('.') if f.startswith('patch_') and f.endswith('.patch')])
        for patch_file in patch_files:
            logging.info(f"Processing {patch_file}")
            with open(patch_file, 'r') as f:
                content = f.read()
            hunks = re.split(r'(^@@.*?@@.*?$)', content, flags=re.MULTILINE)
            if len(hunks) > 1:
                header = hunks[0]
                success_count = 0
                for i in range(len(hunks) - 1, 0, -2):
                    if i - 1 >= 0:
                        hunk_content = header + hunks[i - 1] + hunks[i]
                        hunk_file = f"hunk_{(i // 2) + 1}.patch"
                        with open(hunk_file, 'w') as f:
                            f.write(hunk_content)
                        result = subprocess.run(['git', 'apply', '--directory=' + self.base_dir, hunk_file], capture_output=True, text=True)
                        if result.returncode == 0:
                            logging.info(f"  ✓ Applied {hunk_file}")
                            os.remove(hunk_file)
                            success_count += 1
                        else:
                            logging.error(f"  ✗ Failed {hunk_file}: {result.stderr.strip()}")
                if success_count == (len(hunks) - 1) // 2:
                    os.remove(patch_file)
                    logging.info(f"  All hunks applied successfully for {patch_file}")
            else:
                result = subprocess.run(['git', 'apply', '--directory=' + self.base_dir, patch_file], capture_output=True, text=True)
                if result.returncode == 0:
                    logging.info(f"  ✓ Applied {patch_file}")
                    os.remove(patch_file)
                else:
                    logging.error(f"  ✗ Failed {patch_file}: {result.stderr.strip()}")
