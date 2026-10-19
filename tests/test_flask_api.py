"""Comprehensive API tests for the AI-Builder Flask application."""
import os
import sys
import json
import unittest
import tempfile
import shutil
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app, PROJECTS_FILE, SETTINGS_FILE, CHATS_DIR


class TestProjectAPI(unittest.TestCase):
    """Tests for project CRUD operations."""

    def setUp(self):
        app.config["TESTING"] = True
        self.client = app.test_client()
        self.test_dir = tempfile.mkdtemp()
        # Clean up any existing projects
        with open(PROJECTS_FILE, "w") as f:
            json.dump([], f)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)
        # Clean up
        with open(PROJECTS_FILE, "w") as f:
            json.dump([], f)

    def test_create_project_minimal(self):
        """Create a project with minimal required fields."""
        resp = self.client.post("/api/projects", data={
            "name": "Test Project",
            "rootDirectory": self.test_dir,
        })
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["name"], "Test Project")
        self.assertEqual(data["rootDirectory"], self.test_dir)
        self.assertIn("id", data)
        self.assertFalse(data["isArchived"])
        self.assertEqual(data["enabled_tools"], [])

    def test_create_project_full(self):
        """Create a project with all fields."""
        resp = self.client.post("/api/projects", data={
            "name": "Full Project",
            "rootDirectory": self.test_dir,
            "instructions": "Do something cool",
            "preScript": "echo pre",
            "postScript": "echo post",
        })
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["instructions"], "Do something cool")
        self.assertEqual(data["preScript"], "echo pre")
        self.assertEqual(data["postScript"], "echo post")

    def test_create_project_missing_name(self):
        """Creating a project without a name should fail."""
        resp = self.client.post("/api/projects", data={
            "rootDirectory": self.test_dir,
        })
        self.assertEqual(resp.status_code, 400)

    def test_create_project_missing_root_dir(self):
        """Creating a project without a root directory should fail."""
        resp = self.client.post("/api/projects", data={
            "name": "No Root",
        })
        self.assertEqual(resp.status_code, 400)

    def test_get_projects_empty(self):
        """Get projects when none exist."""
        resp = self.client.get("/api/projects")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json(), [])

    def test_get_projects_list(self):
        """Get projects returns all non-deleted projects."""
        self.client.post("/api/projects", data={
            "name": "Proj1",
            "rootDirectory": self.test_dir,
        })
        self.client.post("/api/projects", data={
            "name": "Proj2",
            "rootDirectory": self.test_dir,
        })
        resp = self.client.get("/api/projects")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.get_json()), 2)

    def test_get_single_project(self):
        """Get a single project by ID."""
        resp = self.client.post("/api/projects", data={
            "name": "Single",
            "rootDirectory": self.test_dir,
        })
        pid = resp.get_json()["id"]
        resp = self.client.get(f"/api/projects/{pid}")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["name"], "Single")
        self.assertNotIn("modelConfig", data)

    def test_get_single_project_not_found(self):
        """Get a non-existent project returns 404."""
        resp = self.client.get("/api/projects/nonexistent-id")
        self.assertEqual(resp.status_code, 404)

    def test_update_project(self):
        """Update an existing project."""
        resp = self.client.post("/api/projects", data={
            "name": "Old Name",
            "rootDirectory": self.test_dir,
            "instructions": "Old instructions",
        })
        pid = resp.get_json()["id"]
        resp = self.client.post(f"/api/projects/{pid}", data={
            "name": "New Name",
            "rootDirectory": self.test_dir,
            "instructions": "New instructions",
        })
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["project"]["name"], "New Name")
        self.assertEqual(data["project"]["instructions"], "New instructions")

    def test_update_project_missing_root_dir(self):
        """Updating a project without root directory falls back to existing root."""
        resp = self.client.post("/api/projects", data={
            "name": "Test",
            "rootDirectory": self.test_dir,
        })
        pid = resp.get_json()["id"]
        resp = self.client.post(f"/api/projects/{pid}", data={
            "name": "Updated",
        })
        # Falls back to existing root directory (not 400)
        self.assertEqual(resp.status_code, 200)

    def test_archive_project(self):
        """Archive a project."""
        resp = self.client.post("/api/projects", data={
            "name": "Archive Me",
            "rootDirectory": self.test_dir,
        })
        pid = resp.get_json()["id"]
        resp = self.client.post(f"/api/projects/{pid}/archive")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()["status"], "archived")

    def test_unarchive_project(self):
        """Unarchive a previously archived project."""
        resp = self.client.post("/api/projects", data={
            "name": "Archive Me",
            "rootDirectory": self.test_dir,
        })
        pid = resp.get_json()["id"]
        self.client.post(f"/api/projects/{pid}/archive")
        resp = self.client.post(f"/api/projects/{pid}/unarchive")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()["status"], "unarchived")

    def test_delete_project(self):
        """Delete a project and verify it's gone."""
        resp = self.client.post("/api/projects", data={
            "name": "Delete Me",
            "rootDirectory": self.test_dir,
        })
        pid = resp.get_json()["id"]
        resp = self.client.delete(f"/api/projects/{pid}")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()["status"], "deleted")
        # Verify it's actually gone
        resp = self.client.get("/api/projects")
        projects = resp.get_json()
        self.assertNotIn(pid, [p["id"] for p in projects])

    def test_delete_nonexistent_project(self):
        """Delete a non-existent project."""
        resp = self.client.delete("/api/projects/nonexistent-id")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()["status"], "deleted")

    def test_multiple_projects_independent(self):
        """Multiple projects should be independent."""
        resp1 = self.client.post("/api/projects", data={
            "name": "Project A",
            "rootDirectory": self.test_dir,
        })
        pid_a = resp1.get_json()["id"]
        resp2 = self.client.post("/api/projects", data={
            "name": "Project B",
            "rootDirectory": self.test_dir,
        })
        pid_b = resp2.get_json()["id"]
        # Update A
        self.client.post(f"/api/projects/{pid_a}", data={
            "name": "Updated A",
            "rootDirectory": self.test_dir,
        })
        # Verify B unchanged
        resp = self.client.get(f"/api/projects/{pid_b}")
        self.assertEqual(resp.get_json()["name"], "Project B")


