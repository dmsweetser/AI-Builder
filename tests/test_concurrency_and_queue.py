"""Expanded tests for concurrency guards, queue behavior, and SSE endpoint."""
import os
import sys
import json
import unittest
import tempfile
import shutil
import threading
import time
from unittest.mock import patch, MagicMock, Mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Stop the worker thread before importing app to prevent interference
import app as _app_module
_app_module.stop_worker()

from app import (
    app, PROJECTS_FILE, SETTINGS_FILE, CHATS_DIR,
    job_queue, running_job, job_queue_lock,
    get_concurrent_job_info,
)


def _reset_globals():
    """Reset global state for a clean test."""
    with job_queue_lock:
        job_queue.clear()
        _app_module.running_job = None


def _set_running(pid, job_id="job-1"):
    """Helper to set running_job on the app module."""
    with job_queue_lock:
        _app_module.running_job = {"job_id": job_id, "project_id": pid}


def _set_queued(pid, job_id="job-2"):
    """Helper to add a queued job."""
    with job_queue_lock:
        job_queue.append({"job_id": job_id, "project_id": pid})


# ====================================================================
# get_concurrent_job_info tests
# ====================================================================

class TestConcurrentJobInfo(unittest.TestCase):
    """Tests for the get_concurrent_job_info helper."""

    def setUp(self):
        app.config["TESTING"] = True
        _reset_globals()

    def tearDown(self):
        _reset_globals()

    def test_no_job_returns_false(self):
        running, queued, jid = get_concurrent_job_info("any-id")
        self.assertFalse(running)
        self.assertFalse(queued)
        self.assertIsNone(jid)

    def test_running_project_detected(self):
        _set_running("proj-A", "job-1")
        running, queued, jid = get_concurrent_job_info("proj-A")
        self.assertTrue(running)
        self.assertFalse(queued)
        self.assertEqual(jid, "job-1")

    def test_queued_project_detected(self):
        _set_queued("proj-B", "job-2")
        running, queued, jid = get_concurrent_job_info("proj-B")
        self.assertFalse(running)
        self.assertTrue(queued)
        self.assertEqual(jid, "job-2")

    def test_different_project_not_detected(self):
        _set_running("proj-A", "job-1")
        running, queued, jid = get_concurrent_job_info("proj-X")
        self.assertFalse(running)
        self.assertFalse(queued)
        self.assertIsNone(jid)

    def test_running_project_not_detected_as_queued(self):
        _set_running("proj-A", "job-1")
        with job_queue_lock:
            job_queue.append({"job_id": "job-2", "project_id": "proj-A"})
        running, queued, jid = get_concurrent_job_info("proj-A")
        self.assertTrue(running)
        self.assertFalse(queued)


# ====================================================================
# Queue concurrency guard tests
# ====================================================================

