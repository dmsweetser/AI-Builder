"""Action serialization — save/load action lists to text files."""

import re
import logging
from typing import List, Dict, Any

from oneshot_engine.parser import FileParser


class ActionManager:
    """Serializes and deserializes action lists to/from text files."""

    @staticmethod
    def save_actions(actions: List[Dict[str, Any]], filepath: str) -> None:
        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                for action in actions:
                    f.write(f"File: {action['file']}\n")
                    f.write(f"Action: {action['action']['action']}\n")
                    if action['action']['action'] in ('create_file', 'replace_file', 'replace_section'):
                        f.write(f"Content:\n")
                        f.write(FileParser._safe_join(action['action']['file_content']) + "\n")
                    if action['action']['action'] == 'replace_section':
                        f.write(f"Original Content:\n{action['action']['original_content']}\n")
                    f.write("\n")
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
                    r'File: (.*?)\nAction: (.*?)\n(?:Content:\n(.*?)(?=\nFile:|\Z))?'
                    r'(?:Original Content:\n(.*?)(?=\nFile:|\Z))?',
                    content,
                    re.DOTALL,
                )
                for block in action_blocks:
                    file = block.group(1)
                    action_type = block.group(2)
                    file_content = (
                        FileParser._safe_split(block.group(3)) if block.group(3) else []
                    )
                    original_content = block.group(4) if block.group(4) else None
                    action = {'action': action_type}
                    if action_type in ('create_file', 'replace_file', 'replace_section'):
                        action['file_content'] = file_content
                    if action_type == 'replace_section':
                        action['original_content'] = original_content
                    actions.append({'file': file, 'action': action})
            logging.info(f"Loaded actions from {filepath}")
            return actions
        except Exception as e:
            logging.error(f"Error loading actions: {e}")
            raise