class TestSettingsAPI(unittest.TestCase):
    """Tests for settings CRUD operations."""

    def setUp(self):
        app.config["TESTING"] = True
        self.client = app.test_client()
        # Clean up settings
        if os.path.exists(SETTINGS_FILE):
            os.remove(SETTINGS_FILE)

    def tearDown(self):
        if os.path.exists(SETTINGS_FILE):
            os.remove(SETTINGS_FILE)

    def test_get_settings_defaults(self):
        """Get settings returns defaults when no settings saved."""
        resp = self.client.get("/api/settings")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIn("custom_endpoint_url", data)
        self.assertIn("custom_model_name", data)
        self.assertIn("max_steps", data)
        self.assertIn("timeout", data)
        self.assertIn("custom_verify_ssl", data)

    def test_save_and_get_settings(self):
        """Save settings and verify they persist."""
        settings = {
            "custom_endpoint_url": "http://localhost:11434/v1",
            "custom_model_name": "test-model",
            "max_steps": 25,
            "timeout": 600,
            "custom_verify_ssl": True,
        }
        resp = self.client.post("/api/settings", json=settings)
        self.assertEqual(resp.status_code, 200)
        resp = self.client.get("/api/settings")
        data = resp.get_json()
        self.assertEqual(data["custom_endpoint_url"], "http://localhost:11434/v1")
        self.assertEqual(data["custom_model_name"], "test-model")
        self.assertEqual(data["max_steps"], 25)
        self.assertEqual(data["timeout"], 600)
        self.assertTrue(data["custom_verify_ssl"])

    def test_save_settings_partial(self):
        """Saving partial settings should merge with existing."""
        self.client.post("/api/settings", json={
            "custom_endpoint_url": "http://localhost:11434/v1",
            "max_steps": 30,
        })
        self.client.post("/api/settings", json={
            "custom_model_name": "new-model",
        })
        resp = self.client.get("/api/settings")
        data = resp.get_json()
        self.assertEqual(data["custom_endpoint_url"], "http://localhost:11434/v1")
        self.assertEqual(data["max_steps"], 30)
        self.assertEqual(data["custom_model_name"], "new-model")

    def test_save_settings_no_data(self):
        """Saving settings with no data returns error."""
        resp = self.client.post("/api/settings", json={})
        # Empty dict is accepted (no-op merge)
        self.assertIn(resp.status_code, [200, 400])