class TestQueueConcurrencyGuard(unittest.TestCase):
    """Tests that the /api/queue endpoint blocks concurrent runs."""

    def setUp(self):
        app.config["TESTING"] = True
        self.client = app.test_client()
        self.test_dir = tempfile.mkdtemp()
        with open(PROJECTS_FILE, "w") as f:
            json.dump([], f)
        _reset_globals()
        self._worker_patch = patch("app.start_worker")
        self._worker_patch.start()

    def tearDown(self):
        self._worker_patch.stop()
        shutil.rmtree(self.test_dir, ignore_errors=True)
        with open(PROJECTS_FILE, "w") as f:
            json.dump([], f)
        _reset_globals()

    def _create_project(self, name="Test"):
        resp = self.client.post("/api/projects", data={
            "name": name,
            "rootDirectory": self.test_dir,
        })
        return resp.get_json()["id"]

    def test_add_to_queue_normal(self):
        pid = self._create_project()
        resp = self.client.post("/api/queue", json={"project_id": pid})
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["status"], "queued")
        self.assertIn("job_id", data)

    def test_add_same_project_twice(self):
        pid = self._create_project()
        resp1 = self.client.post("/api/queue", json={"project_id": pid})
        self.assertEqual(resp1.status_code, 200)
        resp2 = self.client.post("/api/queue", json={"project_id": pid})
        self.assertEqual(resp2.status_code, 409)
        data = resp2.get_json()
        self.assertIn("already queued", data["error"].lower())
        self.assertIn("job_id", data)

    def test_add_while_running_rejected(self):
        pid = self._create_project()
        _set_running(pid, "running-1")
        resp = self.client.post("/api/queue", json={"project_id": pid})
        self.assertEqual(resp.status_code, 409)
        data = resp.get_json()
        self.assertIn("already running", data["error"].lower())

    def test_different_projects_can_both_queue(self):
        pid1 = self._create_project("Proj1")
        pid2 = self._create_project("Proj2")
        resp1 = self.client.post("/api/queue", json={"project_id": pid1})
        self.assertEqual(resp1.status_code, 200)
        resp2 = self.client.post("/api/queue", json={"project_id": pid2})
        self.assertEqual(resp2.status_code, 200)

    def test_queue_returns_job_id(self):
        pid = self._create_project()
        resp = self.client.post("/api/queue", json={"project_id": pid})
        self.assertIn("job_id", resp.get_json())

    def test_invalid_project_id(self):
        resp = self.client.post("/api/queue", json={"project_id": "nonexistent"})
        self.assertEqual(resp.status_code, 404)

    def test_missing_project_id(self):
        resp = self.client.post("/api/queue", json={})
        self.assertEqual(resp.status_code, 400)


# ====================================================================
# SSE endpoint concurrency guard tests
# ====================================================================

class TestSSEEndpointConcurrencyGuard(unittest.TestCase):
    """Tests that the /api/agent/run endpoint blocks concurrent runs."""

    def setUp(self):
        app.config["TESTING"] = True
        self.client = app.test_client()
        self.test_dir = tempfile.mkdtemp()
        with open(PROJECTS_FILE, "w") as f:
            json.dump([], f)
        _reset_globals()

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)
        with open(PROJECTS_FILE, "w") as f:
            json.dump([], f)
        _reset_globals()

    def _create_project(self, name="Test"):
        resp = self.client.post("/api/projects", data={
            "name": name,
            "rootDirectory": self.test_dir,
        })
        return resp.get_json()["id"]

    def _mock_agent_engine(self):
        mock_instance = MagicMock()
        mock_instance.run.return_value = {
            "status": "completed",
            "steps": 1,
            "summary": "done",
            "max_steps": 50,
            "step_history": [],
        }
        return mock_instance

    def test_sse_rejects_while_running(self):
        pid = self._create_project()
        _set_running(pid, "running-1")
        resp = self.client.post("/api/agent/run", json={
            "project_id": pid,
            "rootDirectory": self.test_dir,
        })
        self.assertEqual(resp.status_code, 409)
        data = resp.get_json()
        self.assertIn("already running", data["error"].lower())

    def test_sse_rejects_while_queued(self):
        pid = self._create_project()
        _set_queued(pid, "queued-1")
        resp = self.client.post("/api/agent/run", json={
            "project_id": pid,
            "rootDirectory": self.test_dir,
        })
        self.assertEqual(resp.status_code, 409)
        data = resp.get_json()
        self.assertIn("already queued", data["error"].lower())

    def test_sse_accepts_when_idle(self):
        pid = self._create_project()
        with patch("app.AgentEngine") as mock_engine_cls:
            mock_engine_cls.return_value = self._mock_agent_engine()
            resp = self.client.post("/api/agent/run", json={
                "project_id": pid,
                "rootDirectory": self.test_dir,
            })
            self.assertNotEqual(resp.status_code, 409)

    def test_sse_with_instructions_no_project(self):
        with patch("app.AgentEngine") as mock_engine_cls:
            mock_engine_cls.return_value = self._mock_agent_engine()
            resp = self.client.post("/api/agent/run", json={
                "instructions": "Do something",
                "rootDirectory": self.test_dir,
            })
            self.assertNotEqual(resp.status_code, 409)

    def test_sse_missing_root_dir(self):
        resp = self.client.post("/api/agent/run", json={
            "instructions": "Do something",
        })
        self.assertEqual(resp.status_code, 400)

    def test_sse_missing_both_project_and_instructions(self):
        resp = self.client.post("/api/agent/run", json={})
        self.assertEqual(resp.status_code, 400)


