#!/usr/bin/env python3
"""Diagnostics runner — execute any AI-Builder tool directly.

Runs a tool against a project's root_dir in the exact environment
the agent engine would use, capturing full output including error
details and injected source code.

Usage:
    # Run a built-in tool
    python -m diagnostics.diagnose --tool read_file --params '{"path": "src/main.py"}' --root /path/to/project

    # Run a project-local (custom) tool
    python -m diagnostics.diagnose --tool my_custom_tool --params '{"path": "src/main.py"}' --root /path/to/project

    # List all available tools
    python -m diagnostics.diagnose --list

    # Run with a specific project output dir (for custom tool resolution)
    python -m diagnostics.diagnose --tool read_file --params '{"path": "src/main.py"}' --root /path/to/project --output-dir /path/to/project/aib_instance/proj123/output

    # Run with verbose output (show full source code for failed tools)
    python -m diagnostics.diagnose --tool edit_file --params '{"path": "src/main.py", "original_text": "...", "new_text": "..."}' --root /path/to/project --verbose
"""

import argparse
import json
import os
import sys
import traceback
from typing import Any, Dict, Optional


def resolve_project_root(root_dir: str) -> str:
    """Resolve the project root directory, walking up if needed."""
    root_dir = os.path.abspath(root_dir)
    # If the root doesn't have agent_engine, walk up looking for it
    if not os.path.isdir(os.path.join(root_dir, "agent_engine")):
        candidate = root_dir
        for _ in range(10):
            parent = os.path.dirname(candidate)
            if parent == candidate:
                break
            candidate = parent
            if os.path.isdir(os.path.join(candidate, "agent_engine")):
                root_dir = candidate
                break
    return root_dir


def ensure_agent_engine_on_path(root_dir: str) -> None:
    """Add the project root to sys.path so agent_engine imports work."""
    if root_dir not in sys.path:
        sys.path.insert(0, root_dir)
    # Also add shim modules for common LLM-generated import patterns
    if "tools.base" not in sys.modules:
        try:
            from agent_engine.tools.base import BaseTool, ToolResult
            import types
            _shim = types.ModuleType("tools.base")
            _shim.BaseTool = BaseTool
            _shim.ToolResult = ToolResult
            sys.modules["tools.base"] = _shim
        except ImportError:
            pass
    if "base" not in sys.modules:
        try:
            from agent_engine.tools.base import BaseTool, ToolResult
            import types
            _shim = types.ModuleType("base")
            _shim.BaseTool = BaseTool
            _shim.ToolResult = ToolResult
            sys.modules["base"] = _shim
        except ImportError:
            pass


def list_tools(root_dir: str) -> None:
    """List all available tools (built-in + project-local)."""
    root_dir = resolve_project_root(root_dir)
    ensure_agent_engine_on_path(root_dir)

    from agent_engine.tools import _BUILTIN_TOOL_CLASSES, ToolRegistry

    registry = ToolRegistry()

    # Determine project output dir for custom tool loading
    project_output_dir = os.path.join(root_dir, "aib_instance", "output")
    if not os.path.isdir(project_output_dir):
        # Try to find an existing project
        aib_instance = os.path.join(root_dir, "aib_instance")
        if os.path.isdir(aib_instance):
            for entry in sorted(os.listdir(aib_instance)):
                candidate = os.path.join(aib_instance, entry, "output")
                if os.path.isdir(candidate):
                    project_output_dir = candidate
                    break

    # List built-in tools
    print("=" * 60)
    print("AVAILABLE TOOLS")
    print("=" * 60)
    print(f"\nProject root: {root_dir}")
    print(f"Project output dir: {project_output_dir}")
    print()

    print("Built-in tools:")
    print("-" * 40)
    for name in sorted(_BUILTIN_TOOL_CLASSES.keys()):
        cls = _BUILTIN_TOOL_CLASSES[name]
        try:
            instance = cls("/tmp")
            desc = instance.description[:80].replace("\n", " ")
            print(f"  {name:30s}  {desc}")
        except Exception:
            print(f"  {name:30s}  [failed to load]")

    # List project-local tools
    print()
    print("Project-local tools:")
    print("-" * 40)
    loader = None
    try:
        loader = registry._get_or_create_loader(project_output_dir)
        tool_names = loader.get_tool_names()
        if tool_names:
            for name in sorted(tool_names):
                try:
                    cls = loader._dynamic_tools[name]
                    instance = cls(root_dir, output_dir=project_output_dir)
                    desc = instance.description[:80].replace("\n", " ")
                    print(f"  {name:30s}  {desc}")
                except Exception:
                    print(f"  {name:30s}  [failed to load]")
        else:
            print("  (none)")
    except Exception as e:
        print(f"  (error loading project tools: {e})")

    # Show pending tools
    print()
    print("Pending tools:")
    print("-" * 40)
    try:
        if loader is None:
            loader = registry._get_or_create_loader(project_output_dir)
        pending = loader.get_pending_tools()
        if pending:
            for tool in pending:
                desc = tool.get("description", "")[:60].replace("\n", " ")
                print(f"  {tool['name']:30s}  {desc}")
        else:
            print("  (none)")
    except Exception:
        print("  (error loading pending tools)")


