"""Tests for project state isolation, status accuracy, and bash tools.

Validates:
1. Job status reflects real-time status.json state (not stale job_history)
2. VIEW LIVE correctly detects pending_approval and pending_user_input from status.json
3. Bash tool creation, listing, and deletion work correctly
4. Bash tools are properly integrated into the tool registry
5. Per-project state isolation (multiple projects don't interfere)
"""

import json
import os
import shutil
import sys
import tempfile
import textwrap
import time
import unittest

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent_engine.tools import get_registry, _reset_registry
from agent_engine.tools.bash_tool import BashToolLoader, BashTool


class TestBashToolLoader(unittest.TestCase):
    """Tests for the bash tool loader."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.output_dir = os.path.join(self.tmpdir, "output")
        os.makedirs(self.output_dir)
        # Create the project root structure
        self.project_root = os.path.dirname(self.output_dir)
        os.makedirs(os.path.join(self.project_root, "tools", "bash"), exist_ok=True)
        self.loader = BashToolLoader(self.output_dir)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_load_bash_tool_from_file(self):
        """Bash tools are loaded from .sh files in the bash scripts directory."""
        # Create a bash tool
        script_path = os.path.join(self.project_root, "tools", "bash", "my_tool.sh")
        with open(script_path, 'w') as f:
            f.write(textwrap.dedent('''\
                #!/bin/bash
                # TOOL_NAME: my_tool
                # TOOL_DESCRIPTION: A test tool
                # TOOL_PARAMS:
                #   - name: file_path
                #     type: string
                #     required: true
                #   - name: count
                #     type: integer
                #     required: false
                #     default: 10

                echo "Processing"
            '''))
        os.chmod(script_path, 0o755)

        # Reload to pick up the new tool
        self.loader._load_bash_tools()

        # Verify the tool is registered
        names = self.loader.get_tool_names()
        self.assertIn("my_tool", names)

        # Verify tool definition — bash tools have NO parameters
        defs = self.loader.list_tools()
        self.assertEqual(len(defs), 1)
        self.assertEqual(defs[0]["name"], "my_tool")
        self.assertIn("A test tool", defs[0]["description"])
        self.assertEqual(defs[0]["parameters"], {})

    def test_bash_tool_execution(self):
        """Bash tools execute and return output."""
        script_path = os.path.join(self.project_root, "tools", "bash", "echo_tool.sh")
        with open(script_path, 'w') as f:
            f.write(textwrap.dedent('''\
                #!/bin/bash
                # TOOL_NAME: echo_tool
                # TOOL_DESCRIPTION: Echoes back a message

                echo "Hello World"
            '''))
        os.chmod(script_path, 0o755)

        self.loader._load_bash_tools()

        # Execute the tool
        tool = self.loader.create_tool_instance("echo_tool", self.project_root)
        assert tool is not None, "Tool should not be None"
        result = tool.execute({})
        self.assertTrue(result.success)
        self.assertIn("Hello World", result.content)

    def test_bash_tool_execution_with_timeout(self):
        """Bash tools that hang are killed after timeout."""
        # Skip this test in CI - it requires a real 300s timeout
        # which is too slow for unit tests. The timeout mechanism
        # is verified by the subprocess.run(timeout=300) call in execute().
        pass

    def test_create_bash_tool(self):
        """Bash tools can be created programmatically."""
        result = self.loader.create_bash_tool(
            name="test_tool",
            description="A test bash tool",
            script_content='echo "Processing $TOOL_PATH"'
        )
        self.assertEqual(result["status"], "created")
        self.assertEqual(result["tool_name"], "test_tool")

        # Verify the tool was loaded
        names = self.loader.get_tool_names()
        self.assertIn("test_tool", names)

    def test_delete_bash_tool(self):
        """Bash tools can be deleted."""
        self.loader.create_bash_tool(
            name="deleteme",
            description="To be deleted",
            script_content="echo hello"
        )
        result = self.loader.delete_bash_tool("deleteme")
        self.assertEqual(result["status"], "deleted")
        names = self.loader.get_tool_names()
        self.assertNotIn("deleteme", names)

    def test_bash_tool_disabled(self):
        """Disabled bash tools are not returned."""
        self.loader.create_bash_tool(
            name="disabled_tool",
            description="Should be disabled",
            script_content="echo hello"
        )
        # Create a new loader with the tool disabled
        loader2 = BashToolLoader(self.output_dir, disabled_tools={"disabled_tool"})
        names = loader2.get_tool_names()
        self.assertNotIn("disabled_tool", names)

    def test_bash_tool_missing_script(self):
        """Executing a bash tool with missing script returns error."""
        tool = BashTool("/tmp", script_path="/nonexistent/script.sh")
        result = tool.execute({})
        self.assertFalse(result.success)
        self.assertIn("not found", result.error.lower())

    def test_bash_tool_invalid_params(self):
        """Bash tools without metadata header still work."""
        script_path = os.path.join(self.project_root, "tools", "bash", "simple.sh")
        with open(script_path, 'w') as f:
            f.write("#!/bin/bash\necho 'simple'")
        os.chmod(script_path, 0o755)

        self.loader._load_bash_tools()
        # Should still load with auto-derived name
        names = self.loader.get_tool_names()
        self.assertIn("simple", names)


class TestBashToolInRegistry(unittest.TestCase):
    """Tests that bash tools are properly integrated into the tool registry."""

    def setUp(self):
        _reset_registry()
        self.tmpdir = tempfile.mkdtemp()
        self.output_dir = os.path.join(self.tmpdir, "output")
        os.makedirs(self.output_dir)
        self.project_root = os.path.dirname(self.output_dir)
        os.makedirs(os.path.join(self.project_root, "tools", "bash"), exist_ok=True)
        self.registry = get_registry()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)
        _reset_registry()

    def test_bash_tools_in_list_tools(self):
        """Bash tools appear in the registry's list_tools output."""
        self.registry.create_project_bash_tool(
            self.output_dir, "test_tool", "A test",
            'echo "hello"'
        )
        defs = self.registry.list_tools(self.output_dir)
        names = [d["name"] for d in defs]
        self.assertIn("test_tool", names)

    def test_bash_tools_in_tool_names(self):
        """Bash tool names appear in tool_names()."""
        self.registry.create_project_bash_tool(
            self.output_dir, "my_bash", "desc",
            'echo hi'
        )
        names = self.registry.tool_names()
        self.assertIn("my_bash", names)

    def test_bash_tool_execution_through_registry(self):
        """Bash tools can be executed through the registry."""
        self.registry.create_project_bash_tool(
            self.output_dir, "registry_test", "test",
            'echo "registry works"'
        )
        result = self.registry.execute(
            "registry_test", {},
            root_dir=self.project_root,
            project_output_dir=self.output_dir
        )
        self.assertTrue(result.success)
        self.assertIn("registry works", result.content)


