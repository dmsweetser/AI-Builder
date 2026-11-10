"""edit_file tool — robust multi-strategy file editing.

Strategies (tried in order):
  0. Line-range replacement — replace lines line_start..line_end (1-indexed)
  1. Exact match — original_text found verbatim in content
  2. Whitespace-insensitive match — collapse all whitespace to single spaces, then match
  3. Flexible whitespace match — allow any amount of whitespace between words
  4. Context-aware match — original_text found when ignoring leading/trailing whitespace per line
  5. Fuzzy line match — each line of original_text matched against a sliding window in content
  6. Character-level fuzzy match — sliding window with character similarity scoring
"""
import os
import re
import time
from typing import Any, Dict, Optional
from agent_engine.tools.base import BaseTool, ToolResult
from agent_engine.tools.file_lock import FileLock
from agent_engine.security import ensure_under_root


class EditFileTool(BaseTool):
    name = "edit_file"
    description = (
        "Make a targeted edit to an existing file. "
        "Specify the exact original text (original_text) and the replacement text (new_text). "
        "For multi-line edits, include the full lines. "
        "Use read_file first to get the exact original text. "
        "Strategies (tried in order): exact match, whitespace-insensitive, "
        "line-range replacement (line_start/line_end), context-aware, fuzzy line match. "
        "You can also use line_start and line_end (1-indexed, inclusive) to replace "
        "specific lines directly."
    )
    parameters = {
        "path": "string",
        "original_text": "string",
        "new_text": "string",
    }

    def execute(self, params: Dict[str, str]) -> ToolResult:
        path = ensure_under_root(params["path"], self.root_dir)
        original = params["original_text"]
        new_text = params["new_text"]

        if not os.path.isfile(path):
            return ToolResult(False, "", error=f"File not found: {params['path']}")

        try:
            with open(path, 'r', encoding='utf-8') as f:
                content = f.read()
        except (OSError, PermissionError) as e:
            return ToolResult(False, "", error=f"Cannot read file: {e}")

        # --- Strategy 0: Line-range replacement (if line_start/line_end provided) ---
        line_start = params.get("line_start", "").strip()
        line_end = params.get("line_end", "").strip()
        if line_start and line_end:
            try:
                ls = int(line_start) - 1  # convert to 0-indexed
                le = int(line_end)
                lines = content.splitlines()
                if 0 <= ls < le <= len(lines):
                    # Reconstruct with original line endings
                    raw_lines = content.splitlines(True)
                    replacement_lines = new_text.splitlines(True)
                    # Ensure last replacement line has newline if original did
                    if raw_lines and raw_lines[-1].endswith('\n') and replacement_lines and not replacement_lines[-1].endswith('\n'):
                        replacement_lines[-1] += '\n'
                    new_content = ''.join(raw_lines[:ls]) + ''.join(replacement_lines) + ''.join(raw_lines[le:])
                    if new_content != content:
                        return self._write_and_verify(path, new_content, params['path'])
            except (ValueError, IndexError):
                pass  # Fall through to other strategies

        # --- Strategy 1: Exact match ---
        if original in content:
            new_content = content.replace(original, new_text, 1)
            return self._write_and_verify(path, new_content, params['path'])

        # --- Strategy 2: Whitespace-insensitive match ---
        result = self._whitespace_insensitive_match(content, original, new_text, path)
        if result is not None:
            return result

        # --- Strategy 3: Flexible whitespace match ---
        result = self._flexible_whitespace_match(content, original, new_text, path)
        if result is not None:
            return result

        # --- Strategy 4: Context-aware match (ignore leading/trailing whitespace per line) ---
        result = self._context_aware_match(content, original, new_text, path)
        if result is not None:
            return result

        # --- Strategy 5: Fuzzy line match ---
        result = self._fuzzy_line_match(content, original, new_text, path)
        if result is not None:
            return result

        # --- Strategy 6: Character-level fuzzy match ---
        result = self._character_fuzzy_match(content, original, new_text, path)
        if result is not None:
            return result

        # --- All strategies failed ---
        return ToolResult(False, "", error=self._build_error_message(content, original))

    def _write_and_verify(self, path: str, new_content: str, original_path: str) -> ToolResult:
        """Write content and verify it actually changed."""
        # Use file locking to prevent concurrent writes from corrupting files
        lock = FileLock(path)
        try:
            lock.acquire()
        except TimeoutError:
            return ToolResult(False, "", error=f"Could not acquire write lock for {original_path}")

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
        finally:
            lock.release()

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

    def _flexible_whitespace_match(self, content: str, original: str,
                                    new_text: str, path: str) -> Optional[ToolResult]:
        """Match original_text allowing any amount of whitespace between words/tokens."""
        # Split original into words (preserving internal structure like quotes, operators)
        orig_words = re.findall(r'\S+', original)
        if not orig_words:
            return None

        # Build a regex that allows flexible whitespace between each word
        # Each word boundary allows any amount of whitespace (including newlines)
        pattern_str = r'\s*'.join(re.escape(w) for w in orig_words)
        pattern = re.compile(pattern_str, re.DOTALL)

        # Search for the best match (prefer longest match)
        best_match = None
        for match in pattern.finditer(content):
            if best_match is None or (match.end() - match.start()) > (best_match.end() - best_match.start()):
                best_match = match

        if best_match:
            new_content = content[:best_match.start()] + new_text + content[best_match.end():]
            return self._write_and_verify(path, new_content, path)
        return None

    def _character_fuzzy_match(self, content: str, original: str,
                                new_text: str, path: str) -> Optional[ToolResult]:
        """Sliding window match with character-level similarity scoring.

        Tries progressively longer windows in content until a match with
        sufficient similarity is found.
        """
        orig_stripped = original.strip()
        if not orig_stripped:
            return None

        content_lines = content.splitlines(True)
        orig_lines = [l for l in original.splitlines(True) if l.strip()]

        if not orig_lines:
            return None

        # Target: total character count of original (ignoring whitespace)
        orig_target_len = sum(len(l.strip()) for l in orig_lines)
        if orig_target_len == 0:
            return None

        # Try sliding window over content, character by character
        # But do it line-by-line for efficiency: accumulate lines until
        # the stripped length is close to orig_target_len
        best_match = None
        best_score = 0.0

        for start_line in range(len(content_lines)):
            accumulated = ''
            for end_line_offset in range(min(50, len(content_lines) - start_line)):
                accumulated += content_lines[start_line + end_line_offset]
                acc_stripped = accumulated.strip()

                # Early exit if we've gone way past the target length
                if len(acc_stripped) > orig_target_len * 3:
                    break

                # Check if lengths are in a reasonable range
                if len(acc_stripped) < orig_target_len * 0.5:
                    continue

                # Compute similarity between accumulated text and original
                score = self._text_similarity(acc_stripped, orig_stripped)
                if score > best_score and score >= 0.65:
                    best_score = score
                    best_match = accumulated

        if best_match and best_score >= 0.65:
            # Find where this match occurs in content
            # Use the accumulated text to find the exact position
            idx = content.find(best_match)
            if idx >= 0:
                end_idx = idx + len(best_match)
                new_content = content[:idx] + new_text + content[end_idx:]
                return self._write_and_verify(path, new_content, path)

        return None

    @staticmethod
    def _text_similarity(a: str, b: str) -> float:
        """Compute similarity ratio between two strings using character-level comparison.

        Uses a combination of:
        - Longest common subsequence ratio
        - Character frequency similarity
        - Prefix/suffix match bonus
        """
        if not a or not b:
            return 0.0

        # Quick check: if one is a substring of the other, high score
        if a in b or b in a:
            shorter, longer = (a, b) if len(a) < len(b) else (b, a)
            return 0.8 + 0.2 * (len(shorter) / len(longer))

        # LCS-based similarity
        lcs_len = EditFileTool._lcs_length(a, b)
        lcs_ratio = 2.0 * lcs_len / (len(a) + len(b)) if (len(a) + len(b)) > 0 else 0.0

        # Character frequency similarity (Jaccard-like)
        freq_a = {}
        freq_b = {}
        for c in a:
            freq_a[c] = freq_a.get(c, 0) + 1
        for c in b:
            freq_b[c] = freq_b.get(c, 0) + 1

        all_chars = set(freq_a.keys()) | set(freq_b.keys())
        if all_chars:
            intersection = sum(min(freq_a.get(c, 0), freq_b.get(c, 0)) for c in all_chars)
            union = sum(freq_a.values()) + sum(freq_b.values())
            freq_ratio = intersection / union
        else:
            freq_ratio = 0.0

        # Weighted combination
        score = 0.6 * lcs_ratio + 0.4 * freq_ratio
        return min(score, 1.0)

    @staticmethod
    def _lcs_length(a: str, b: str) -> int:
        """Compute the length of the longest common subsequence of a and b.

        Uses space-optimized DP (only two rows) for memory efficiency.
        """
        m, n = len(a), len(b)
        if m == 0 or n == 0:
            return 0

        # Use two rows instead of full matrix
        prev = [0] * (n + 1)
        curr = [0] * (n + 1)

        for i in range(1, m + 1):
            for j in range(1, n + 1):
                if a[i - 1] == b[j - 1]:
                    curr[j] = prev[j - 1] + 1
                else:
                    curr[j] = max(prev[j], curr[j - 1])
            prev, curr = curr, [0] * (n + 1)

        return prev[n]

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

        # Show first 20 lines of content for context
        preview_lines = lines[:20]
        preview = '\n'.join(preview_lines)
        if len(lines) > 20:
            preview += f"\n... ({len(lines) - 20} more lines)"
        msg += f"\nFile preview (first 20 lines):\n{preview}\n"

        # Show what was expected
        msg += f"\nExpected text to replace:\n{original}\n"

        # Check if the original text is close to any line
        if orig_lines and lines:
            best_line = None
            best_score = 0
            for i, line in enumerate(lines[:30]):  # Check first 30 lines
                score = self._text_similarity(original.strip(), line.strip())
                if score > best_score:
                    best_score = score
                    best_line = (i + 1, line)

            if best_line and best_score > 0.3:
                msg += (
                    f"\nClosest match (line {best_line[0]}, similarity {best_score:.0%}):\n"
                    f"  {best_line[1]}\n"
                    f"  Expected: {original.strip()[:80]}{'...' if len(original) > 80 else ''}"
                )

        # Also check if the original text is close to any multi-line section
        if len(orig_lines) > 1 and len(lines) >= len(orig_lines):
            for i in range(min(len(lines) - len(orig_lines) + 1, 20)):
                section = '\n'.join(lines[i:i+len(orig_lines)])
                score = self._text_similarity(section.strip(), original.strip())
                if score > 0.4:
                    msg += (
                        f"\nClose multi-line match (lines {i+1}-{i+len(orig_lines)}, similarity {score:.0%}):\n"
                        f"  {section[:200]}{'...' if len(section) > 200 else ''}\n"
                    )

        # Suggest using line_start/line_end as a fallback
        msg += (
            "\nTIP: If you know the approximate line numbers, you can use "
            "line_start and line_end parameters instead of original_text.\n"
        )

        return msg
