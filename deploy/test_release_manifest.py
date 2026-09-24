"""Offline release-policy tests; no application imports or cloud connections."""

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from release_manifest import collect


class ReleaseManifestTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def touch(self, name):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
        return path

    def test_runtime_files_and_only_one_env_template(self):
        expected = {
            "README.md", "backend/.env.example", "backend/requirements.txt",
            "backend/app/main.py", "backend/app/models/migrations.py",
            "backend/scripts/rebuild_vectors.py", "frontend/package-lock.json",
            "frontend/src/utils/export.ts", "frontend/dist/index.html",
            "frontend/dist/assets/app.js", "docs/fonts/font.woff2",
            "docs/fonts.css", "deploy/start.sh",
            "deploy/docker-compose.infrastructure.yml",
        }
        for name in expected:
            self.touch(name)
        self.assertEqual(set(collect(self.root)), expected)

    def test_excludes_secrets_data_toolchains_and_hidden_files(self):
        excluded = {
            "backend/.env", "backend/.env.production", "backend/.env.example.bak",
            "frontend/.env", "frontend/.env.example", "backend/app/.env",
            "docs/.env.example", "backend/app/client.key", "backend/app/client.pem",
            "docs/credentials.txt", "docs/private-key.txt", "docs/id_rsa",
            "docs/data/records.md", "docs/exports/metadata.md",
            "backend/data/media.sql", "backend/scripts/export.json",
            "backend/scripts/migration-data.jsonl", "docs/migration.csv",
            "docs/database.db", "docs/snapshot.tar.gz", "docs/backup/readme.md",
            "backend/venv/lib/tool.py", "backend/.venv/lib/tool.py",
            "backend/app/__pycache__/main.pyc",
            "frontend/node_modules/package/index.js",
            "frontend/src/.npmrc", "frontend/dist/.vite/manifest.json",
            "frontend/dist/assets/credentials.js",
            ".tools/node/bin/node", ".tools/env.sh", ".trae/specs/spec.md",
            "docs/toolchain/tool.py", "docs/name\nwith-newline.md",
        }
        for name in excluded:
            self.touch(name)
        self.assertEqual(collect(self.root), [])

    def test_never_reads_file_contents(self):
        self.touch("backend/.env")
        self.touch("backend/.env.example")
        with patch.object(Path, "open", side_effect=AssertionError("File content read")):
            self.assertEqual(collect(self.root), ["backend/.env.example"])

    def test_links_cannot_alias_secret_files_or_directories(self):
        secret = self.touch("backend/.env")
        (self.root / "backend/app").mkdir()
        (self.root / "backend/app/innocent.py").symlink_to(secret)
        os.link(secret, self.root / "backend/app/hardlink.py")
        self.touch("outside/main.py")
        (self.root / "backend/scripts").symlink_to(self.root / "outside", target_is_directory=True)
        self.assertEqual(collect(self.root), [])

    def test_nested_symlinks_are_not_followed(self):
        self.touch("outside/file.ts")
        (self.root / "frontend/src").mkdir(parents=True)
        (self.root / "frontend/src/shared").symlink_to(self.root / "outside", target_is_directory=True)
        self.assertEqual(collect(self.root), [])


if __name__ == "__main__":
    unittest.main()