def run_tool(
    tool_name: str,
    params: Dict[str, Any],
    root_dir: str,
    output_dir: Optional[str] = None,
    verbose: bool = False,
) -> Dict[str, Any]:
    """Run a tool and return the full result."""
    root_dir = resolve_project_root(root_dir)
    ensure_agent_engine_on_path(root_dir)

    from agent_engine.tools import _BUILTIN_TOOL_CLASSES, ToolRegistry
    from agent_engine.tools.base import ToolResult
    from agent_engine.security import SecurityError, ToolError

    registry = ToolRegistry()

    # Determine project output dir
    if output_dir is None:
        output_dir = os.path.join(root_dir, "aib_instance", "output")
        if not os.path.isdir(output_dir):
            aib_instance = os.path.join(root_dir, "aib_instance")
            if os.path.isdir(aib_instance):
                for entry in sorted(os.listdir(aib_instance)):
                    candidate = os.path.join(aib_instance, entry, "output")
                    if os.path.isdir(candidate):
                        output_dir = candidate
                        break

    result = {
        "tool": tool_name,
        "root_dir": root_dir,
        "output_dir": output_dir,
        "params": params,
        "success": False,
        "content": "",
        "error": "",
        "summary": "",
    }

    # Try to create and execute the tool
    try:
        tool_instance = registry._create_tool_instance(
            tool_name, root_dir, output_dir, disabled_tools=set(), job_id="diagnostics"
        )
    except Exception as e:
        result["error"] = f"Failed to create tool instance: {e}"
        result["traceback"] = traceback.format_exc()
        return result

    if tool_instance is None:
        available = sorted(_BUILTIN_TOOL_CLASSES.keys())
        result["error"] = f"Tool '{tool_name}' not found. Available: {available}"
        return result

    # Show tool definition
    if verbose:
        print()
        print("=" * 60)
        print(f"TOOL: {tool_name}")
        print("=" * 60)
        print(f"  Class:    {tool_instance.__class__.__name__}")
        print(f"  Root:     {root_dir}")
        print(f"  Output:   {output_dir}")
        print(f"  Params:   {json.dumps(params, indent=4)}")
        print()

    # Execute the tool
    try:
        tool_result = registry.execute(
            tool_name=tool_name,
            params=params,
            root_dir=root_dir,
            project_output_dir=output_dir,
            disabled_tools=set(),
            job_id="diagnostics",
        )

        result["success"] = tool_result.success
        result["content"] = tool_result.content
        result["error"] = tool_result.error
        result["summary"] = tool_result.summary

        if verbose:
            print("-" * 60)
            print("RESULT")
            print("-" * 60)
            print(f"  Success: {tool_result.success}")
            if tool_result.summary:
                print(f"  Summary: {tool_result.summary}")
            if tool_result.error:
                print(f"  Error:   {tool_result.error}")
            if tool_result.content:
                print()
                print("  Content:")
                print("  " + "-" * 58)
                content = tool_result.content
                # Truncate very long output for display
                if len(content) > 50000:
                    content = content[:50000] + f"\n  ... (truncated, {len(tool_result.content)} chars total)"
                for line in content.split("\n"):
                    print(f"  {line}")
                print("  " + "-" * 58)
            print()

    except SecurityError as e:
        result["error"] = f"SecurityError: {e}"
        result["traceback"] = traceback.format_exc()
        if verbose:
            print(f"\nSecurityError: {e}")
            print(traceback.format_exc())

    except ToolError as e:
        result["error"] = f"ToolError: {e}"
        result["traceback"] = traceback.format_exc()
        if verbose:
            print(f"\nToolError: {e}")
            print(traceback.format_exc())

    except Exception as e:
        result["error"] = f"Unexpected error: {e}"
        result["traceback"] = traceback.format_exc()
        if verbose:
            print(f"\nUnexpected error: {e}")
            print(traceback.format_exc())

    return result


