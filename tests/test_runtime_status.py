import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from laya_gui import services
from laya_gui.services import read_director_health


class RuntimeStatusTests(unittest.TestCase):
    def test_fresh_heartbeat_reports_running(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            pid_path = root / "director.pid"
            status_path = root / "runtime-status.json"
            pid_path.write_text(str(os.getpid()), encoding="ascii")
            status_path.write_text(json.dumps({
                "pid": os.getpid(),
                "state": "running",
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "detail": "cycle complete",
            }), encoding="utf-8")
            health = read_director_health(pid_path, status_path)
            self.assertEqual(health["state"], "running")
            self.assertTrue(health["healthy"])

    def test_stale_heartbeat_reports_unresponsive_even_when_pid_exists(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            pid_path = root / "director.pid"
            status_path = root / "runtime-status.json"
            pid_path.write_text(str(os.getpid()), encoding="ascii")
            status_path.write_text(json.dumps({
                "pid": os.getpid(),
                "state": "running",
                "updated_at": (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat(),
            }), encoding="utf-8")
            health = read_director_health(pid_path, status_path, stale_after=45)
            self.assertEqual(health["state"], "unresponsive")
            self.assertFalse(health["healthy"])

    def test_start_does_not_overwrite_director_child_pid(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            python_exe = root / "python.exe"
            director = root / "director.py"
            python_exe.touch()
            director.touch()
            pid_path = root / "director.pid"
            status_path = root / "runtime-status.json"

            def fake_popen(*args, **kwargs):
                pid_path.write_text("222", encoding="ascii")
                return SimpleNamespace(pid=111)

            config = {
                "python_exe": str(python_exe),
                "director_script": str(director),
                "device": "cpu",
                "interval": 10,
                "api_url": "http://localhost:8765",
            }
            with patch.object(services.subprocess, "Popen", side_effect=fake_popen):
                actual = services.start_director(
                    config,
                    root / "decisions.jsonl",
                    root / "state.json",
                    pid_path,
                    status_path,
                )

            self.assertEqual(actual, 222)
            self.assertEqual(pid_path.read_text(encoding="ascii"), "222")

    def test_enabled_ornith_profile_is_passed_only_to_the_director(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            python_exe = root / "python.exe"
            director = root / "director.py"
            python_exe.touch()
            director.touch()
            pid_path = root / "director.pid"
            status_path = root / "runtime-status.json"
            advisor_path = root / "colony-advisor.json"
            captured = {}

            def fake_popen(*args, **kwargs):
                captured.update(kwargs)
                pid_path.write_text("222", encoding="ascii")
                return SimpleNamespace(pid=111)

            config = {
                "python_exe": str(python_exe), "director_script": str(director),
                "device": "cpu", "interval": 10, "api_url": "http://localhost:8765",
                "ornith_enabled": True,
            }
            with patch.object(services, "ADVISOR_CONFIG_PATH", advisor_path), \
                    patch.object(services.subprocess, "Popen", side_effect=fake_popen):
                actual = services.start_director(
                    config, root / "decisions.jsonl", root / "state.json", pid_path, status_path)

            self.assertEqual(actual, 222)
            self.assertEqual(str(advisor_path), captured["env"]["RIMWORLD_AUTOPILOT_ADVISOR"])
            self.assertTrue(json.loads(advisor_path.read_text(encoding="utf-8"))["enabled"])


if __name__ == "__main__":
    unittest.main()
