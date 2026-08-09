"""Step 7 — the deployment, asserted rather than described.

A Dockerfile that claims a non-root user and a manifest that claims a readiness
path are both *claims*, and this repository's rule is that documentation may
never claim behaviour the code does not have. Parsing them costs twenty lines
and catches the rename that would otherwise be caught by a cluster
(Level 19, decision D-1).
"""

import re
import unittest
from pathlib import Path

import yaml

from code_reviewer.infrastructure.http.app import ReviewApi

REPOSITORY = Path(__file__).resolve().parents[2]
DOCKERFILE = REPOSITORY / "Dockerfile"
MANIFESTS = sorted((REPOSITORY / "deploy" / "kubernetes").glob("*.yaml"))


def _dockerfile() -> str:
    return DOCKERFILE.read_text(encoding="utf-8")


def _instructions(keyword: str) -> list[str]:
    pattern = re.compile(rf"^\s*{keyword}\s+(.*)$", re.MULTILINE | re.IGNORECASE)
    return [match.strip() for match in pattern.findall(_dockerfile())]


def _documents() -> dict[str, dict]:
    return {path.name: yaml.safe_load(path.read_text(encoding="utf-8")) for path in MANIFESTS}


def _by_kind(kind: str) -> dict:
    for document in _documents().values():
        if document.get("kind") == kind:
            return document
    raise AssertionError(f"no {kind} in deploy/kubernetes")


def _container() -> dict:
    return _by_kind("Deployment")["spec"]["template"]["spec"]["containers"][0]


class TestTheImage(unittest.TestCase):
    def test_there_is_a_dockerfile(self):
        self.assertTrue(DOCKERFILE.is_file())

    def test_it_runs_as_a_non_root_user(self):
        """'We set USER' is the kind of claim that survives its own
        deletion."""
        users = _instructions("USER")

        self.assertTrue(users, "the image has no USER instruction and would run as root")
        self.assertNotIn("root", users[-1].lower())
        self.assertNotEqual(users[-1].split(":")[0], "0")

    def test_the_user_is_numeric_so_run_as_non_root_can_check_it(self):
        """`runAsNonRoot` refuses to start a container whose USER is a name it
        cannot resolve to a uid."""
        self.assertRegex(_instructions("USER")[-1], r"^\d+")

    def test_no_stage_is_built_from_latest(self):
        """An image that rebuilds differently next Tuesday is not a deployable
        artefact."""
        for source in _instructions("FROM"):
            image = source.split(" AS ")[0].strip()
            self.assertNotIn(":latest", image, source)
            self.assertIn(":", image, f"{source} has no tag at all, which means latest")

    def test_it_is_built_in_more_than_one_stage(self):
        self.assertGreaterEqual(len(_instructions("FROM")), 2)

    def test_the_final_stage_carries_no_build_toolchain(self):
        """No compiler, no `uv`, no source tree."""
        final = _dockerfile().split("FROM ")[-1]

        for tool in ("gcc", "build-essential", "uv sync", "uv pip"):
            self.assertNotIn(tool, final, f"{tool} survives into the runtime stage")

    def test_the_command_serves_the_application_under_a_real_server(self):
        """`wsgiref` serves one request at a time, which is fine for a laptop
        and not for a deployment."""
        command = _dockerfile()

        self.assertIn("gunicorn", command)
        self.assertIn("code_reviewer.serve:create_app", command)

    def test_the_container_exposes_the_port_it_serves(self):
        self.assertIn("8080", _instructions("EXPOSE")[0])
        self.assertIn("8080", _dockerfile())

    def test_the_build_context_excludes_what_the_image_must_not_carry(self):
        ignored = (REPOSITORY / ".dockerignore").read_text(encoding="utf-8")

        for entry in (".git", ".venv", "tests", "reports"):
            self.assertIn(entry, ignored, f"{entry} would be copied into the image")


class TestTheManifestsAreManifests(unittest.TestCase):
    def test_there_are_manifests(self):
        self.assertTrue(MANIFESTS)

    def test_every_file_parses_and_names_itself(self):
        for name, document in _documents().items():
            with self.subTest(manifest=name):
                self.assertIsInstance(document, dict)
                self.assertIn("apiVersion", document)
                self.assertIn("kind", document)
                self.assertTrue(document["metadata"]["name"])

    def test_everything_lives_in_one_namespace(self):
        for name, document in _documents().items():
            if document["kind"] == "Namespace":
                continue
            with self.subTest(manifest=name):
                self.assertEqual(document["metadata"]["namespace"], "code-review")

    def test_the_service_selects_the_deployment(self):
        service = _by_kind("Service")
        deployment = _by_kind("Deployment")

        self.assertEqual(service["spec"]["selector"], deployment["spec"]["selector"]["matchLabels"])