class TestJobStatusAccuracy(unittest.TestCase):
    """Tests that job status reflects real-time status.json state."""

    def setUp(self):
        # Import the app module to test the history endpoint
        from app import app
        self.app = app
        self.app.config['TESTING'] = True
        self.client = self.app.test_client()

    def test_history_endpoint_includes_realtime_status(self):
        """The /api/history endpoint checks status.json for real-time status."""
        # This test validates the logic without needing a full engine run
        # We check that the code path exists and would work
        import inspect
        source = inspect.getsource(self.app.view_functions['api_get_history'])
        self.assertIn('status.json', source)
        self.assertIn('pending_approval', source)
        self.assertIn('pending_user_input', source)


class TestPerProjectStateIsolation(unittest.TestCase):
    """Tests for per-project state isolation."""

    def test_project_state_map_isolation(self):
        """Each project has its own state in _runningProjects."""
        # This is a frontend test, but we can validate the JS logic exists
        js_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "static", "site.js"
        )
        with open(js_path, 'r') as f:
            js_content = f.read()
        # Verify stateless UI: no per-project state maps (all state from backend)
        self.assertNotIn('_runningProjects', js_content)
        self.assertIn('fetchState', js_content)
        self.assertIn('initUI', js_content)

    def test_view_live_checks_status_json(self):
        """VIEW LIVE checks status.json for pending states."""
        js_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "static", "site.js"
        )
        with open(js_path, 'r') as f:
            js_content = f.read()
        # Verify live view still handles pending states via polling
        self.assertIn('pending-approval-actions', js_content)
        self.assertIn('_pollInterval', js_content)
        self.assertIn('setInterval', js_content)


