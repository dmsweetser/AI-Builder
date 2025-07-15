import json
import os
import re

def extract_json_content(text):
    # Regular expression to find content between ```json and ```
    match = re.search(r'```json\s*(.*?)\s*```', text, re.DOTALL)
    if match:
        # Return the matched JSON content
        return match.group(1).strip()
    # If no match is found, return the original text
    return text

def load_instructions(json_path):
    with open(json_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # Extract only the JSON content between ```json and ```
    json_content = extract_json_content(content)

    # Parse the JSON content
    return json.loads(json_content)['changes']

def apply_modifications(instruction_file):
    changes = load_instructions(instruction_file)
    for change in changes:
        filepath = change['file']
        if not os.path.isfile(filepath):
            print(f"[WARNING] File not found: {filepath}")
            continue

        with open(filepath, 'r', encoding='utf-8') as f:
            lines = f.read().splitlines()

        for action in change['actions']:
            action_type = action['action']
            if action_type == 'replace_between_markers':
                lines = replace_between_markers(lines, action['start_marker'], action['end_marker'], action['new_content'])
            elif action_type == 'append':
                # Check for existing lines before appending
                new_lines = [line for line in action['content'] if line not in lines]
                lines.extend(new_lines)
            elif action_type == 'prepend':
                # Check for existing lines before prepending
                new_lines = [line for line in action['content'] if line not in lines]
                lines = new_lines + lines
            elif action_type == 'regex_replace':
                lines = regex_replace(lines, action['pattern'], action['replacement'])
            elif action_type == 'replace_line_containing':
                lines = replace_line_containing(lines, action['match_substring'], action['replacement_line'])
            else:
                print(f"[WARNING] Unknown action type: {action_type}")

        with open(filepath, 'w', encoding='utf-8') as f:
            f.write("\n".join(lines) + "\n")
        print(f"[INFO] Updated: {filepath}")

def replace_between_markers(lines, start_marker, end_marker, new_content):
    inside_block = False
    new_lines = []
    for line in lines:
        if start_marker in line:
            new_lines.append(line)
            new_lines.extend(new_content)
            inside_block = True
        elif end_marker in line and inside_block:
            new_lines.append(line)
            inside_block = False
        elif not inside_block:
            new_lines.append(line)
    return new_lines

def regex_replace(lines, pattern, replacement):
    compiled = re.compile(pattern)
    return [compiled.sub(replacement, line) for line in lines]

def replace_line_containing(lines, match_substring, replacement_line):
    return [
        replacement_line if match_substring in line else line
        for line in lines
    ]

if __name__ == "__main__":
    import sys
    if len(sys.argv) != 2:
        print("Usage: python file_mod_engine.py modifications.json")
        sys.exit(1)
    instruction_file = sys.argv[1]
    apply_modifications(instruction_file)
