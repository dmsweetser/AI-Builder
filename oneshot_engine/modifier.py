"""File modification — apply create, remove, replace, replace_section actions."""

import os
import logging
import shutil
from typing import List, Dict, Any, Optional

from oneshot_engine.parser import FileParser


class FileModifier:
    """Applies file modifications parsed from LLM output."""

    @staticmethod
    def _sanitize_path(filepath: str, root_directory: str) -> str:
        """Sanitize file path to prevent directory traversal."""
        if os.path.isabs(filepath):
            return filepath
        if not root_directory:
            return filepath
        full_path = os.path.normpath(os.path.join(root_directory, filepath))
        root_dir = os.path.normpath(root_directory)
        if not full_path.startswith(root_dir + os.sep) and full_path != root_dir:
            raise ValueError(
                f"Path traversal detected: {filepath} resolves to {full_path} "
                f"which is outside {root_dir}"
            )
        return full_path

    @staticmethod
    def apply_modifications(
        changes: List[Dict[str, Any]],
        root_directory: str,
        dry_run: bool = False,
        output_dir: Optional[str] = None,
        scope_paths: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """Apply parsed changes to the filesystem."""
        try:
            incomplete_actions = []
            processed_files = set()
            created_files = []

            normalized_scope_paths = []
            if scope_paths:
                for scope_path in scope_paths:
                    normalized_scope_paths.append(os.path.normpath(scope_path))

            for change in changes:
                filepath = change['file']
                try:
                    normalized_filepath = os.path.normpath(filepath)

                    if os.path.isabs(normalized_filepath):
                        full_path = normalized_filepath
                    else:
                        full_path = None
                        for scope_path in normalized_scope_paths:
                            if (normalized_filepath.startswith(scope_path + os.sep)
                                    or normalized_filepath == scope_path):
                                full_path = os.path.join(scope_path, normalized_filepath)
                                break
                            elif normalized_filepath.startswith(scope_path):
                                full_path = normalized_filepath
                                break

                        if full_path is None:
                            full_path = FileModifier._sanitize_path(filepath, root_directory)

                    full_path = os.path.normpath(full_path)
                    logging.info(f"Processing file: {full_path}")

                    backup_filepath = None
                    if full_path not in processed_files:
                        processed_files.add(full_path)
                        if not dry_run and os.path.exists(full_path):
                            try:
                                backup_filepath = f"{full_path}.bak"
                                shutil.copy2(full_path, backup_filepath)
                                logging.info(f"Created backup: {backup_filepath}")
                            except Exception as e:
                                logging.error(f"Could not back up file: {full_path}: {e}")

                    for action in change['actions']:
                        try:
                            if dry_run:
                                logging.info(
                                    f"Dry run: Would apply action {action['action']} "
                                    f"to {full_path}"
                                )
                            else:
                                if action['action'] == 'create_file':
                                    created_files.append(full_path)
                                if not FileModifier._apply_action(full_path, action):
                                    incomplete_actions.append(
                                        {'file': full_path, 'action': action}
                                    )
                        except Exception as e:
                            logging.error(
                                f"Error applying modifications to {full_path}: {e}"
                            )
                            incomplete_actions.append(
                                {'file': full_path, 'action': action}
                            )
                            if not dry_run and backup_filepath and os.path.exists(backup_filepath):
                                try:
                                    shutil.copy2(backup_filepath, full_path)
                                    logging.info(f"Restored backup for {full_path}")
                                except Exception as restore_err:
                                    logging.error(
                                        f"Failed to restore backup for {full_path}: "
                                        f"{restore_err}"
                                    )
                except Exception as e:
                    logging.error(f"Error processing change for file {filepath}: {e}")
                    incomplete_actions.append(
                        {'file': filepath, 'action': {'error': str(e)}}
                    )

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
                dir_path = os.path.dirname(filepath)
                if dir_path:
                    os.makedirs(dir_path, exist_ok=True)
                content_to_write = FileParser._safe_join(action['file_content']).strip()
                with open(filepath, 'w', encoding='utf-8') as f:
                    f.write(content_to_write)
                logging.info(f"Replaced entire content of: {filepath}")
                return True

            elif action_type == 'replace_section':
                return FileModifier._replace_section(
                    filepath,
                    action['original_content'],
                    action['file_content'],
                )

            return False
        except Exception as e:
            logging.error(f"Error applying action: {e}")
            raise

    @staticmethod
    def _replace_section(
        filepath: str, original_content: str, new_content: List[str]
    ) -> bool:
        try:
            if not os.path.exists(filepath):
                logging.warning(
                    f"File does not exist for section replacement: {filepath}"
                )
                return False

            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()

            new_section_str = FileParser._safe_join(new_content).strip()
            nl = chr(10)
            crlf = chr(13) + chr(10)

            normalized_original = original_content.replace(crlf, nl).strip()
            normalized_content = content.replace(crlf, nl)

            match_original = nl.join(
                [line.strip() for line in normalized_original.split(nl) if line.strip()]
            )
            match_content = nl.join(
                [line.strip() for line in normalized_content.split(nl) if line.strip()]
            )

            if match_original in match_content:
                modified_content = content.replace(
                    original_content.strip(), new_section_str
                )
                with open(filepath, 'w', encoding='utf-8') as f:
                    f.write(modified_content)
                logging.info(f"Replaced section in: {filepath}")
                return True
            else:
                logging.warning(f"Original content not found in: {filepath}")
                if (original_content.strip().lower().replace(" ", "").replace("\t", "")
                        in content.lower().replace(" ", "").replace("\t", "")):
                    modified_content = content.replace(
                        original_content.strip(), new_section_str
                    )
                    with open(filepath, 'w', encoding='utf-8') as f:
                        f.write(modified_content)
                    logging.info(f"Replaced section in: {filepath} (flexible match)")
                    return True
                return False
        except Exception as e:
            logging.error(f"Error replacing section: {e}")
            raise
