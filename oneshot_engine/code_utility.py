"""Code collection — walk directories and collect file contents for LLM context."""

import os
import logging
from typing import List


class CodeUtility:
    """Collects source code from a project directory for LLM context."""

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
                    return [
                        line.strip()
                        for line in file
                        if line.strip() and not line.strip().startswith('#')
                    ]
            return []
        except Exception as e:
            logging.error(f"Error parsing .gitignore: {e}")
            raise

    def should_process_file(
        self, path: str, rules: List[str], patterns: List[str], mode: str
    ) -> bool:
        try:
            file_name = os.path.basename(path)
            if not patterns:
                return mode == "include"

            normalized_patterns = [p.rstrip('/').rstrip('\\') for p in patterns]
            normalized_path = path.rstrip('/').rstrip('\\')

            for pattern in normalized_patterns:
                pattern_clean = pattern.rstrip('/').rstrip('\\')
                if pattern_clean == normalized_path:
                    return mode == "include"
                if (normalized_path.startswith(pattern_clean + '/')
                        or normalized_path.startswith(pattern_clean + '\\')):
                    return mode == "include"
                if pattern_clean in normalized_path.split(os.sep):
                    return mode == "include"
            return mode == "exclude"
        except Exception as e:
            logging.error(f"Error determining if file should be processed: {e}")
            raise

    def process_directory(
        self, directory: str, parent_rules: List[str], patterns: List[str], mode: str
    ) -> None:
        try:
            if not isinstance(parent_rules, list):
                parent_rules = [parent_rules] if parent_rules else []

            absolute_mode = not directory

            if absolute_mode:
                logging.info("Directory is blank — treating patterns as absolute file paths.")
            else:
                logging.info(
                    f"Directory provided — treating patterns as relative paths inside: {directory}"
                )

            file_paths = []
            for p in patterns:
                p = p.strip()
                if os.path.isabs(p):
                    full_path = p
                elif absolute_mode:
                    full_path = p
                else:
                    full_path = os.path.join(directory, p)

                full_path = os.path.normpath(full_path)

                if directory and not absolute_mode:
                    directory = os.path.normpath(directory)
                    if (not full_path.startswith(directory + os.sep)
                            and full_path != directory):
                        logging.warning(
                            f"Skipping path that would traverse outside root directory: {p}"
                        )
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

                if absolute_mode or self.should_process_file(
                    relative_path, all_rules, patterns, mode
                ):
                    try:
                        if os.path.isfile(full_path):
                            with open(full_path, 'r', encoding='utf-8') as f:
                                content = f.read()

                            with open(self.output_file, 'a', encoding='utf-8') as out_file:
                                out_file.write(
                                    f"\n### {relative_path}\n```\n{content}\n```\n"
                                )

                            logging.info(
                                f"Successfully wrote content from {relative_path} "
                                f"to {self.output_file}"
                            )
                        else:
                            logging.warning(f"Path is not a file, skipping: {full_path}")
                    except Exception as e:
                        logging.warning(
                            f"Skipped unreadable file: {relative_path} - Error: {e}"
                        )
                        with open(self.output_file, 'a', encoding='utf-8') as out_file:
                            out_file.write(
                                f"\n### {relative_path}\n```\n"
                                f"CONTENT UNREADABLE / POTENTIAL BINARY\n```\n"
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
                        nl = chr(10)
                        out_file.write(
                            f"{nl}### {rel_path}{nl}```{nl}{content}{nl}```{nl}"
                        )
                except Exception as e:
                    logging.warning(
                        f"Skipped unreadable diff file: {rel_path} - Error: {e}"
                    )
        except Exception as e:
            logging.error(f"Error collecting diff files: {e}")
            raise
