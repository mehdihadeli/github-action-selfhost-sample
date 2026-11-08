import json
import os
import pathlib

stages = json.loads(os.environ['STAGES'])
required = [name for name in os.environ.get('REQUIRED', '').split(',') if name]
failures = [name for name in required if stages.get(name, {}).get('result') != 'success']
status = ('FAIL' if failures else 'PASS') if required else 'REPORT_ONLY'
configuration = json.loads(os.environ.get('CONFIGURATION', '{}'))
allowed_settings = [
    'test-project', 'test-platform', 'e2e-test-project', 'e2e-test-platform',
    'require-tests', 'collect-coverage', 'enable-snyk', 'enable-sonar',
    'enable-dependency-track', 'require-docker-healthcheck', 'validate-deployment',
    'enable-k6', 'enable-zap', 'argocd-allow-http',
]
name = os.environ['EVIDENCE_NAME']
if not name.replace('-', '').replace('_', '').isalnum():
    raise SystemExit('Invalid evidence artifact name.')
directory = pathlib.Path('artifacts') / name
directory.mkdir(parents=True, exist_ok=True)
metadata = {
    'repository': os.environ.get('GITHUB_REPOSITORY'),
    'sourceRevision': os.environ['SOURCE_REVISION'],
    'runId': os.environ.get('GITHUB_RUN_ID'),
    'runAttempt': os.environ.get('GITHUB_RUN_ATTEMPT'),
    'image': os.environ.get('IMAGE', ''),
    'gitopsRevision': os.environ.get('GITOPS_REVISION', ''),
    'configuration': {key: configuration[key] for key in allowed_settings if key in configuration},
    'gateStatus': status,
    'requiredJobs': required,
    'stages': {stage: value.get('result') for stage, value in stages.items()},
}
(directory / 'metadata.json').write_text(json.dumps(metadata, indent=2) + '\n')
summary = '\n'.join([
    f'## {name}', f'Gate: {status}', f'Commit: {metadata["sourceRevision"]}',
    '', '| Stage | Result |', '| --- | --- |',
    *[f'| {stage} | {result} |' for stage, result in metadata['stages'].items()], '',
])
(directory / 'summary.md').write_text(summary)
with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as output:
    output.write(summary)
with open(os.environ['GITHUB_OUTPUT'], 'a') as output:
    output.write(f'gate-status={status}\n')
if failures:
    raise SystemExit('Required stages failed, skipped, or cancelled: ' + ', '.join(failures))