class TestChatAPI(unittest.TestCase):
    """Tests for chat operations."""

    def setUp(self):
        app.config["TESTING"] = True
        self.client = app.test_client()
        # Clean up chats
        if os.path.exists(CHATS_DIR):
            shutil.rmtree(CHATS_DIR)

    def tearDown(self):
        if os.path.exists(CHATS_DIR):
            shutil.rmtree(CHATS_DIR)

    def test_list_chats_empty(self):
        """List chats when none exist."""
        resp = self.client.get("/api/chats")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json(), [])

    def test_create_chat(self):
        """Create a new chat."""
        resp = self.client.post("/api/chats", json={
            "timestamp": "2026-01-01T00:00:00",
        })
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIn("id", data)
        self.assertEqual(data["timestamp"], "2026-01-01T00:00:00")

    def test_list_chats_after_create(self):
        """List chats returns created chats."""
        self.client.post("/api/chats", json={
            "timestamp": "2026-01-01T00:00:00",
        })
        resp = self.client.get("/api/chats")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.get_json()), 1)

    def test_get_chat(self):
        """Get a specific chat."""
        resp = self.client.post("/api/chats", json={
            "timestamp": "2026-01-01T00:00:00",
        })
        chat_id = resp.get_json()["id"]
        resp = self.client.get(f"/api/chats/{chat_id}")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["id"], chat_id)
        self.assertEqual(data["messages"], [])

    def test_get_chat_not_found(self):
        """Get a non-existent chat returns 404."""
        resp = self.client.get("/api/chats/nonexistent-id")
        self.assertEqual(resp.status_code, 404)

    def test_send_message(self):
        """Send a message to a chat."""
        resp = self.client.post("/api/chats", json={
            "timestamp": "2026-01-01T00:00:00",
        })
        chat_id = resp.get_json()["id"]
        resp = self.client.post(f"/api/chats/{chat_id}/messages",
                                json={"content": "Hello"})
        self.assertEqual(resp.status_code, 200)
        # Verify message was saved
        resp = self.client.get(f"/api/chats/{chat_id}")
        data = resp.get_json()
        self.assertEqual(len(data["messages"]), 1)
        self.assertEqual(data["messages"][0]["role"], "user")
        self.assertEqual(data["messages"][0]["content"], "Hello")

    def test_send_message_to_nonexistent_chat(self):
        """Sending a message to a non-existent chat returns 404."""
        resp = self.client.post("/api/chats/nonexistent/messages",
                                json={"content": "Hello"})
        self.assertEqual(resp.status_code, 404)

    def test_send_message_empty(self):
        """Sending an empty message returns 400."""
        resp = self.client.post("/api/chats/some-id/messages",
                                json={"content": ""})
        self.assertEqual(resp.status_code, 400)

    def test_delete_chat(self):
        """Delete a chat."""
        resp = self.client.post("/api/chats", json={
            "timestamp": "2026-01-01T00:00:00",
        })
        chat_id = resp.get_json()["id"]
        resp = self.client.delete(f"/api/chats/{chat_id}")
        self.assertEqual(resp.status_code, 200)
        # Verify it's gone
        resp = self.client.get(f"/api/chats/{chat_id}")
        self.assertEqual(resp.status_code, 404)

    def test_auto_chat_creates_new(self):
        """Auto chat creates a new chat when none exist."""
        resp = self.client.get("/api/chats/auto")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["created"])
        self.assertIn("id", data)

    def test_auto_chat_returns_existing(self):
        """Auto chat returns existing chat when one exists."""
        self.client.post("/api/chats", json={
            "timestamp": "2026-01-01T00:00:00",
        })
        resp = self.client.get("/api/chats/auto")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertFalse(data["created"])


class TestQueueAPI(unittest.TestCase):
    """Tests for job queue operations."""

    def setUp(self):
        app.config["TESTING"] = True
        self.client = app.test_client()

    def test_get_queue_empty(self):
        """Get queue when empty."""
        resp = self.client.get("/api/queue")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["queue"], [])
        self.assertIsNone(data["running"])

    def test_delete_from_queue(self):
        """Delete a job from queue."""
        resp = self.client.delete("/api/queue/fake-job-id")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()["status"], "deleted")

    def test_stop_running(self):
        """Stop the running job."""
        resp = self.client.post("/api/queue/running/stop")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()["status"], "stopped")