def main():
    parser = argparse.ArgumentParser(
        description="Diagnostics runner — execute any AI-Builder tool directly.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--tool", "-t",
        type=str,
        help="Tool name to execute (e.g. read_file, edit_file, grep_code)",
    )
    parser.add_argument(
        "--params", "-p",
        type=str,
        default="{}",
        help="JSON object of tool parameters (default: {})",
    )
    parser.add_argument(
        "--root", "-r",
        type=str,
        default=".",
        help="Project root directory (default: current dir)",
    )
    parser.add_argument(
        "--output-dir", "-o",
        type=str,
        default=None,
        help="Project output directory (auto-detected if omitted)",
    )
    parser.add_argument(
        "--list", "-l",
        action="store_true",
        help="List all available tools and exit",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Show verbose output (tool definition, full result)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output result as JSON (for piping to other tools)",
    )

    args = parser.parse_args()

    if args.list:
        list_tools(args.root)
        return

    if not args.tool:
        parser.error("--tool is required (or use --list)")
        return

    # Parse parameters
    try:
        params = json.loads(args.params)
    except json.JSONDecodeError as e:
        print(f"Error: Invalid JSON for --params: {e}", file=sys.stderr)
        sys.exit(1)

    if not isinstance(params, dict):
        print("Error: --params must be a JSON object (dict)", file=sys.stderr)
        sys.exit(1)

    # Run the tool
    result = run_tool(
        tool_name=args.tool,
        params=params,
        root_dir=args.root,
        output_dir=args.output_dir,
        verbose=args.verbose,
    )

    if args.json:
        # Output clean JSON for programmatic consumption
        output = {
            "tool": result["tool"],
            "success": result["success"],
            "content": result["content"],
            "error": result["error"],
            "summary": result["summary"],
        }
        if result.get("traceback"):
            output["traceback"] = result["traceback"]
        print(json.dumps(output, indent=2, ensure_ascii=False))
    else:
        # Human-readable output
        print()
        print("=" * 60)
        print(f"DIAGNOSTICS: {result['tool']}")
        print("=" * 60)
        print(f"  Root dir:   {result['root_dir']}")
        print(f"  Output dir: {result['output_dir']}")
        print(f"  Params:     {json.dumps(result['params'], indent=4)}")
        print()
        print("-" * 60)
        print("RESULT")
        print("-" * 60)
        print(f"  Success: {result['success']}")
        if result["summary"]:
            print(f"  Summary: {result['summary']}")
        if result["error"]:
            print(f"  Error:   {result['error']}")
        if result["content"]:
            print()
            print("  Content:")
            print("  " + "-" * 58)
            content = result["content"]
            if len(content) > 50000:
                content = content[:50000] + f"\n  ... (truncated, {len(result['content'])} chars total)"
            for line in content.split("\n"):
                print(f"  {line}")
            print("  " + "-" * 58)
        if result.get("traceback"):
            print()
            print("  Traceback:")
            print("  " + "-" * 58)
            for line in result["traceback"].split("\n"):
                print(f"  {line}")
            print("  " + "-" * 58)
        print()


if __name__ == "__main__":
    main()