# ====================================================================
# Queue end-to-end tests
# ====================================================================

class TestQueueEndToEnd(unittest.TestCase):
    """End-to-end tests for queue lifecycle."""

    def setUp(self):
        app.config["TESTING"] = True
        self.client = app.test_client()
        self.test_dir = tempfile.mkdtemp()
        with open(PROJECTS_FILE, "w") as f:
            json.dump([], f)
        _reset_globals()
        self._worker_patch = patch("app.start_worker")
        self._worker_patch.start()

    def tearDown(self):
        self._worker_patch.stop()
        shutil.rmtree(self.test_dir, ignore_errors=True)
        with open(PROJECTS_FILE, "w") as f:
            json.dump([], f)
        _reset_globals()

    def _create_project(self, name="Test"):
        resp = self.client.post("/api/projects", data={
            "name": name,
            "rootDirectory": self.test_dir,
        })
        return resp.get_json()["id"]

    def test_queue_lifecycle(self):
        pid = self._create_project()
        resp = self.client.post("/api/queue", json={"project_id": pid})
        self.assertEqual(resp.status_code, 200)
        job_id = resp.get_json()["job_id"]

        resp = self.client.get("/api/queue")
        data = resp.get_json()
        self.assertEqual(len(data["queue"]), 1)
        self.assertEqual(data["queue"][0]["job_id"], job_id)

        resp = self.client.delete(f"/api/queue/{job_id}")
        self.assertEqual(resp.status_code, 200)

        resp = self.client.get("/api/queue")
        self.assertEqual(len(resp.get_json()["queue"]), 0)

    def test_stop_running_clears_running_job(self):
        pid = self._create_project()
        _set_running(pid, "running-1")

        resp = self.client.post("/api/queue/running/stop")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()["status"], "stopped")

        with job_queue_lock:
            self.assertIsNone(_app_module.running_job)

    def test_delete_project_clears_from_queue(self):
        pid = self._create_project()
        self.client.post("/api/queue", json={"project_id": pid})
        resp = self.client.delete(f"/api/projects/{pid}")
        self.assertEqual(resp.status_code, 200)
        resp = self.client.get("/api/queue")
        data = resp.get_json()
        self.assertEqual(len(data["queue"]), 0)

    def test_history_includes_queued_jobs(self):
        pid = self._create_project()
        self.client.post("/api/queue", json={"project_id": pid})
        resp = self.client.get("/api/history")
        history = resp.get_json()
        queued_in_history = any(
            j.get("project_id") == pid and j.get("status") == "queued"
            for j in history
        )
        self.assertTrue(queued_in_history)

    def test_clear_history(self):
        pid = self._create_project()
        self.client.post("/api/queue", json={"project_id": pid})
        resp = self.client.post("/api/history/clear")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()["status"], "cleared")


# ====================================================================
# Concurrent project run tests
# ====================================================================

