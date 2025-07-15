import os
import re
import logging
import subprocess
from typing import List, Dict, Optional

class CodeUtility:
    def __init__(self, base_dir: str = os.getcwd()):
        self.base_dir = base_dir
        self.output_file = os.path.join(base_dir, "ai_builder", "output.txt")
        self.log_file = os.path.join(base_dir, "ai_builder", "utility.log")
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
                return False
        for pattern in patterns:
            if pattern in file_name or pattern in path:
                return mode == "include"
        return mode == "exclude"

    def process_directory(self, directory: str, parent_rules: List[str], patterns: List[str], mode: str):
        current_rules = self.parse_gitignore(directory)
        all_rules = parent_rules + current_rules
        logging.info(f"Processing directory: {directory}")

        for root, dirs, files in os.walk(directory):
            logging.info(f"Current root: {root}, dirs: {dirs}, files: {files}")
            for file in files:
                relative_path = os.path.relpath(os.path.join(root, file), self.base_dir)
                logging.info(f"Checking file: {relative_path}")
                if self.should_process_file(relative_path, all_rules, patterns, mode):
                    try:
                        with open(os.path.join(root, file), 'r') as f:
                            content = f.read()
                        with open(self.output_file, 'a') as out_file:
                            out_file.write(f"\n### {relative_path}\n```\n{content}\n```\n")
                        logging.info(f"Successfully wrote content from {relative_path} to {self.output_file}")
                    except Exception as e:
                        logging.error(f"Skipped unreadable file: {relative_path} - Error: {e}")
