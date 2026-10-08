"""File parsing — the aibuilder_change custom format."""

import re
import logging
import uuid
from typing import List, Dict, Any, Optional

LINE_DELIMITER = f"<<<AI_BUILDER_LINE_DELIMITER_{uuid.uuid4().hex}>>>"


class FileParser:
    """Parses the aibuilder_change custom format into structured changes."""

    @staticmethod
    def _safe_split(content: str) -> List[str]:
        content = content.replace("\\r\\n", "<<LITERAL_CRLF>>")
        content = content.replace("\\n", "<<LITERAL_NEWLINE>>")
        return content.replace(f"{chr(10)}", LINE_DELIMITER).split(f"{chr(10)}")

    @staticmethod
    def _safe_join(lines: List[str]) -> str:
        result = f"{chr(10)}".join(lines).replace(LINE_DELIMITER, f"{chr(10)}")
        result = result.replace("<<LITERAL_CRLF>>", "\\r\\n")
        result = result.replace("<<LITERAL_NEWLINE>>", "\\n")
        return result

    @staticmethod
    def escape_newline_sequences(content: str) -> str:
        """Replace newline-related sequences with unique tokens."""
        content = content.replace("\r\n", "<<LITERAL_CRLF>>")
        content = content.replace("\n", "<<LITERAL_NEWLINE>>")
        content = content.replace("\\r\\n", "<<LITERAL_ESCAPED_CRLF>>")
        content = content.replace("\\n", "<<LITERAL_ESCAPED_NEWLINE>>")
        return content

    @staticmethod
    def unescape_newline_sequences(content: str) -> str:
        """Restore newline-related sequences from tokens."""
        content = content.replace("<<LITERAL_ESCAPED_CRLF>>", "\\r\\n")
        content = content.replace("<<LITERAL_ESCAPED_NEWLINE>>", "\\n")
        content = content.replace("<<LITERAL_CRLF>>", "\r\n")
        content = content.replace("<<LITERAL_NEWLINE>>", "\n")
        return content

    @staticmethod
    def parse_custom_format(content: str) -> List[Dict[str, Any]]:
        """Parse aibuilder_change blocks from LLM output."""
        try:
            # Strip think blocks if present
            if "<think>" in content:
                split_content = re.split(r'<\/think>\s*\[?aibuilder', content, flags=re.DOTALL)
                if len(split_content) > 1:
                    content = "[aibuilder" + split_content[1]
                else:
                    content = split_content[0]

            # Strip everything before the first aibuilder_change tag
            content = re.sub(r'^.*?\[?aibuilder_change', '[aibuilder_change', content, flags=re.DOTALL)

            changes = []
            change_blocks = re.finditer(
                r'\[?aibuilder_change\s+file\s*=\s*"([^"]+)"\](.*?)(?=\[?aibuilder_change|$)',
                content,
                re.DOTALL
            )
            for block in change_blocks:
                file_path = block.group(1)
                actions = FileParser._parse_actions(block.group(2))
                changes.append({'file': file_path, 'actions': actions})
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
        pattern = r'\[?aibuilder_file_content\](.*?)\[?aibuilder_end_file_content\]'
        match = re.search(pattern, content, re.DOTALL)
        if match:
            file_content = match.group(1)
            return {
                'action': 'create_file',
                'file_content': file_content.split('\n')
            }
        return None

    @staticmethod
    def _parse_replace_file_action(content: str) -> Optional[Dict[str, Any]]:
        pattern = r'\[?aibuilder_file_content\](.*?)\[?aibuilder_end_file_content\]'
        match = re.search(pattern, content, re.DOTALL)
        if match:
            file_content = match.group(1)
            return {
                'action': 'replace_file',
                'file_content': file_content.split('\n')
            }
        return None

    @staticmethod
    def _parse_replace_section_action(content: str) -> Optional[Dict[str, Any]]:
        orig_pattern = r'\[?aibuilder_original_content\](.*?)\[?aibuilder_end_original_content\]'
        content_pattern = r'\[?aibuilder_file_content\](.*?)\[?aibuilder_end_file_content\]'
        orig_match = re.search(orig_pattern, content, re.DOTALL)
        content_match = re.search(content_pattern, content, re.DOTALL)
        if orig_match and content_match:
            return {
                'action': 'replace_section',
                'original_content': orig_match.group(1),
                'file_content': content_match.group(1).split('\n')
            }
        return None
