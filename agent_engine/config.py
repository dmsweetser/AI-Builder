"""Runtime configuration for the agentic engine."""
import os
import sys
import json
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


class EngineConfig:
    """Runtime configuration for the agentic engine."""

    @staticmethod
    def get_root_directory() -> str:
        val = _settings_get("root_directory")
        return val if val else os.getcwd()

    @staticmethod
    def get_pending_tools_file() -> str:
        """Return the global pending tools file path (app-level, not per-project)."""
        if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
            app_dir = sys._MEIPASS
        else:
            app_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        instance_dir = os.path.join(app_dir, "aib_instance", "output")
        return os.path.join(instance_dir, "pending_tools.json")

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
        """Read a live instruction file for a running job."""
        if base_dir:
            instruction_file = os.path.join(base_dir, "live_instruction.txt")
        else:
            instruction_file = os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                "aib_instance", "output", job_id, "live_instruction.txt"
            )
        if os.path.exists(instruction_file):
            try:
                with open(instruction_file, 'r') as f:
                    instruction = f.read().strip()
                with open(instruction_file, 'w') as f:
                    f.write('')
                return instruction if instruction else None
            except Exception:
                return None
        return None

    @staticmethod
    def get_resume_input(job_id: str, base_dir: Optional[str] = None) -> Optional[str]:
        """Read a resume input file for a paused agent run."""
        if base_dir:
            resume_file = os.path.join(base_dir, "resume_input.txt")
        else:
            resume_file = os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                "aib_instance", "output", job_id, "resume_input.txt"
            )
        if os.path.exists(resume_file):
            try:
                with open(resume_file, 'r', encoding='utf-8') as f:
                    user_input = f.read().strip()
                with open(resume_file, 'w', encoding='utf-8') as f:
                    f.write('')
                return user_input if user_input else None
            except Exception:
                return None
        return None