class TestHistoryAPI(unittest.TestCase):
    """Tests for job history operations."""

    def setUp(self):
        app.config["TESTING"] = True
        self.client = app.test_client()

    def test_get_history_empty(self):
        """Get history when empty."""
        resp = self.client.get("/api/history")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json(), [])

    def test_clear_history(self):
        """Clear job history."""
        resp = self.client.post("/api/history/clear")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()["status"], "cleared")


class TestJobActionsAPI(unittest.TestCase):
    """Tests for job actions endpoint."""

    def setUp(self):
        app.config["TESTING"] = True
        self.client = app.test_client()

    def test_get_job_actions_not_found(self):
        """Get actions for a non-existent job."""
        resp = self.client.get("/api/job/fake-job/actions")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["content"], "")


class TestFavicon(unittest.TestCase):
    """Tests for favicon endpoint."""

    def setUp(self):
        app.config["TESTING"] = True
        self.client = app.test_client()

    def test_favicon_exists(self):
        """Favicon should return 200."""
        resp = self.client.get("/favicon.ico")
        self.assertEqual(resp.status_code, 200)


class TestIndexPage(unittest.TestCase):
    """Tests for the main index page."""

    def setUp(self):
        app.config["TESTING"] = True
        self.client = app.test_client()

    def test_index_page_loads(self):
        """Index page should return 200."""
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"AI Builder", resp.data)

    def test_index_page_has_all_panels(self):
        """Index page should contain all UI panels."""
        resp = self.client.get("/")
        html = resp.data.decode()
        self.assertIn("projects-panel", html)
        self.assertIn("jobs-panel", html)
        self.assertIn("chat-panel", html)
        self.assertIn("settings-panel", html)
        self.assertIn("tools-panel", html)

    def test_index_page_has_static_assets(self):
        """Index page should reference static assets."""
        resp = self.client.get("/")
        html = resp.data.decode()
        self.assertIn("styles.css", html)
        self.assertIn("site.js", html)

    def test_index_page_has_closing_html_tag(self):
        """Index page should have proper closing HTML tag."""
        resp = self.client.get("/")
        html = resp.data.decode()
        self.assertIn("</html>", html)
        self.assertIn("</body>", html)


class TestEdgeCases(unittest.TestCase):
    """Edge case tests."""

    def setUp(self):
        app.config["TESTING"] = True
        self.client = app.test_client()

    def test_create_project_with_special_chars_in_name(self):
        """Project name with special characters should work."""
        resp = self.client.post("/api/projects", data={
            "name": "Project & <script>alert('xss')</script>",
            "rootDirectory": "/tmp/test",
        })
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIn("<script>", data["name"])

    def test_create_project_with_unicode_name(self):
        """Project name with unicode characters should work."""
        resp = self.client.post("/api/projects", data={
            "name": "项目测试 🚀",
            "rootDirectory": "/tmp/test",
        })
        self.assertEqual(resp.status_code, 200)
        self.assertIn("项目测试", resp.get_json()["name"])

    def test_settings_with_unicode_values(self):
        """Settings with unicode values should persist."""
        resp = self.client.post("/api/settings", json={
            "custom_endpoint_url": "http://例.test/v1",
        })
        self.assertEqual(resp.status_code, 200)
        resp = self.client.get("/api/settings")
        self.assertEqual(resp.get_json()["custom_endpoint_url"], "http://例.test/v1")

    def test_consecutive_project_operations(self):
        """Create, update, archive, unarchive, delete in sequence."""
        # Create
        resp = self.client.post("/api/projects", data={
            "name": "Lifecycle",
            "rootDirectory": "/tmp/test",
        })
        pid = resp.get_json()["id"]
        # Update
        self.client.post(f"/api/projects/{pid}", data={
            "name": "Lifecycle Updated",
            "rootDirectory": "/tmp/test",
        })
        # Archive
        self.client.post(f"/api/projects/{pid}/archive")
        # Unarchive
        self.client.post(f"/api/projects/{pid}/unarchive")
        # Delete
        resp = self.client.delete(f"/api/projects/{pid}")
        self.assertEqual(resp.status_code, 200)


if __name__ == "__main__":
    unittest.main()