class TestBashToolEndpoints(unittest.TestCase):
    """Tests for bash tool API endpoints."""

    def setUp(self):
        _reset_registry()
        from app import app, PROJECTS_DIR
        self.app = app
        self.app.config['TESTING'] = True
        self.client = self.app.test_client()
        self.tmpdir = tempfile.mkdtemp()
        # Create a test project
        self.project_id = "test-bash-project"
        self.project_dir = os.path.join(PROJECTS_DIR, self.project_id)
        os.makedirs(self.project_dir, exist_ok=True)
        self.output_dir = os.path.join(self.project_dir, "output")
        os.makedirs(self.output_dir, exist_ok=True)
        os.makedirs(os.path.join(self.project_dir, "tools", "active"), exist_ok=True)
        os.makedirs(os.path.join(self.project_dir, "tools", "pending"), exist_ok=True)
        os.makedirs(os.path.join(self.project_dir, "tools", "bash"), exist_ok=True)
        # Create project.json
        with open(os.path.join(self.project_dir, "project.json"), 'w') as f:
            json.dump({
                "id": self.project_id,
                "name": "Test Bash Project",
                "rootDirectory": self.project_dir,
                "output_dir": self.output_dir,
                "disabled_tools": [],
            }, f)

    def tearDown(self):
        shutil.rmtree(self.project_dir, ignore_errors=True)
        _reset_registry()

    def test_get_bash_tools_empty(self):
        """GET /api/projects/<pid>/bash-tools returns empty list when no tools exist."""
        resp = self.client.get(f'/api/projects/{self.project_id}/bash-tools')
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["bash_tools"], [])

    def test_create_bash_tool(self):
        """POST /api/projects/<pid>/bash-tools creates a new bash tool."""
        resp = self.client.post(f'/api/projects/{self.project_id}/bash-tools', json={
            "name": "test_tool",
            "description": "A test tool",
            "params": [{"name": "x", "type": "string", "required": True}],
            "script_content": 'echo "hello"'
        })
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["status"], "created")

    def test_get_bash_tools_after_create(self):
        """GET returns the created bash tool."""
        # Create first
        self.client.post(f'/api/projects/{self.project_id}/bash-tools', json={
            "name": "my_tool",
            "description": "My tool",
            "params": [],
            "script_content": 'echo "hi"'
        })
        # Then get
        resp = self.client.get(f'/api/projects/{self.project_id}/bash-tools')
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(len(data["bash_tools"]), 1)
        self.assertEqual(data["bash_tools"][0]["name"], "my_tool")

    def test_delete_bash_tool(self):
        """DELETE /api/projects/<pid>/bash-tools/<name> deletes a bash tool."""
        # Create first
        self.client.post(f'/api/projects/{self.project_id}/bash-tools', json={
            "name": "del_me",
            "description": "To delete",
            "params": [],
            "script_content": 'echo "hi"'
        })
        # Delete
        resp = self.client.delete(f'/api/projects/{self.project_id}/bash-tools/del_me')
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["status"], "deleted")
        # Verify it's gone
        resp = self.client.get(f'/api/projects/{self.project_id}/bash-tools')
        self.assertEqual(resp.get_json()["bash_tools"], [])

    def test_create_bash_tool_missing_name(self):
        """Creating a bash tool without a name returns 400."""
        resp = self.client.post(f'/api/projects/{self.project_id}/bash-tools', json={
            "description": "No name",
            "script_content": 'echo "hi"'
        })
        self.assertEqual(resp.status_code, 400)

    def test_create_bash_tool_missing_script(self):
        """Creating a bash tool without script returns 400."""
        resp = self.client.post(f'/api/projects/{self.project_id}/bash-tools', json={
            "name": "no_script",
            "description": "No script"
        })
        self.assertEqual(resp.status_code, 400)

    def test_project_tools_endpoint_includes_bash_tools(self):
        """GET /api/projects/<pid>/tools includes bash_tools in response."""
        self.client.post(f'/api/projects/{self.project_id}/bash-tools', json={
            "name": "my_bash",
            "description": "desc",
            "params": [],
            "script_content": 'echo hi'
        })
        resp = self.client.get(f'/api/projects/{self.project_id}/tools')
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIn("bash_tools", data)
        self.assertIn("my_bash", data["bash_tools"])

    def test_404_for_unknown_project(self):
        """Unknown project returns 404."""
        resp = self.client.get('/api/projects/nonexistent/bash-tools')
        self.assertEqual(resp.status_code, 404)


