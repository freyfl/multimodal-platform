"""Static deployment safety tests; Docker is not required."""

from pathlib import Path
import re
import subprocess
import unittest


DEPLOY = Path(__file__).resolve().parent
COMPOSE = DEPLOY / "docker-compose.infrastructure.yml"
INFRA = DEPLOY / "infra.sh"
FRONTEND_SERVER = DEPLOY.parent / "frontend" / "server.mjs"


class InfrastructureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.compose = COMPOSE.read_text(encoding="utf-8")
        cls.infra = INFRA.read_text(encoding="utf-8")
        cls.frontend_server = FRONTEND_SERVER.read_text(encoding="utf-8")

    def test_images_are_pinned_and_services_are_present(self):
        for service in ("mysql", "etcd", "minio", "milvus"):
            self.assertRegex(self.compose, rf"(?m)^  {service}:$")
        images = re.findall(r"(?m)^\s+image:\s+(\S+)$", self.compose)
        self.assertEqual(len(images), 4)
        self.assertTrue(all(":" in image and not image.endswith(":latest") for image in images))
        self.assertIn("quay.io/coreos/etcd:v3.5.25", images)
        self.assertIn("milvusdb/milvus:v2.6.23", images)

    def test_database_ports_are_loopback_only(self):
        for binding in (
            '"127.0.0.1:${MYSQL_PORT:-3306}:3306"',
            '"127.0.0.1:19530:19530"',
            '"127.0.0.1:9091:9091"',
        ):
            self.assertIn(binding, self.compose)
        self.assertNotRegex(self.compose, r'(?m)^\s+-\s+"(?:3306|19530|9091):')

    def test_persistent_named_volumes_and_healthchecks(self):
        for volume in ("mysql_data", "etcd_data", "minio_data", "milvus_data"):
            self.assertRegex(self.compose, rf"(?m)^  {volume}:$")
        self.assertEqual(self.compose.count("healthcheck:"), 4)
        self.assertIn("condition: service_healthy", self.compose)

    def test_secrets_are_required_and_milvus_auth_is_explicitly_disabled(self):
        for variable in (
            "MYSQL_PASSWORD",
            "INFRA_MYSQL_ROOT_PASSWORD",
            "INFRA_MINIO_ROOT_USER",
            "INFRA_MINIO_ROOT_PASSWORD",
        ):
            self.assertIn(f"${{{variable}:?", self.compose)
        self.assertIn('COMMON_SECURITY_AUTHORIZATIONENABLED: "false"', self.compose)
        self.assertIn("MQ_TYPE: woodpecker", self.compose)

    def test_milvus_uses_standalone_mode_without_distributed_components(self):
        self.assertIn('command: ["milvus", "run", "standalone"]', self.compose)
        for component in (
            "querynode", "datanode", "indexnode", "querycoord",
            "datacoord", "indexcoord", "rootcoord", "proxy",
        ):
            self.assertNotRegex(self.compose, rf"(?mi)^\s+{component}:")

    def test_infra_shutdown_never_removes_volumes_or_sources_env(self):
        self.assertNotIn("down -v", self.infra)
        self.assertNotIn("--volumes", self.infra)
        self.assertNotRegex(self.infra, r"(?m)^\s*(?:source|\.)\s+[\"']?\$ENV_FILE")
        self.assertIn("--env-file", self.infra)
        self.assertIn("compose up -d --wait", self.infra)

    def test_shell_scripts_parse(self):
        for name in ("common.sh", "infra.sh", "install.sh", "start.sh", "stop.sh"):
            result = subprocess.run(
                ["bash", "-n", str(DEPLOY / name)],
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_frontend_entrypoint_is_never_cached_as_immutable(self):
        self.assertIn(
            "'Cache-Control': 'no-cache, no-store, must-revalidate'",
            self.frontend_server,
        )
        self.assertIn(
            "'Cache-Control': 'public, max-age=31536000, immutable'",
            self.frontend_server,
        )
        self.assertLess(
            self.frontend_server.index("path.extname(filePath).toLowerCase() === '.html'"),
            self.frontend_server.index("filePath.startsWith(path.join(DIST_DIR, 'assets')"),
        )


if __name__ == "__main__":
    unittest.main()
