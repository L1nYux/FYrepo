"""Anonymous downloads, source integrity and extracted standalone startup."""
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from unittest.mock import patch
from django.conf import settings
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from .agent_distribution import AGENT_FILES, AgentPackageError, build_agent_package


class AgentDownloadViewTests(TestCase):
    def test_login_and_public_instructions_expose_download_before_login(self):
        response = self.client.get(reverse("login"))
        self.assertContains(response, reverse("sampling:agent_download"))
        response = self.client.get(reverse("sampling:agent_setup"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "START_CNKI_AGENT_WINDOWS.cmd")
        self.assertNotContains(response, 'id="workspace-navigation"')

    def test_anonymous_zip_contains_this_workbench_origin_and_complete_engine(self):
        response = self.client.get(reverse("sampling:agent_download"), secure=True)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/zip")
        self.assertIn("attachment;", response["Content-Disposition"])
        with zipfile.ZipFile(io.BytesIO(b"".join(response.streaming_content))) as archive:
            self.assertIsNone(archive.testzip())
            prefix = "FYrepo-CNKI-Agent/"
            origin = json.loads(archive.read(prefix + "tools/cnki_agent/workbench_origin.json"))
            self.assertEqual(origin["allowed_origins"], ["https://testserver"])
            self.assertIn(prefix + "START_CNKI_AGENT_WINDOWS.cmd", archive.namelist())
            self.assertIn(prefix + "vendor/sample_llm/integrations/pdf_downloader.py", archive.namelist())
            self.assertIn(prefix + "vendor/sample_llm/third_party/cnki_metadata_exporter-0.2.0-py3-none-any.whl", archive.namelist())
            self.assertNotIn(b"\n", archive.read(prefix + "START_CNKI_AGENT_WINDOWS.cmd").replace(b"\r\n", b""))

    def test_distribution_error_returns_instructions_with_503(self):
        with patch("sampling.views.build_agent_package", side_effect=AgentPackageError("来源文件 SHA256 不匹配")):
            response = self.client.get(reverse("sampling:agent_download"))
        self.assertEqual(response.status_code, 503)
        self.assertContains(response, "SHA256 不匹配", status_code=503)


class AgentPackageTests(SimpleTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "source"
        manifest = json.loads((settings.BASE_DIR / "vendor/SAMPLE_LLM_SOURCE.json").read_text())
        names = list(AGENT_FILES) + ["vendor/SAMPLE_LLM_SOURCE.json"]
        names += ["vendor/sample_llm/" + entry["path"] for entry in manifest["files"]]
        for name in names:
            target = self.root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(settings.BASE_DIR / name, target)

    def test_whitelist_excludes_runtime_cookies_database_and_environment(self):
        for name in ("vendor/sample_llm/runtime_outputs/cnki_master_profile/Default/Network/Cookies",
                     "tools/cnki_agent/runtime/private-job.json", "data/workbench.sqlite3", ".env",
                     "tools/cnki_agent/.venv/private.py"):
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"private-source-test-fixture")
        with zipfile.ZipFile(build_agent_package("https://workbench.example", base_dir=self.root)) as archive:
            self.assertFalse(any("runtime" in name or ".venv" in name or ".sqlite3" in name or name.endswith("/.env") for name in archive.namelist()))
            self.assertNotIn(b"private-source-test-fixture", b"".join(archive.read(name) for name in archive.namelist()))

    def test_corrupt_component_prevents_distribution(self):
        wheel = self.root / "vendor/sample_llm/third_party/cnki_metadata_exporter-0.2.0-py3-none-any.whl"
        wheel.write_bytes(b"corrupt")
        with self.assertRaisesRegex(AgentPackageError, "SHA256"):
            build_agent_package("https://workbench.example", base_dir=self.root)

    def test_extracted_package_checks_without_repository_or_django(self):
        extraction = self.root.parent / "extracted"
        with zipfile.ZipFile(build_agent_package("https://workbench.example", base_dir=self.root)) as archive:
            archive.extractall(extraction)
        result = subprocess.run([sys.executable, "-X", "utf8", "-S", str(extraction / "FYrepo-CNKI-Agent/tools/cnki_agent/start_agent.py"), "--check"],
            capture_output=True, text=True, encoding="utf-8", timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("23 文件", result.stdout)
        self.assertIn("https://workbench.example", result.stdout)

    def test_invalid_origin_config_has_readable_error(self):
        spec = importlib.util.spec_from_file_location("fyrepo_test_start_agent", self.root / "tools/cnki_agent/start_agent.py")
        bootstrap = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(bootstrap)
        config = self.root / "tools/cnki_agent/workbench_origin.json"
        for origins in (["https://workbench.example/path"], [123], ["https://user:password@workbench.example"]):
            with self.subTest(origins=origins):
                config.write_text(json.dumps({"schema_version": 1, "allowed_origins": origins}))
                with self.assertRaisesRegex(RuntimeError, "重新下载"):
                    bootstrap.configured_origins()


class ReleaseDeploymentTests(SimpleTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.parent = Path(self.temp.name)
        self.source, self.release = self.parent / "source", self.parent / "release"
        shutil.copytree(settings.BASE_DIR, self.source, ignore=shutil.ignore_patterns(
            ".git", ".venv", "node_modules", "data", "staticfiles", ".test-scratch",
            "__pycache__", "runtime", "runtime_outputs", "dist"))

    def stage(self):
        return subprocess.run([sys.executable, "-S", str(self.source / "deploy/stage_release.py"),
                               str(self.source), str(self.release)],
                              capture_output=True, text=True, encoding="utf-8", timeout=30,
                              env={**os.environ,'PYTHONIOENCODING':'utf-8'})

    def test_staged_release_serves_complete_download_without_original_checkout(self):
        private_files = (
            ".env", "data/workbench.sqlite3", "desktop/server-connection.json",
            "tools/cnki_agent/runtime/private-job.json", "tools/cnki_agent/.venv/private.py",
            "tools/cnki_agent/workbench_origin.json",
            "vendor/sample_llm/runtime_outputs/cnki_master_profile/Default/Network/Cookies",
        )
        for name in private_files:
            path = self.source / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"private-release-fixture")
        staged = self.stage()
        self.assertEqual(staged.returncode, 0, staged.stderr)
        for name in private_files:
            self.assertFalse((self.release / name).exists(), name)
        # The server process must resolve settings and download files from the release.
        archive_path = self.parent / "download.zip"
        environment = {**os.environ, "PYTHONPATH": "", "DJANGO_SETTINGS_MODULE": "config.settings",
                       "WORKBENCH_SECRET_KEY": "isolated-release-test", "WORKBENCH_DEBUG": "1",
                       "WORKBENCH_ALLOWED_HOSTS": "testserver", "WORKBENCH_DATA_DIR": str(self.parent / "data"),
                       "PYTHONIOENCODING":"utf-8"}
        response = subprocess.run([sys.executable, "-c", """
import json, sys
from pathlib import Path
import django
django.setup()
from django.conf import settings
from django.core.management import call_command
from django.test import Client
from django.urls import reverse
call_command('migrate', interactive=False, verbosity=0)
response = Client().get(reverse('sampling:agent_download'), secure=True)
assert response.status_code == 200, response.status_code
assert response['Content-Type'] == 'application/zip'
Path(sys.argv[1]).write_bytes(b''.join(response.streaming_content))
print(json.dumps({'base_dir': str(settings.BASE_DIR)}))
""", str(archive_path)], cwd=self.release, env=environment,
            capture_output=True, text=True, encoding="utf-8", timeout=60)
        self.assertEqual(response.returncode, 0, response.stderr)
        # Windows temp paths may use an 8.3 alias for the same directory.
        self.assertTrue(Path(json.loads(response.stdout)["base_dir"]).samefile(self.release))
        extraction = self.parent / "extracted"
        with zipfile.ZipFile(archive_path) as archive:
            self.assertIsNone(archive.testzip())
            for name in AGENT_FILES:
                self.assertIn("FYrepo-CNKI-Agent/" + name, archive.namelist())
            origin = json.loads(archive.read("FYrepo-CNKI-Agent/tools/cnki_agent/workbench_origin.json"))
            self.assertEqual(origin["allowed_origins"], ["https://testserver"])
            archive.extractall(extraction)
        checked = subprocess.run([sys.executable, "-S",
            str(extraction / "FYrepo-CNKI-Agent/tools/cnki_agent/start_agent.py"), "--check"],
            capture_output=True, text=True, encoding="utf-8", timeout=10,
            env={**os.environ,'PYTHONIOENCODING':'utf-8'})
        self.assertEqual(checked.returncode, 0, checked.stderr)
        self.assertIn("23 文件", checked.stdout)

    def test_missing_launcher_fails_staging_before_copying_release(self):
        (self.source / "START_CNKI_AGENT_WINDOWS.cmd").unlink()
        staged = self.stage()
        self.assertNotEqual(staged.returncode, 0)
        self.assertIn("START_CNKI_AGENT_WINDOWS.cmd", staged.stderr)
        self.assertFalse((self.release / "manage.py").exists())
