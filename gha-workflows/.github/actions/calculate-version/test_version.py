import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile
import unittest


class VersionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        self.manifest = self.root / 'version.json'
        self.manifest.write_text(json.dumps({
            'version': '1.0.0-preview.{height}',
            'publicReleaseRefSpec': ['^refs/heads/main$'],
        }), encoding='utf-8')
        self.bash = shutil.which('bash')
        self.git = shutil.which('git')
        self.assertIsNotNone(self.bash)
        self.assertIsNotNone(self.git)
        for arguments in (
            ['init', '-q'], ['config', 'user.name', 'Version Test'],
            ['config', 'user.email', 'version-test@example.invalid'],
            ['config', 'core.abbrev', '7'], ['add', 'version.json'],
            ['commit', '-qm', 'Version fixture'],
        ):
            subprocess.run([self.git, '-C', str(self.root), *arguments], check=True,
                           capture_output=True, text=True)
        self.commit = subprocess.check_output(
            [self.git, '-C', str(self.root), 'rev-parse', 'HEAD'], text=True).strip()[:7]
        self.tool = self.bin / 'nbgv'
        self.tool.write_text(
            '#!/usr/bin/env bash\nset -euo pipefail\n'
            '[[ "${MOCK_NBGV_FAILURE:-false}" == false ]]\n'
            'case "$3" in\n'
            '  SemVer2) printf "%s\\n" "$MOCK_SEMVER" ;;\n'
            '  AssemblyVersion) printf "%s\\n" "1.0.0.0" ;;\n'
            '  *) exit 1 ;;\nesac\n', encoding='utf-8')
        self.tool.chmod(0o755)
        clock = self.bin / 'date'
        clock.write_text('#!/usr/bin/env bash\nprintf "%s\\n" "26015"\n', encoding='utf-8')
        clock.chmod(0o755)
        self.startup = self.root / 'bash-env'
        self.startup.write_text(
            'fixture_bin=' + shlex.quote(self.bin.as_posix()) + '\n'
            'if command -v cygpath >/dev/null; then fixture_bin="$(cygpath -u "$fixture_bin")"; fi\n'
            'export PATH="$fixture_bin:$PATH"\n', encoding='utf-8')
        self.output = self.root / 'outputs'
        self.output.write_text('', encoding='utf-8')

    def calculate(self, ref='refs/heads/main', semver='1.0.0-preview.4', arguments=(), **overrides):
        environment = {
            **os.environ,
            'GITHUB_WORKSPACE': self.root.as_posix(),
            'GITHUB_OUTPUT': self.output.as_posix(),
            'GITHUB_REF': ref,
            'GITHUB_RUN_NUMBER': '42',
            'NBGV': self.tool.as_posix(),
            'MOCK_SEMVER': semver,
            'BASH_ENV': self.startup.as_posix(),
        }
        environment.update(overrides)
        script = Path(__file__).with_name('calculate-version.sh')
        result = subprocess.run([self.bash, script.as_posix(), *arguments], env=environment,
                                capture_output=True, text=True)
        outputs = dict(line.split('=', 1) for line in self.output.read_text(
            encoding='utf-8').splitlines())
        return result, outputs

    def test_should_calculate_preview_version_and_all_outputs(self):
        result, outputs = self.calculate()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(outputs, {
            'version': '1.0.0-preview.4.26015.42',
            'assembly_version': '1.0.0.0',
            'informational_version': '1.0.0-preview.4.26015.42+' + self.commit,
            'environment': 'dev', 'docker_tag': '1.0.0-preview.4.26015.42',
            'commit': self.commit,
        })

    def test_should_disable_release_for_zero_preview_height(self):
        result, outputs = self.calculate(semver='1.0.0-preview.0+gabcdef0')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(outputs['environment'], 'none')
        self.assertEqual(outputs['version'], '1.0.0-preview.0')

    def test_should_disable_release_for_stable_version_on_main(self):
        result, outputs = self.calculate(semver='1.0.0')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(outputs['environment'], 'none')

    def test_should_select_production_for_matching_stable_tag(self):
        result, outputs = self.calculate(ref='refs/tags/v1.0.0', semver='1.0.0')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(outputs['version'], '1.0.0')
        self.assertEqual(outputs['docker_tag'], '1.0.0')
        self.assertEqual(outputs['environment'], 'production')

    def test_should_select_staging_and_unique_version_for_matching_rc_tag(self):
        result, outputs = self.calculate(ref='refs/tags/v1.0.0-rc.2', semver='1.0.0-rc.2')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(outputs['version'], '1.0.0-rc.2.26015.42')
        self.assertEqual(outputs['docker_tag'], '1.0.0-rc.2.26015.42')
        self.assertEqual(outputs['environment'], 'staging')

    def test_should_reject_tag_version_mismatch_without_outputs(self):
        result, outputs = self.calculate(ref='refs/tags/v1.0.0', semver='1.1.0')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('does not match NBGV version', result.stderr)
        self.assertEqual(outputs, {})

    def test_should_reject_unsupported_branch_without_outputs(self):
        result, outputs = self.calculate(ref='refs/heads/feature')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Unsupported release ref', result.stderr)
        self.assertEqual(outputs, {})

    def test_should_reject_unsupported_tag_without_outputs(self):
        result, outputs = self.calculate(ref='refs/tags/v1.0.0-beta.1', semver='1.0.0-beta.1')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(outputs, {})

    def test_should_print_valid_manifest_guide_when_root_manifest_missing(self):
        self.manifest.unlink()
        result, outputs = self.calculate()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Missing root version.json', result.stderr)
        guide = json.loads(result.stdout)
        self.assertEqual(guide['version'], '1.0.0-preview.{height}')
        self.assertIn('^refs/heads/main$', guide['publicReleaseRefSpec'])
        self.assertEqual(outputs, {})

    def test_should_reject_malformed_manifest_without_outputs(self):
        self.manifest.write_text('{invalid}', encoding='utf-8')
        result, outputs = self.calculate()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('valid JSON', result.stderr)
        self.assertEqual(outputs, {})

    def test_should_validate_manifest_without_running_nbgv(self):
        result, outputs = self.calculate(arguments=['--validate-manifest'], MOCK_NBGV_FAILURE='true')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(outputs, {})

    def test_should_fail_closed_when_nbgv_fails(self):
        result, outputs = self.calculate(MOCK_NBGV_FAILURE='true')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(outputs, {})

    def test_should_reject_invalid_run_number_without_outputs(self):
        result, outputs = self.calculate(GITHUB_RUN_NUMBER='not-a-number')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(outputs, {})


if __name__ == '__main__':
    unittest.main()