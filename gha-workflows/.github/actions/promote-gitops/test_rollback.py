import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


class RollbackTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.remote = self.root / "remote.git"
        self.source = self.root / "source"
        self.workspace = self.root / "workspace"
        self.tools = self.root / "tools"
        for directory in (self.source, self.workspace, self.tools):
            directory.mkdir()
        self.git = shutil.which("git")
        self.jq = shutil.which("jq")
        self.assertIsNotNone(self.git)
        self.assertIsNotNone(self.jq)
        self.bash = shutil.which("bash")
        if os.name == "nt":
            self.bash = next(
                str(directory / "bin" / "bash.exe")
                for directory in Path(self.git).parents
                if (directory / "bin" / "bash.exe").is_file()
            )
        self.environment = dict(os.environ)
        settings = {
            f"url.{self.remote.as_posix()}.insteadOf": "https://gitops.example/repo.git",
            "commit.gpgsign": "false",
            "core.autocrlf": "false",
            "core.hooksPath": self.tools.as_posix(),
        }
        self.environment["GIT_CONFIG_COUNT"] = str(len(settings))
        for index, (key, value) in enumerate(settings.items()):
            self.environment[f"GIT_CONFIG_KEY_{index}"] = key
            self.environment[f"GIT_CONFIG_VALUE_{index}"] = value
        self._git("init", "--bare", self.remote.as_posix())
        self._git("init", "--initial-branch=main")
        self._git("config", "user.name", "Test bot")
        self._git("config", "user.email", "test@example.invalid")
        self._git("remote", "add", "origin", self.remote.as_posix())
        self.previous_image = "ghcr.io/example/app@sha256:" + "a" * 64
        self.failed_image = "ghcr.io/example/app@sha256:" + "b" * 64
        self.manifest_path = "environments/local/kustomization.yaml"
        self.manifest = self.source / self.manifest_path
        self.manifest.parent.mkdir(parents=True)
        self.previous_manifest = {
            "resources": ["../../base"],
            "images": [{"name": "simple-api", "newName": "ghcr.io/example/app", "digest": "sha256:" + "a" * 64}],
        }
        self._commit(self.previous_manifest)
        self._git("push", "origin", "main")
        self._git("symbolic-ref", "HEAD", "refs/heads/main", cwd=self.remote)
        self.output = self.root / "outputs"
        self.output.touch()
        self.log = self.root / "cosign.jsonl"
        self.mock = self.root / "mock.py"
        self.mock.write_text(
            'import json, os, sys\n'
            'if sys.argv[1] == "docker":\n'
            '    entries = [entry for entry in json.load(sys.stdin)["images"] if entry["name"] == os.environ["IMAGE_KEY"]]\n'
            '    if len(entries) != 1: sys.exit(1)\n'
            '    print(json.dumps(entries[0]))\n'
            'else:\n'
            '    args = sys.argv[2:]\n'
            '    with open(os.environ["COSIGN_LOG"], "a", encoding="utf-8") as stream: stream.write(json.dumps(args) + "\\n")\n'
            '    sys.exit(int(os.environ.get("SIGNATURE_EXIT" if args[0] == "verify" else "ATTESTATION_EXIT", "0")))\n',
            encoding="utf-8", newline="\n",
        )
        for name in ("docker", "cosign"):
            tool = self.tools / name
            tool.write_text(
                f'#!/usr/bin/env bash\nexec "$TEST_PYTHON" "$MOCK_PYTHON" {name} "$@"\n',
                encoding="utf-8", newline="\n",
            )
            tool.chmod(0o755)
        wrappers = {
            "git": 'if [[ "${FAIL_PUSH:-false}" == true && " $* " == *" push "* ]]; then exit 23; fi\nexec "$TEST_GIT" "$@"\n',
            "jq": 'set -euo pipefail\n"$TEST_JQ" "$@" | tr -d "\\r"\n',
        }
        for name, body in wrappers.items():
            tool = self.tools / name
            tool.write_text("#!/usr/bin/env bash\n" + body, encoding="utf-8", newline="\n")
            tool.chmod(0o755)

    def _git(self, *arguments, cwd=None):
        result = subprocess.run(
            [self.git, *arguments], cwd=cwd or self.source, env=self.environment,
            capture_output=True, text=True, check=True,
        )
        return result.stdout.strip()

    def _commit(self, manifest, extra_file=False):
        self.manifest.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n")
        if extra_file:
            (self.source / "unrelated.txt").write_text("unrelated\n", encoding="utf-8", newline="\n")
        self._git("add", ".")
        self._git("commit", "-m", "Fixture desired state")
        return self._git("rev-parse", "HEAD")

    def _promote(self, extra_file=False):
        promoted = json.loads(json.dumps(self.previous_manifest))
        promoted["images"][0]["digest"] = "sha256:" + "b" * 64
        self.failed_revision = self._commit(promoted, extra_file)
        self._git("push", "origin", "main")

    def _run(self, **overrides):
        import sys

        workspace = subprocess.run(
            [self.bash, "-c", "pwd"], cwd=self.workspace, capture_output=True, text=True, check=True,
        ).stdout.strip()
        environment = {
            **self.environment,
            "REPO_URL": "https://gitops.example/repo.git", "BRANCH": "main",
            "PROMOTION_REVISION": self.failed_revision, "MANIFEST_PATH": self.manifest_path,
            "IMAGE_KEY": "simple-api", "IMAGE": self.failed_image,
            "REGISTRY": "ghcr.io", "IMAGE_NAME": "example/app", "REPOSITORY": "example/app",
            "IDENTITY": "https://github.com/example/catalog/.github/workflows/dotnet-ci.yml@refs/heads/main",
            "GITHUB_WORKSPACE": workspace, "GITHUB_OUTPUT": self.output.as_posix(),
            "GITOPS_USERNAME": "fixture", "GITOPS_TOKEN": "fixture",
            "MOCK_TOOLS": workspace.rsplit("/", 1)[0] + "/tools",
            "TEST_PYTHON": Path(sys.executable).as_posix(), "MOCK_PYTHON": self.mock.as_posix(),
            "TEST_GIT": Path(self.git).as_posix(), "TEST_JQ": Path(self.jq).as_posix(),
            "COSIGN_LOG": self.log.as_posix(),
            "ROLLBACK_SCRIPT": Path(__file__).with_name("rollback.sh").resolve().as_posix(),
            **overrides,
        }
        result = subprocess.run(
            [self.bash, "-c", 'export PATH="$MOCK_TOOLS:$PATH"; bash "$ROLLBACK_SCRIPT"'],
            cwd=self.workspace, env=environment, capture_output=True, text=True,
        )
        outputs = dict(line.split("=", 1) for line in self.output.read_text().splitlines())
        return result, outputs

    def test_Should_RestoreVerifiedDigest_When_FailedPromotionIsHead(self):
        self._promote()
        result, outputs = self._run()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(outputs["status"], "reverted")
        self.assertEqual(outputs["image"], self.previous_image)
        self.assertEqual(outputs["revision"], self._git("rev-parse", "HEAD", cwd=self.remote))
        restored = json.loads(self._git("show", f"HEAD:{self.manifest_path}", cwd=self.remote))
        self.assertEqual(restored, self.previous_manifest)
        calls = [json.loads(line) for line in self.log.read_text().splitlines()]
        self.assertEqual([call[0] for call in calls], ["verify", "verify-attestation"])
        for call in calls:
            self.assertEqual(call[-1], self.previous_image)
            self.assertIn("--certificate-identity", call)
            self.assertIn("--certificate-github-workflow-repository", call)
            self.assertNotIn("--certificate-identity-regexp", call)

    def test_Should_SkipRollback_When_NewerCommitExists(self):
        self._promote()
        (self.source / "newer.txt").write_text("newer\n", encoding="utf-8")
        self._git("add", ".")
        self._git("commit", "-m", "Newer writer")
        newer = self._git("rev-parse", "HEAD")
        self._git("push", "origin", "main")
        result, outputs = self._run()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(outputs, {"status": "superseded"})
        self.assertEqual(self._git("rev-parse", "HEAD", cwd=self.remote), newer)
        self.assertFalse(self.log.exists())

    def test_Should_RejectRollback_When_PreviousSignatureInvalid(self):
        self._promote()
        result, outputs = self._run(SIGNATURE_EXIT="17")
        self.assertEqual(result.returncode, 17, result.stderr)
        self.assertEqual(outputs, {})
        self.assertEqual(self._git("rev-parse", "HEAD", cwd=self.remote), self.failed_revision)

    def test_Should_RejectRollback_When_PreviousSbomInvalid(self):
        self._promote()
        result, outputs = self._run(ATTESTATION_EXIT="19")
        self.assertEqual(result.returncode, 19, result.stderr)
        self.assertEqual(outputs, {})
        self.assertEqual(self._git("rev-parse", "HEAD", cwd=self.remote), self.failed_revision)

    def test_Should_RejectRollback_When_PreviousImageIsMutable(self):
        mutable = json.loads(json.dumps(self.previous_manifest))
        del mutable["images"][0]["digest"]
        mutable["images"][0]["newTag"] = "latest"
        self._commit(mutable)
        self._promote()
        result, outputs = self._run()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(outputs, {})
        self.assertFalse(self.log.exists())

    def test_Should_RejectRollback_When_CommitChangesOtherFiles(self):
        self._promote(extra_file=True)
        result, outputs = self._run()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(outputs, {})
        self.assertEqual(self._git("rev-parse", "HEAD", cwd=self.remote), self.failed_revision)

    def test_Should_NotReportReverted_When_PushFails(self):
        self._promote()
        result, outputs = self._run(FAIL_PUSH="true")
        self.assertEqual(result.returncode, 23, result.stderr)
        self.assertEqual(outputs, {})
        self.assertEqual(self._git("rev-parse", "HEAD", cwd=self.remote), self.failed_revision)


if __name__ == "__main__":
    unittest.main()