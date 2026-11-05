"""Tests for create_tool parameter parsing edge cases.

Reproduces the exact flow: LLM response -> _strip_code_blocks -> 
extract tool blocks -> parse_tool_calls -> validate_tool_params.
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from agent_engine.engine import parse_tool_calls, _strip_code_blocks
from agent_engine.security import validate_tool_params, ToolError


def test_parse_create_tool_basic():
    """Parse a create_tool call with 4 parameters."""
    response = """[TOOL_START]
[TOOL_NAME]
create_tool
[PARAM_NAME]
name
[PARAM_VALUE]
hello
[PARAM_NAME]
description
[PARAM_VALUE]
A tool that says hello to the user.
[PARAM_NAME]
parameters
[PARAM_VALUE]
{}
[PARAM_NAME]
code
[PARAM_VALUE]
class HelloTool(BaseTool):
    name = "hello"
    description = "A tool that says hello to the user."
    parameters = {}

    def execute(self, params):
        return "Hello! \U0001f44b"
[RATIONALE]
Creating a simple tool.
[TOOL_END]"""
    calls = parse_tool_calls(response)
    print(f"  Parsed {len(calls)} call(s)")
    assert len(calls) == 1, f"Expected 1 call, got {len(calls)}"
    tool_name, params, rationale = calls[0]
    print(f"  tool_name: {tool_name!r}")
    print(f"  params keys: {list(params.keys())}")
    for k, v in params.items():
        print(f"    {k!r}: {v!r}")
    assert "name" in params, f"Missing 'name' in params: {list(params.keys())}"
    assert params["name"] == "hello"
    assert "description" in params, f"Missing 'description' in params: {list(params.keys())}"
    assert "parameters" in params, f"Missing 'parameters' in params: {list(params.keys())}"
    assert "code" in params, f"Missing 'code' in params: {list(params.keys())}"
    print("  PASSED")


def test_parse_create_tool_with_code_blocks():
    """Parse when LLM wraps the tool call inside a markdown code block."""
    response = """I'll create a tool for you.

```
[TOOL_START]
[TOOL_NAME]
create_tool
[PARAM_NAME]
name
[PARAM_VALUE]
run_build
[PARAM_NAME]
description
[PARAM_VALUE]
Runs the build.sh script to compile C source files to WebAssembly.
[PARAM_NAME]
parameters
[PARAM_VALUE]
{}
[PARAM_NAME]
code
[PARAM_VALUE]
class run_build(BaseTool):
    name = "run_build"
    description = "Runs the build.sh script."
    parameters = {}
    def execute(self, params):
        import subprocess
        return subprocess.run(["bash", "build.sh"], capture_output=True, text=True)
[RATIONALE]
Creating build tool.
[TOOL_END]
```"""
    calls = parse_tool_calls(response)
    print(f"  Parsed {len(calls)} call(s)")
    assert len(calls) == 1, f"Expected 1 call, got {len(calls)}"
    tool_name, params, _ = calls[0]
    print(f"  tool_name: {tool_name!r}")
    print(f"  params keys: {list(params.keys())}")
    for k, v in params.items():
        print(f"    {k!r}: {v!r}")
    assert "description" in params, f"Missing 'description' in params: {list(params.keys())}"
    assert "code" in params, f"Missing 'code' in params: {list(params.keys())}"
    print("  PASSED")


def test_parse_create_tool_with_natural_language():
    """Parse when LLM adds text before the tool call."""
    response = """Let me create a tool for you:

[TOOL_START]
[TOOL_NAME]
create_tool
[PARAM_NAME]
name
[PARAM_VALUE]
greet
[PARAM_NAME]
description
[PARAM_VALUE]
Greets the user with a personalized message.
[PARAM_NAME]
parameters
[PARAM_VALUE]
{"name": "string?"}
[PARAM_NAME]
code
[PARAM_VALUE]
class greet(BaseTool):
    name = "greet"
    description = "Greets the user."
    parameters = {"name": "string?"}
    def execute(self, params):
        return f"Hello, {params.get('name', 'User')}!"
[TOOL_END]"""
    calls = parse_tool_calls(response)
    print(f"  Parsed {len(calls)} call(s)")
    assert len(calls) == 1
    tool_name, params, _ = calls[0]
    print(f"  tool_name: {tool_name!r}")
    print(f"  params keys: {list(params.keys())}")
    for k, v in params.items():
        print(f"    {k!r}: {v!r}")
    assert "description" in params
    assert "code" in params
    print("  PASSED")


def test_parse_create_tool_multiline_code():
    """Parse when code parameter spans many lines with blank lines."""
    response = """[TOOL_START]