class TestTheProbesPointAtEndpointsThatExist(unittest.TestCase):
    """AC-11. A renamed endpoint breaks a test rather than a cluster."""

    def setUp(self):
        self.container = _container()
        self.served = {route.path for route in ReviewApi.ROUTES}

    def test_the_liveness_path_is_served(self):
        self.assertIn(self.container["livenessProbe"]["httpGet"]["path"], self.served)

    def test_the_readiness_path_is_served(self):
        self.assertIn(self.container["readinessProbe"]["httpGet"]["path"], self.served)

    def test_the_probes_are_the_two_open_routes(self):
        """A probe that needs a token is a probe that fails during a secret
        rotation."""
        open_paths = {route.path for route in ReviewApi.ROUTES if route.auth == "open"}

        self.assertEqual(
            {
                self.container["livenessProbe"]["httpGet"]["path"],
                self.container["readinessProbe"]["httpGet"]["path"],
            },
            open_paths,
        )

    def test_the_probes_use_the_port_the_container_declares(self):
        port_name = self.container["ports"][0]["name"]

        for probe in ("livenessProbe", "readinessProbe"):
            self.assertEqual(self.container[probe]["httpGet"]["port"], port_name)

    def test_the_declared_port_is_the_one_the_image_serves(self):
        self.assertEqual(self.container["ports"][0]["containerPort"], 8080)
        self.assertIn("8080", _dockerfile())


class TestTheDeploymentIsSafeToRun(unittest.TestCase):
    def setUp(self):
        self.deployment = _by_kind("Deployment")
        self.container = _container()

    def test_it_asks_for_one_replica_and_says_why(self):
        """The queue is in memory: two replicas do not share it."""
        self.assertEqual(self.deployment["spec"]["replicas"], 1)

        text = (REPOSITORY / "deploy" / "kubernetes" / "30-deployment.yaml").read_text(encoding="utf-8")
        self.assertIn("in memory", text)

    def test_no_autoscaler_is_shipped(self):
        """Shipping one would be a bug delivered as configuration."""
        kinds = {document["kind"] for document in _documents().values()}

        self.assertNotIn("HorizontalPodAutoscaler", kinds)

    def test_requests_and_limits_are_both_set(self):
        """A container without limits is a container that takes its node down
        with it."""
        resources = self.container["resources"]

        for section in ("requests", "limits"):
            self.assertIn("cpu", resources[section])
            self.assertIn("memory", resources[section])

    def test_the_pod_runs_as_a_non_root_user(self):
        security = self.deployment["spec"]["template"]["spec"]["securityContext"]

        self.assertTrue(security["runAsNonRoot"])
        self.assertNotEqual(security["runAsUser"], 0)

    def test_the_container_gives_up_everything_it_can(self):
        security = self.container["securityContext"]

        self.assertFalse(security["allowPrivilegeEscalation"])
        self.assertTrue(security["readOnlyRootFilesystem"])
        self.assertEqual(security["capabilities"]["drop"], ["ALL"])

    def test_a_read_only_root_has_somewhere_to_write(self):
        """`grep`, the analyzers and Python itself all want somewhere. With a
        read-only root that has to be said out loud."""
        mounted = {mount["mountPath"] for mount in self.container["volumeMounts"]}

        self.assertIn("/tmp", mounted)
        self.assertIn("/workspace", mounted)

    def test_the_grace_period_outlasts_the_drain(self):
        """So the bounded drain finishes before the kill rather than racing
        it."""
        grace = self.deployment["spec"]["template"]["spec"]["terminationGracePeriodSeconds"]
        configured = int(_by_kind("ConfigMap")["data"]["REVIEW_DRAIN_SECONDS"])

        self.assertGreater(grace, configured)

    def test_the_image_is_pinned(self):
        image = self.container["image"]

        self.assertNotIn(":latest", image)
        self.assertRegex(image, r":\d+\.\d+\.\d+$")


class TestNoSecretIsALiteral(unittest.TestCase):
    def test_every_credential_comes_from_a_secret(self):
        container = _container()
        sources = {key for source in container.get("envFrom", []) for key in source}

        self.assertIn("secretRef", sources)
        self.assertNotIn("env", container, "inline env is where a literal secret ends up")

    def test_the_configmap_carries_no_credential_keys(self):
        data = _by_kind("ConfigMap")["data"]

        for key in data:
            self.assertNotIn("TOKEN", key.upper(), f"{key} belongs in the Secret")
            self.assertNotIn("SECRET", key.upper(), f"{key} belongs in the Secret")
            self.assertNotIn("PASSWORD", key.upper(), f"{key} belongs in the Secret")

    def test_the_example_secret_says_it_is_an_example(self):
        path = REPOSITORY / "deploy" / "kubernetes" / "20-secret.example.yaml"

        self.assertTrue(path.is_file())
        self.assertIn("EXAMPLE", path.read_text(encoding="utf-8").upper())

    def test_the_example_secrets_values_are_placeholders(self):
        values = _by_kind("Secret")["stringData"].values()

        for value in values:
            self.assertEqual(value, "REPLACE_ME")


class TestTheConfigMapExplainsItself(unittest.TestCase):
    def test_every_key_carries_a_comment(self):
        """Twelve unexplained keys is twelve keys nobody dares change."""
        text = (REPOSITORY / "deploy" / "kubernetes" / "10-configmap.yaml").read_text(encoding="utf-8")
        lines = text.splitlines()

        for index, line in enumerate(lines):
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or ":" not in stripped:
                continue
            key = stripped.split(":", 1)[0]
            if key in ("apiVersion", "kind", "metadata", "name", "namespace", "labels", "data"):
                continue
            if key.startswith("app.kubernetes.io"):
                continue
            with self.subTest(key=key):
                preceding = [lines[offset].strip() for offset in range(max(0, index - 4), index)]
                self.assertTrue(
                    any(item.startswith("#") for item in preceding),
                    f"{key} has no comment saying what breaks without it",
                )


if __name__ == "__main__":
    unittest.main()
