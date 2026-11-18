"""edit_file tool — robust multi-strategy file editing.

Strategies (tried in order based on match_mode):
  1. Exact match — original_text found verbatim in content
  2. Whitespace-insensitive match — normalize all whitespace then match
  3. Case+whitespace-insensitive match — normalize case and whitespace then match
  4. Context-aware match — original_text found when ignoring leading/trailing whitespace per line
  5. Fuzzy line match — each line of original_text matched against a sliding window in content

match_mode parameter controls permissiveness:
  - case_sensitive (default): tries exact → whitespace → context-aware → fuzzy
  - whitespace_insensitive: normalizes whitespace first, then tries all strategies
  - case_and_whitespace_insensitive: normalizes case+whitespace, then tries all strategies
  - fuzzy: skips exact/whitespace, uses context-aware → fuzzy only
"""
import os
import re
from typing import Any, Dict, Optional
from agent_engine.tools.base import BaseTool, ToolResult
from agent_engine.security import ensure_under_root


class EditFileTool(BaseTool):
    name = "edit_file"
    description = (
        "Make a targeted edit to an existing file. "
        "Requires original_text to specify what to replace and new_text for the replacement. "
        "match_mode controls matching permissiveness: "
        "'case_sensitive' (default) = exact, then whitespace-insensitive, context-aware, fuzzy; "
        "'whitespace_insensitive' = normalizes whitespace first, then tries all strategies; "
        "'case_and_whitespace_insensitive' = normalizes case+whitespace, then tries all; "
        "'fuzzy' = skips exact/whitespace, uses context-aware and fuzzy matching. "
        "For multi-line edits, include the full lines. "
        "Use read_file first to get the exact original text."
    )
    parameters = {
        "path": "string",
        "original_text": "string",
        "new_text": "string",
        "match_mode": "string? (case_sensitive, whitespace_insensitive, case_and_whitespace_insensitive, fuzzy)",
    }

    def execute(self, params: Dict[str, str]) -> ToolResult:
        path = ensure_under_root(params["path"], self.root_dir)
        original = params["original_text"]
        new_text = params["new_text"]
        match_mode = params.get("match_mode", "case_sensitive").strip().lower()

        # Validate match_mode
        valid_modes = ("case_sensitive", "whitespace_insensitive", "case_and_whitespace_insensitive", "fuzzy")
        if match_mode not in valid_modes:
            return ToolResult(False, "", error=f"Invalid match_mode '{match_mode}'. Valid: {', '.join(valid_modes)}")

        if not os.path.isfile(path):
            return ToolResult(False, "", error=f"File not found: {params['path']}")

        try:
            with open(path, 'r', encoding='utf-8') as f:
                content = f.read()
        except (OSError, PermissionError) as e:
            return ToolResult(False, "", error=f"Cannot read file: {e}")

        # --- Determine which strategies to try based on match_mode ---
        # case_sensitive: exact, whitespace-insensitive, context-aware, fuzzy
        # whitespace_insensitive: normalize whitespace first, then try all
        # case_and_whitespace_insensitive: normalize case+whitespace first, then try all
        # fuzzy: skip exact/whitespace, go straight to fuzzy
        strategies = self._get_strategies_for_mode(match_mode, content, original, new_text, path)
        for strategy in strategies:
            result = strategy()
            if result is not None:
                return result

        # --- All strategies failed ---
        return ToolResult(False, "", error=self._build_error_message(content, original))

    def _get_strategies_for_mode(self, mode: str, content: str, original: str,
                                  new_text: str, path: str) -> list:
        """Return ordered list of strategy functions based on match_mode."""
        strategies = []

        if mode == "case_sensitive":
            strategies.append(lambda: self._exact_match(content, original, new_text, path))
            strategies.append(lambda: self._whitespace_insensitive_match(content, original, new_text, path))
            strategies.append(lambda: self._context_aware_match(content, original, new_text, path))
            strategies.append(lambda: self._fuzzy_line_match(content, original, new_text, path))

        elif mode == "whitespace_insensitive":
            # First normalize whitespace and try exact match on normalized
            strategies.append(lambda: self._whitespace_insensitive_match(content, original, new_text, path))
            strategies.append(lambda: self._exact_match(content, original, new_text, path))
            strategies.append(lambda: self._context_aware_match(content, original, new_text, path))
            strategies.append(lambda: self._fuzzy_line_match(content, original, new_text, path))

        elif mode == "case_and_whitespace_insensitive":
            strategies.append(lambda: self._case_and_whitespace_insensitive_match(content, original, new_text, path))
            strategies.append(lambda: self._whitespace_insensitive_match(content, original, new_text, path))
            strategies.append(lambda: self._exact_match(content, original, new_text, path))
            strategies.append(lambda: self._context_aware_match(content, original, new_text, path))
            strategies.append(lambda: self._fuzzy_line_match(content, original, new_text, path))

        elif mode == "fuzzy":
            strategies.append(lambda: self._context_aware_match(content, original, new_text, path))
            strategies.append(lambda: self._fuzzy_line_match(content, original, new_text, path))

        return strategies

    def _exact_match(self, content: str, original: str, new_text: str, path: str) -> Optional[ToolResult]:
        """Exact match strategy."""
        if original in content:
            new_content = content.replace(original, new_text, 1)
            return self._write_and_verify(path, new_content, path)
        return None

    def _case_and_whitespace_insensitive_match(self, content: str, original: str,
                                                new_text: str, path: str) -> Optional[ToolResult]:
        """Match ignoring both case and whitespace."""
        norm_orig = re.sub(r'\s+', ' ', original.strip()).lower()
        norm_content = re.sub(r'\s+', ' ', content).lower()

        if norm_orig in norm_content:
            # Build regex that matches with flexible whitespace and case-insensitive
            tokens = re.findall(r'\S+', original)
            if tokens:
                pattern_str = r'\s+'.join(re.escape(t) for t in tokens)
                pattern = re.compile(pattern_str, re.IGNORECASE | re.DOTALL)
                match = pattern.search(content)
                if match:
                    new_content = content[:match.start()] + new_text + content[match.end():]
                    return self._write_and_verify(path, new_content, path)
        return None

    def _write_and_verify(self, path: str, new_content: str, original_path: str) -> ToolResult:
        """Write content and verify it actually changed."""
        
        try:
            with open(path, 'w', encoding='utf-8') as f:
                f.write(new_content)
            # Verify the file content actually changed
            with open(path, 'r', encoding='utf-8') as f:
                actual = f.read()
            if actual != new_content:
                return ToolResult(False, "",
                                  error="File verification failed: content does not match after write")
            return ToolResult(True, f"Edited {original_path}",
                              summary=f"Replaced section in: {original_path}")
        except OSError as e:
            return ToolResult(False, "", error=f"Cannot write file: {e}")

    def _whitespace_insensitive_match(self, content: str, original: str,
                                       new_text: str, path: str) -> Optional[ToolResult]:
        """Try matching after normalizing all whitespace to single spaces."""
        norm_orig = re.sub(r'\s+', ' ', original.strip())
        norm_content = re.sub(r'\s+', ' ', content)

        if norm_orig in norm_content:
            # Found normalized match — build a regex that matches the original
            # text with flexible whitespace between tokens
            # Split original into non-whitespace tokens, join with \s+
            tokens = re.findall(r'\S+', original)
            if tokens:
                pattern_str = r'\s+'.join(re.escape(t) for t in tokens)
                pattern = re.compile(pattern_str, re.DOTALL)
                match = pattern.search(content)
                if match:
                    new_content = content[:match.start()] + new_text + content[match.end():]
                    return self._write_and_verify(path, new_content, path)
        return None

    def _context_aware_match(self, content: str, original: str,
                              new_text: str, path: str) -> Optional[ToolResult]:
        """Match original_text when ignoring leading/trailing whitespace on each line."""
        orig_lines = original.splitlines()
        content_lines = content.splitlines()

        if not orig_lines or not content_lines:
            return None

        for i in range(len(content_lines) - len(orig_lines) + 1):
            match = True
            for j, orig_line in enumerate(orig_lines):
                if i + j >= len(content_lines):
                    match = False
                    break
                if content_lines[i + j].strip() != orig_line.strip():
                    match = False
                    break

            if match:
                # Found context-aware match — replace the actual lines
                start = sum(len(l) + 1 for l in content_lines[:i])
                end_line_idx = i + len(orig_lines)
                end = start
                for k in range(i, end_line_idx):
                    end += len(content_lines[k]) + 1

                new_content = content[:start] + new_text + content[end:]
                return self._write_and_verify(path, new_content, path)
        return None

    def _fuzzy_line_match(self, content: str, original: str,
                           new_text: str, path: str) -> Optional[ToolResult]:
        """Match original lines against a sliding window, allowing minor whitespace differences."""
        orig_lines = [l.strip() for l in original.splitlines() if l.strip()]
        content_lines = content.splitlines()

        if not orig_lines or not content_lines:
            return None

        for i in range(len(content_lines) - len(orig_lines) + 1):
            match = True
            for j, orig_line in enumerate(orig_lines):
                if i + j >= len(content_lines):
                    match = False
                    break
                content_line = content_lines[i + j].strip()
                if orig_line not in content_line and content_line not in orig_line:
                    if not self._lines_similar(orig_line, content_line):
                        match = False
                        break

            if match:
                # Found fuzzy match — replace the lines
                start = sum(len(l) + 1 for l in content_lines[:i])
                end_line_idx = i + len(orig_lines)
                end = start
                for k in range(i, end_line_idx):
                    end += len(content_lines[k]) + 1

                new_content = content[:start] + new_text + content[end:]
                return self._write_and_verify(path, new_content, path)
        return None

    @staticmethod
    def _lines_similar(a: str, b: str) -> bool:
        """Check if two lines are similar enough to be considered a match."""
        a_norm = re.sub(r'\s+', ' ', a.strip())
        b_norm = re.sub(r'\s+', ' ', b.strip())
        if a_norm == b_norm:
            return True
        if len(a_norm) > 0 and len(b_norm) > 0:
            shorter, longer = (a_norm, b_norm) if len(a_norm) < len(b_norm) else (b_norm, a_norm)
            if len(shorter) >= 5:
                matches = 0
                si = 0
                for c in shorter:
                    idx = longer.find(c, si)
                    if idx >= 0:
                        matches += 1
                        si = idx + 1
                if matches / len(shorter) >= 0.8:
                    return True
        return False

    def _build_error_message(self, content: str, original: str) -> str:
        """Build a helpful error message showing what was found."""
        lines = content.splitlines()
        orig_lines = original.splitlines()

        msg = (
            "Original text not found in file. "
            "Here are some suggestions:\n"
        )

        # Show first few lines of content for context
        preview_lines = lines[:10]
        preview = '\n'.join(preview_lines)
        if len(lines) > 10:
            preview += f"\n... ({len(lines) - 10} more lines)"
        msg += f"\nFile preview (first 10 lines):\n{preview}\n"

        # Show what was expected
        msg += f"\nExpected text to replace:\n{original}\n"

        # Check if the original text is close to any line
        if orig_lines and lines:
            best_line = None
            best_score = 0
            for i, line in enumerate(lines[:20]):  # Check first 20 lines
                score = self._line_similarity(original.strip(), line.strip())
                if score > best_score:
                    best_score = score
                    best_line = (i + 1, line)

            if best_line and best_score > 0.3:
                msg += (
                    f"\nClosest match (line {best_line[0]}, similarity {best_score:.0%}):\n"
                    f"  {best_line[1]}\n"
                    f"  Expected: {original.strip()[:80]}{'...' if len(original) > 80 else ''}"
                )

        return msg

    @staticmethod
    def _line_similarity(a: str, b: str) -> float:
        """Compute similarity ratio between two strings (0.0 to 1.0)."""
        if not a or not b:
            return 0.0
        a_set = set(a)
        b_set = set(b)
        intersection = a_set & b_set
        union = a_set | b_set
        if not union:
            return 0.0
        return len(intersection) / len(union)