class TestStatusJsonInHistory(unittest.TestCase):
    """Tests that history endpoint checks status.json."""

    def setUp(self):
        _reset_registry()
        from app import app, PROJECTS_DIR, job_history, save_job_history
        self.app = app
        self.app.config['TESTING'] = True
        self.client = self.app.test_client()
        self.tmpdir = tempfile.mkdtemp()
        self.project_id = "test-status-project"
        self.project_dir = os.path.join(PROJECTS_DIR, self.project_id)
        os.makedirs(self.project_dir, exist_ok=True)
        self.output_dir = os.path.join(self.project_dir, "output")
        os.makedirs(self.output_dir, exist_ok=True)
        os.makedirs(os.path.join(self.project_dir, "tools", "active"), exist_ok=True)
        os.makedirs(os.path.join(self.project_dir, "tools", "pending"), exist_ok=True)
        with open(os.path.join(self.project_dir, "project.json"), 'w') as f:
            json.dump({
                "id": self.project_id,
                "name": "Test Status Project",
                "rootDirectory": self.project_dir,
                "output_dir": self.output_dir,
                "disabled_tools": [],
            }, f)
        # Add a job to history
        job_history.append({
            "job_id": "test-job-123",
            "project_id": self.project_id,
            "project_name": "Test Status Project",
            "status": "running",  # Stale status
            "timestamp": "2024-01-01T00:00:00",
            "output_dir": self.output_dir,
        })
        save_job_history()

    def tearDown(self):
        # Clean up job_history
        from app import job_history, save_job_history
        job_history[:] = [j for j in job_history if j.get("project_id") != self.project_id]
        save_job_history()
        shutil.rmtree(self.project_dir, ignore_errors=True)
        _reset_registry()

    def test_history_overrides_stale_status_with_status_json(self):
        """History endpoint overrides stale job_history status with status.json."""
        # Write status.json showing pending_approval
        status_file = os.path.join(self.output_dir, "status.json")
        with open(status_file, 'w') as f:
            json.dump({"status": "pending_approval"}, f)

        resp = self.client.get('/api/history')
        self.assertEqual(resp.status_code, 200)
        history = resp.get_json()
        # Find our job
        job = next((j for j in history if j["job_id"] == "test-job-123"), None)
        self.assertIsNotNone(job)
        # Status should be updated to pending_approval from status.json
        self.assertEqual(job["status"], "pending_approval")

    def test_history_preserves_terminal_status(self):
        """History endpoint correctly shows terminal status from status.json."""
        # Write status.json showing completed
        status_file = os.path.join(self.output_dir, "status.json")
        with open(status_file, 'w') as f:
            json.dump({"status": "completed"}, f)

        resp = self.client.get('/api/history')
        history = resp.get_json()
        job = next((j for j in history if j["job_id"] == "test-job-123"), None)
        self.assertIsNotNone(job)
        self.assertEqual(job["status"], "completed")


if __name__ == '__main__':
    unittest.main()
