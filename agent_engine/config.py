"""Runtime configuration for the agentic engine."""
import os
import sys
import json
import logging
from typing import Optional

# Global settings cache set by app.py
_global_settings = {}


def set_global_settings(settings: dict):
    """Set the global settings dict for engine config access."""
    global _global_settings
    _global_settings = settings


def get_global_settings() -> dict:
    """Get the global settings dict."""
    return _global_settings


def _settings_get(key: str, default=None):
    """Get a value from global settings, falling back to os.environ.

    Checks in order:
    1. Global settings dict (lowercase key)
    2. Environment variable with AIB_ prefix (e.g., AIB_MAX_CONTEXT_TOKENS)
    3. Environment variable without prefix (e.g., MAX_CONTEXT_TOKENS)
    4. Provided default
    """
    val = _global_settings.get(key)
    if val is not None:
        return val
    # Fall back to env vars: first with AIB_ prefix, then without
    for env_key in (f"AIB_{key.upper()}", key.upper()):
        env_val = os.getenv(env_key)
        if env_val is not None:
            return env_val
    return default


def _read_status_file(output_dir: str) -> dict:
    """Read status.json from disk. Returns empty dict on failure."""
    status_file = os.path.join(output_dir, "status.json")
    try:
        with open(status_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def _write_status_file(output_dir: str, data: dict) -> None:
    """Atomically write status.json in the output directory."""
    status_file = os.path.join(output_dir, "status.json")
    tmp_file = status_file + ".tmp"
    try:
        with open(tmp_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_file, status_file)
    except Exception as e:
        logging.warning(f"Failed to write status file {status_file}: {e}")


class EngineConfig:
    """Runtime configuration for the agentic engine."""

    @staticmethod
    def get_root_directory() -> str:
        val = _settings_get("root_directory")
        return val if val else os.getcwd()

    @staticmethod
    def get_pending_tools_file() -> str:
        """Return the global pending tools file path (app-level, not per-project).
        
        Legacy — pending tools are now per-project under aib_instance/<pid>/tools/pending/.
        """
        return ""

    @staticmethod
    def get_log_file_path(root_dir: str) -> str:
        return os.path.join(root_dir, "aib_instance", "output", "utility.log")

    @staticmethod
    def get_custom_endpoint_url() -> Optional[str]:
        return _settings_get("custom_endpoint_url")

    @staticmethod
    def get_custom_api_key() -> Optional[str]:
        return _settings_get("custom_api_key")

    @staticmethod
    def get_custom_model_name() -> Optional[str]:
        return _settings_get("custom_model_name")

    @staticmethod
    def get_custom_verify_ssl() -> bool:
        val = _settings_get("custom_verify_ssl", False)
        if isinstance(val, bool):
            return val
        return str(val).lower() == "true"

    @staticmethod
    def get_timeout() -> int:
        val = _settings_get("timeout", 300)
        return int(val)

    @staticmethod
    def get_max_steps() -> int:
        val = _settings_get("max_steps", 500)
        return int(val)

    @staticmethod
    def get_jd_cli_path() -> Optional[str]:
        return _settings_get("jd_cli_path")

    @staticmethod
    def get_java_home() -> Optional[str]:
        return _settings_get("java_home")

    @staticmethod
    def get_dotnet_cli_path() -> Optional[str]:
        return _settings_get("dotnet_cli_path")

    @staticmethod
    def get_enabled_tools() -> Optional[list]:
        tools_str = _settings_get("AIB_ENABLED_TOOLS")
        if tools_str:
            try:
                return json.loads(tools_str)
            except Exception:
                return None
        return None

    @staticmethod
    def get_max_context_tokens() -> int:
        val = _settings_get("max_context_tokens", 0)
        return int(val)

    @staticmethod
    def get_max_output_tokens() -> int:
        val = _settings_get("max_output_tokens", 0)
        return int(val)

    @staticmethod
    def get_max_tool_result_length() -> int:
        val = _settings_get("max_tool_result_length", 10000)
        return int(val)

    @staticmethod
    def get_live_instruction(job_id: str, base_dir: Optional[str] = None) -> Optional[str]:
        """Read a pending live instruction from status.json.

        The instruction is consumed (removed from status.json) after reading,
        making this idempotent.
        """
        if base_dir:
            status = _read_status_file(base_dir)
        else:
            status = {}

        pending = status.get("pending_live_instruction")
        if pending:
            # Consume it
            if base_dir:
                try:
                    status.pop("pending_live_instruction")
                    _write_status_file(base_dir, status)
                except Exception:
                    pass
            return pending
        return None

    @staticmethod
    def get_resume_input(job_id: str, base_dir: Optional[str] = None) -> Optional[str]:
        """Read a pending resume input from status.json.

        The answer is consumed (removed from status.json) after reading,
        making this idempotent.
        """
        if base_dir:
            status = _read_status_file(base_dir)
        else:
            status = {}

        pending = status.get("pending_user_input")
        answer = None
        if pending and isinstance(pending, dict):
            answer = pending.get("answer")

        if answer:
            # Consume it
            if base_dir:
                try:
                    status["pending_user_input"] = {
                        "question": pending.get("question", ""),
                    }
                    _write_status_file(base_dir, status)
                except Exception:
                    pass
            return answer
        return None