class TestConcurrentProjectRuns(unittest.TestCase):
    """Tests that two different projects can queue, but same project cannot."""

    def setUp(self):
        app.config["TESTING"] = True
        self.client = app.test_client()
        self.test_dir = tempfile.mkdtemp()
        with open(PROJECTS_FILE, "w") as f:
            json.dump([], f)
        _reset_globals()
        # Prevent the worker thread from consuming queued jobs during tests
        self._worker_patch = patch("app.start_worker")
        self._worker_patch.start()

    def tearDown(self):
        self._worker_patch.stop()
        shutil.rmtree(self.test_dir, ignore_errors=True)
        with open(PROJECTS_FILE, "w") as f:
            json.dump([], f)
        _reset_globals()

    def _create_project(self, name="Test"):
        resp = self.client.post("/api/projects", data={
            "name": name,
            "rootDirectory": self.test_dir,
        })
        return resp.get_json()["id"]

    def test_two_different_projects_both_queue(self):
        pid1 = self._create_project("Proj1")
        pid2 = self._create_project("Proj2")
        resp1 = self.client.post("/api/queue", json={"project_id": pid1})
        self.assertEqual(resp1.status_code, 200)
        resp2 = self.client.post("/api/queue", json={"project_id": pid2})
        self.assertEqual(resp2.status_code, 200)
        resp = self.client.get("/api/queue")
        self.assertEqual(len(resp.get_json()["queue"]), 2)

    def test_same_project_cannot_queue_twice_concurrently(self):
        pid = self._create_project()
        resp1 = self.client.post("/api/queue", json={"project_id": pid})
        self.assertEqual(resp1.status_code, 200)
        resp2 = self.client.post("/api/queue", json={"project_id": pid})
        self.assertEqual(resp2.status_code, 409)
        resp = self.client.get("/api/queue")
        self.assertEqual(len(resp.get_json()["queue"]), 1)

    def test_project_running_cannot_queue(self):
        pid = self._create_project()
        _set_running(pid, "running-1")
        resp = self.client.post("/api/queue", json={"project_id": pid})
        self.assertEqual(resp.status_code, 409)

    def test_project_queued_cannot_run_via_sse(self):
        pid = self._create_project()
        _set_queued(pid, "queued-1")
        resp = self.client.post("/api/agent/run", json={
            "project_id": pid,
            "rootDirectory": self.test_dir,
        })
        self.assertEqual(resp.status_code, 409)

    def test_project_running_cannot_run_via_sse(self):
        pid = self._create_project()
        _set_running(pid, "running-1")
        resp = self.client.post("/api/agent/run", json={
            "project_id": pid,
            "rootDirectory": self.test_dir,
        })
        self.assertEqual(resp.status_code, 409)


# ====================================================================
# UI page integration tests
# ====================================================================

class TestUIPageIntegration(unittest.TestCase):
    """Tests that the UI page loads with expected elements."""

    def setUp(self):
        app.config["TESTING"] = True
        self.client = app.test_client()

    def test_index_has_agent_live_container(self):
        resp = self.client.get("/")
        html = resp.data.decode()
        self.assertIn("agent-live-container", html)
        self.assertIn("agent-live-box", html)

    def test_index_has_live_inject_container(self):
        resp = self.client.get("/")
        html = resp.data.decode()
        self.assertIn("live-inject-input", html)
        self.assertIn("live-inject-btn", html)

    def test_index_has_stop_button(self):
        resp = self.client.get("/")
        html = resp.data.decode()
        self.assertIn("details-stop-btn", html)

    def test_css_has_agent_live_box(self):
        resp = self.client.get("/static/styles.css")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b".agent-box", resp.data)

    def test_js_has_handle_agent_step(self):
        resp = self.client.get("/static/site.js")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"handleAgentStep", resp.data)

    def test_js_has_start_agent_sse(self):
        resp = self.client.get("/static/site.js")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"startAgentSSE", resp.data)

    def test_js_has_run_project(self):
        resp = self.client.get("/static/site.js")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"runProject", resp.data)

    def test_js_has_stop_project(self):
        resp = self.client.get("/static/site.js")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"stopProject", resp.data)


# ====================================================================
# Edge cases
# ====================================================================

