import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { cpSync, existsSync, mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const app = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const catalog = path.resolve(app, '../gha-workflows');
const compose = path.join(app, 'deployments/gitea-setup/docker-compose.yaml');
const server = 'http://localhost:3000';
const owner = 'admin';
const application = 'dotnet-github-action-self-host-runner';
const scratch = mkdtempSync(path.join(tmpdir(), 'local-gitea-'));
const tokenName = `local-setup-${Date.now()}`;
let token;
let tokenId;

function run(command, args, options = {}) {
  const result = spawnSync(command, args, {
    encoding: 'utf8', maxBuffer: 8 * 1024 * 1024, ...options,
  });
  assert.equal(result.status, 0, `${command} failed (exit ${result.status}); credentials and process output withheld`);
  return result.stdout.trim();
}

async function api(route, method = 'GET', body) {
  const response = await fetch(`${server}/api/v1${route}`, {
    method,
    headers: { Authorization: `token ${token}`, 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  assert.ok(response.ok, `Local Gitea ${method} ${route}: HTTP ${response.status}`);
  return response.status === 204 ? null : response.json();
}

function publish(source, name) {
  const target = path.join(scratch, name);
  const excluded = new Set(['.git', 'bin', 'obj', 'node_modules', '__pycache__', '.venv', '.env', 'artifacts', 'TestResults']);
  cpSync(source, target, {
    recursive: true,
    filter: candidate => {
      const relative = path.relative(source, candidate).split(path.sep);
      return !relative.some(part => excluded.has(part) || part.startsWith('.env.') || /\.(pfx|p12|key)$/i.test(part))
        && !(relative[0] === '.github' && relative[1] === 'workflows');
    },
  });
  run('git', ['init', '--initial-branch=main', target]);
  run('git', ['add', '.'], { cwd: target });
  run('git', ['-c', 'user.name=Local Gitea Setup', '-c', 'user.email=local-setup@localhost', 'commit', '-m', 'Publish local Actions source snapshot'], { cwd: target });
  run('git', ['remote', 'add', 'origin', `${server}/${owner}/${name}.git`], { cwd: target });
  const authorization = Buffer.from(`${owner}:${token}`).toString('base64');
  run('git', ['push', 'origin', 'main'], {
    cwd: target,
    env: {
      ...process.env, GIT_TERMINAL_PROMPT: '0', GIT_CONFIG_COUNT: '1',
      GIT_CONFIG_KEY_0: 'http.extraHeader', GIT_CONFIG_VALUE_0: `Authorization: Basic ${authorization}`,
    },
  });
  console.log(`Published ${server}/${owner}/${name}; existing worktree and staging unchanged`);
}

try {
  assert.ok(existsSync(catalog), 'Local workflow catalog is missing');
  run('docker', ['compose', '-f', compose, '--profile', 'actions', 'up', '-d', '--no-recreate', 'server']);
  token = run('docker', ['exec', '--user', '1000:1000', 'gitea', 'gitea', '--config', '/data/gitea/conf/app.ini',
    'admin', 'user', 'generate-access-token', '--username', owner, '--token-name', tokenName, '--scopes', 'write:repository,write:user', '--raw']);
  const tokens = await api(`/users/${owner}/tokens`);
  tokenId = tokens.find(candidate => candidate.name === tokenName)?.id;
  assert.ok(tokenId, 'Cannot identify temporary setup token for revocation');
  const repositories = await api('/user/repos?limit=100');
  for (const name of ['gha-workflows', application]) {
    assert.ok(!repositories.some(repository => repository.full_name === `${owner}/${name}`),
      `Local repository ${owner}/${name} already exists; refusing to overwrite its history`);
    await api('/user/repos', 'POST', { name, private: false, auto_init: false, default_branch: 'main' });
    await api(`/repos/${owner}/${name}`, 'PATCH', { has_actions: true });
  }
  publish(catalog, 'gha-workflows');
  run('docker', ['compose', '-f', compose, '--profile', 'actions', 'create', 'runner']);
  const registration = run('docker', ['exec', '--user', '1000:1000', 'gitea', 'gitea', '--config', '/data/gitea/conf/app.ini',
    'actions', 'generate-runner-token', '--scope', `${owner}/${application}`]);
  const registrationToken = registration.match(/\b[0-9a-f]{40,}\b/i)?.[0];
  assert.ok(registrationToken, 'Runner registration token format not recognized; output withheld');
  run('docker', ['run', '--rm', '-i', '--network', 'gitea_gitea', '-v', 'gitea_runner-data:/data', '-w', '/data',
    '--entrypoint', 'gitea-runner', 'local-gitea-dotnet-runner:10.0', 'register', '--instance', 'http://server:3000',
    '--token-file', '/dev/stdin', '--name', 'local-dotnet', '--labels', 'local-dotnet:host', '--no-interactive'],
  { input: `${registrationToken}\n` });
  run('docker', ['compose', '-f', compose, '--profile', 'actions', 'start', 'runner']);
  console.log('Started repository-scoped local-dotnet runner; registration credential stored only in Docker volume');
  publish(app, application);
  console.log(`Actions: ${server}/${owner}/${application}/actions`);
} finally {
  try {
    if (token) {
      if (!tokenId) {
        const tokens = await api(`/users/${owner}/tokens`);
        tokenId = tokens.find(candidate => candidate.name === tokenName)?.id;
      }
      assert.ok(tokenId, 'Temporary token revocation needs attention');
      await api(`/users/${owner}/tokens/${tokenId}`, 'DELETE');
      console.log('Temporary setup access token revoked');
    }
  } finally {
    rmSync(scratch, { recursive: true, force: true });
  }
}