[TOOL_NAME]
create_tool
[PARAM_NAME]
name
[PARAM_VALUE]
complex_tool
[PARAM_NAME]
description
[PARAM_VALUE]
A complex tool that does many things.
[PARAM_NAME]
parameters
[PARAM_VALUE]
{"input": "string?", "output": "string?"}
[PARAM_NAME]
code
[PARAM_VALUE]
class complex_tool(BaseTool):
    name = "complex_tool"
    description = "A complex tool."
    parameters = {"input": "string?", "output": "string?"}

    def execute(self, params):
        import os
        import json

        input_data = params.get("input", "")
        output_file = params.get("output", "output.txt")

        result = {"status": "ok", "input": input_data}

        with open(output_file, "w") as f:
            json.dump(result, f)

        return result
[RATIONALE]
Creating complex tool.
[TOOL_END]"""
    calls = parse_tool_calls(response)
    print(f"  Parsed {len(calls)} call(s)")
    assert len(calls) == 1
    tool_name, params, _ = calls[0]
    print(f"  tool_name: {tool_name!r}")
    print(f"  params keys: {list(params.keys())}")
    for k, v in params.items():
        print(f"    {k!r}: {v!r}")
    assert "description" in params
    assert "code" in params
    # Code should contain the full class
    assert "class complex_tool" in params["code"]
    assert "def execute" in params["code"]
    print("  PASSED")


def test_validate_tool_params():
    """Validate that parsed params pass through validate_tool_params."""
    params = {
        "name": "hello",
        "description": "A tool that says hello to the user.",
        "parameters": "{}",
        "code": "class HelloTool(BaseTool):\n    name = 'hello'\n    pass",
    }
    schema = {
        "name": "string",
        "description": "string",
        "parameters": "string",
        "code": "string",
    }
    result = validate_tool_params(params, schema)
    print(f"  Validated: {list(result.keys())}")
    assert result == params
    print("  PASSED")


def test_strip_json_schema_keys_removes_description():
    """BUG REPRO: strip_json_schema_keys removes 'description' from create_tool params."""
    from agent_engine.security import strip_json_schema_keys
    params = {
        "name": "hello",
        "description": "A tool that says hello to the user.",
        "parameters": "{}",
        "code": "class HelloTool(BaseTool):\n    name = 'hello'\n    pass",
    }
    stripped = strip_json_schema_keys(params)
    print(f"  Original keys: {list(params.keys())}")
    print(f"  Stripped keys: {list(stripped.keys())}")
    assert "description" not in stripped, "BUG: 'description' was stripped!"
    assert "parameters" not in stripped, "BUG: 'parameters' was stripped!"
    print("  PASSED")


def test_strip_json_schema_keys_preserves_create_tool_params():
    """After fix: create_tool params should survive stripping."""
    from agent_engine.security import strip_json_schema_keys
    params = {
        "name": "hello",
        "description": "A tool that says hello to the user.",
        "parameters": "{}",
        "code": "class HelloTool(BaseTool):\n    name = 'hello'\n    pass",
    }
    stripped = strip_json_schema_keys(params)
    print(f"  Original keys: {list(params.keys())}")
    print(f"  Stripped keys: {list(stripped.keys())}")
    assert "description" in stripped, f"'description' was stripped! Keys: {list(stripped.keys())}"
    assert "parameters" in stripped, f"'parameters' was stripped! Keys: {list(stripped.keys())}"
    assert "name" in stripped
    assert "code" in stripped
    print("  PASSED")


def test_validate_missing_description():
    """Validate that missing description raises ToolError."""
    params = {
        "name": "hello",
        "parameters": "{}",
        "code": "class HelloTool(BaseTool):\n    name = 'hello'\n    pass",
    }
    schema = {
        "name": "string",
        "description": "string",
        "parameters": "string",
        "code": "string",
    }
    try:
        validate_tool_params(params, schema)
        assert False, "Expected ToolError"
    except ToolError as e:
        print(f"  Correctly raised ToolError: {e}")
        print("  PASSED")


if __name__ == "__main__":
    tests = [
        ("parse_create_tool_basic", test_parse_create_tool_basic),
        ("parse_create_tool_with_code_blocks", test_parse_create_tool_with_code_blocks),
        ("parse_create_tool_with_natural_language", test_parse_create_tool_with_natural_language),
        ("parse_create_tool_multiline_code", test_parse_create_tool_multiline_code),
        ("validate_tool_params", test_validate_tool_params),
        ("validate_missing_description", test_validate_missing_description),
        ("strip_json_schema_keys_removes_description", test_strip_json_schema_keys_removes_description),
        ("strip_json_schema_keys_preserves_create_tool_params", test_strip_json_schema_keys_preserves_create_tool_params),
    ]
    passed = 0
    failed = 0
    for name, test_fn in tests:
        print(f"\n=== {name} ===")
        try:
            test_fn()
            passed += 1
        except Exception as e:
            print(f"  FAILED: {e}")
            import traceback
            traceback.print_exc()
            failed += 1
    print(f"\n=== RESULTS: {passed} passed, {failed} failed ===")