class TestEdgeCasesExpanded(unittest.TestCase):
    """Additional edge case tests."""

    def setUp(self):
        app.config["TESTING"] = True
        self.client = app.test_client()
        self.test_dir = tempfile.mkdtemp()
        with open(PROJECTS_FILE, "w") as f:
            json.dump([], f)
        _reset_globals()
        self._worker_patch = patch("app.start_worker")
        self._worker_patch.start()

    def tearDown(self):
        self._worker_patch.stop()
        shutil.rmtree(self.test_dir, ignore_errors=True)
        with open(PROJECTS_FILE, "w") as f:
            json.dump([], f)
        _reset_globals()

    def _create_project(self, name="Test"):
        resp = self.client.post("/api/projects", data={
            "name": name,
            "rootDirectory": self.test_dir,
        })
        return resp.get_json()["id"]

    def _mock_agent_engine(self):
        mock_instance = MagicMock()
        mock_instance.run.return_value = {
            "status": "completed",
            "steps": 1,
            "summary": "done",
            "max_steps": 50,
            "step_history": [],
        }
        return mock_instance

    def test_queue_after_stop(self):
        pid = self._create_project()
        _set_running(pid, "running-1")
        self.client.post("/api/queue/running/stop")
        resp = self.client.post("/api/queue", json={"project_id": pid})
        self.assertEqual(resp.status_code, 200)

    def test_delete_queue_job_allows_project_requeue(self):
        pid = self._create_project()
        resp = self.client.post("/api/queue", json={"project_id": pid})
        job_id = resp.get_json()["job_id"]
        self.client.delete(f"/api/queue/{job_id}")
        resp = self.client.post("/api/queue", json={"project_id": pid})
        self.assertEqual(resp.status_code, 200)

    def test_queue_with_special_chars_project_name(self):
        resp = self.client.post("/api/projects", data={
            "name": "Project & <script>alert('xss')</script>",
            "rootDirectory": self.test_dir,
        })
        pid = resp.get_json()["id"]
        resp = self.client.post("/api/queue", json={"project_id": pid})
        self.assertEqual(resp.status_code, 200)

    def test_concurrent_different_projects_via_sse(self):
        pid1 = self._create_project("Proj1")
        pid2 = self._create_project("Proj2")
        with patch("app.AgentEngine") as mock_engine_cls:
            mock_engine_cls.return_value = self._mock_agent_engine()
            resp1 = self.client.post("/api/agent/run", json={
                "project_id": pid1,
                "rootDirectory": self.test_dir,
            })
            self.assertNotEqual(resp1.status_code, 409)
            resp2 = self.client.post("/api/agent/run", json={
                "project_id": pid2,
                "rootDirectory": self.test_dir,
            })
            self.assertNotEqual(resp2.status_code, 409)

    def test_sse_accepts_continue_from_job(self):
        """SSE endpoint accepts continue_from_job parameter."""
        pid = self._create_project()
        # Simulate a previous job in history with step_history
        with patch("app.job_history", [{
            "job_id": "prev-job-123",
            "step_history": [
                {"step": 1, "tool": "llm_call", "params": {}, "result": {"success": True}},
                {"step": 1, "tool": "list_directory", "params": {}, "result": {"success": True}},
            ],
        }]):
            with patch("app.AgentEngine") as mock_engine_cls:
                mock_engine_cls.return_value = self._mock_agent_engine()
                resp = self.client.post("/api/agent/run", json={
                    "project_id": pid,
                    "rootDirectory": self.test_dir,
                    "continue_from_job": "prev-job-123",
                })
                self.assertNotEqual(resp.status_code, 409)

    def test_sse_continue_without_prev_history(self):
        """SSE endpoint handles continue_from_job when no history exists."""
        pid = self._create_project()
        with patch("app.AgentEngine") as mock_engine_cls:
            mock_engine_cls.return_value = self._mock_agent_engine()
            resp = self.client.post("/api/agent/run", json={
                "project_id": pid,
                "rootDirectory": self.test_dir,
                "continue_from_job": "nonexistent-job",
            })
            self.assertNotEqual(resp.status_code, 409)


if __name__ == "__main__":
    unittest.main()
