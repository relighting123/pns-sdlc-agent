import { test } from 'node:test';
import assert from 'node:assert/strict';
import { execFileSync, spawnSync } from 'node:child_process';
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';

const cli = fileURLToPath(new URL('../scripts/sdlc.mjs', import.meta.url));
const provider = fileURLToPath(new URL('./provider-fixture.mjs', import.meta.url));
const node = process.execPath;
const stage = (name, code) => ({ name, argv: [node, '--input-type=module', '-e', code] });

async function fixture(t, overrides = {}) {
  const cwd = await mkdtemp(join(tmpdir(), 'sdlc-agent-tests-'));
  t.after(() => rm(cwd, { recursive: true, force: true }));
  const git = (...args) => execFileSync('git', args, { cwd, encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] }).trim();
  git('init', '-q');
  git('config', 'user.name', 'SDLC Local Test');
  git('config', 'user.email', 'test@example.invalid');
  await writeFile(join(cwd, 'value.txt'), 'old\n');
  git('add', 'value.txt');
  git('commit', '-qm', 'Base');
  const check = stage('unit', "import fs from 'node:fs'; if (fs.readFileSync('value.txt', 'utf8').trim() !== 'new') { console.error('wrong value'); process.exit(7); }");
  const deployment = (step) => stage(step,
    "import fs from 'node:fs'; if (!process.env.SDLC_COMMIT || !process.env.SDLC_OPERATION_ID) process.exit(3); " +
    "fs.appendFileSync(" + JSON.stringify(join(cwd, 'deployment.log')) + ", " + JSON.stringify(step + '\n') + ");");
  const config = join(cwd, 'sdlc.json');
  await writeFile(config, JSON.stringify({ executable: provider, checks: [check], timeoutMs: 10_000,
    environments: { staging: { deploy: deployment('deploy'), smoke: deployment('smoke'), rollback: deployment('rollback') } }, ...overrides }));
  const run = (command, ...args) => {
    const result = spawnSync(node, [cli, command, '--workspace', cwd, ...args], { encoding: 'utf8', timeout: 30_000 });
    assert.ifError(result.error);
    return { status: result.status, err: result.stderr, data: result.stdout ? JSON.parse(result.stdout) : undefined,
      id: result.stderr.match(/SDLC run ([a-f0-9-]+)/)?.[1] };
  };
  const start = (request, command = 'run') => run(command, '--config', config, '--request', request);
  return { cwd, git, run, start };
}

test('full Codex protocol, actual Git edits, failed check repair, exact deploy, and rollback', async (t) => {
  const { cwd, git, run, start } = await fixture(t);
  const { status, id, data, err } = start('Improve value; repair once');
  assert.equal(status, 0, err);
  assert.equal(data.status, 'ready');
  assert.equal(data.repair, 1);
  assert.deepEqual(data.checks.map((check) => check.passed), [true]);
  assert.equal(await readFile(join(cwd, 'value.txt'), 'utf8'), 'old\n');
  assert.equal(await readFile(join(data.worktree, 'value.txt'), 'utf8'), 'new\n');
  assert.match(await readFile(join(cwd, '.git', 'sdlc-agent', 'runs', id, 'check-1-unit.log'), 'utf8'), /wrong value/);
  assert.equal(git('diff', 'HEAD'), '');
  const metric = run('metrics', '--run', id).data;
  assert.equal(metric.modelInvocations, 7);
  assert.equal(metric.measuredInputTokens, 700);
  assert.equal(metric.cacheReadRatio, 0.2);
  assert.equal(metric.model[1].contextCacheHit, true);
  assert.ok(metric.activePipelineMs > 0);
  const { data: committed } = run('commit', '--run', id, '--message', 'Update value');
  assert.ok(committed?.commit);
  assert.equal(run('deploy', '--run', id, '--environment', 'staging', '--commit', data.base).status, 2);
  assert.equal(run('deploy', '--run', id, '--environment', 'staging', '--commit', committed.commit).data.status, 'deployed');
  assert.equal(run('deploy', '--run', id, '--environment', 'staging', '--commit', committed.commit).status, 2);
  assert.equal(run('rollback', '--run', id, '--environment', 'staging').data.status, 'rolled-back');
  assert.equal(run('rollback', '--run', id, '--environment', 'staging').data.status, 'rolled-back');
  assert.equal(await readFile(join(cwd, 'deployment.log'), 'utf8'), 'deploy\nsmoke\nrollback\n');
  assert.equal(run('compare', '--baseline', id, '--run', id).data.inputTokenDelta, 0);
});

test('Claude protocol and clarification resume reuse planning and report cache writes', async (t) => {
  const { run, start } = await fixture(t, { provider: 'claude' });
  const blocked = start('Needs business rule', 'plan');
  assert.equal(blocked.status, 2);
  assert.equal(run('status', '--run', blocked.id).data.artifacts.requirements.blockers[0], 'Which value?');
  const result = run('resume', '--run', blocked.id, '--clarification', 'Accept the new value');
  assert.equal(result.status, 0, result.err);
  assert.equal(result.data.status, 'ready');
  assert.equal(result.data.metrics[0].usage.cacheWrite, 20);
  assert.equal(result.data.metrics[0].usage.input, 100);
});

test('plan-only stops at design and stale worktree blocks release until reverified', async (t) => {
  const { run, start } = await fixture(t);
  const planned = start('Update value', 'plan');
  assert.equal(planned.status, 0, planned.err);
  assert.equal(planned.data.status, 'planned');
  assert.equal(planned.data.metrics.length, 2);
  const ready = run('resume', '--run', planned.id).data;
  await writeFile(join(ready.worktree, 'new-file.txt'), 'another change\n');
  assert.equal(run('commit', '--run', planned.id, '--message', 'Changed').status, 2);
  const updated = run('resume', '--run', planned.id).data;
  assert.equal(updated.status, 'ready');
  assert.notEqual(updated.verified.tree, ready.verified.tree);
  assert.equal(updated.metrics.length, 7);
});

test('a reviewer coverage gap blocks even when the configured command passes', async (t) => {
  const { run, start } = await fixture(t, { repairAttempts: 0 });
  const output = start('Uncovered criterion');
  assert.equal(output.status, 2);
  const state = run('status', '--run', output.id).data;
  assert.equal(state.checks[0].passed, true);
  assert.equal(state.artifacts.review.coverage[0].status, 'gap');
  assert.equal(run('commit', '--run', output.id, '--message', 'Unverified').status, 2);
});

test('a configured observed budget stops the next model call', async (t) => {
  const { run, start } = await fixture(t, { maxInputTokens: 100 });
  const output = start('Update value');
  assert.equal(output.status, 2);
  const state = run('status', '--run', output.id).data;
  assert.equal(state.metrics.length, 1);
  assert.equal(state.phase, 'design');
});

test('source-changing verification blocks the run', async (t) => {
  const { run, start } = await fixture(t, { checks: [
    stage('write-source', "import fs from 'node:fs'; fs.appendFileSync('value.txt','unexpected');"),
  ] });
  const output = start('Update value');
  assert.equal(output.status, 2);
  assert.match(output.err, /Verification changed Git-visible files/);
  assert.equal(run('status', '--run', output.id).data.verified, undefined);
});

test('a failed smoke check records failure and preserves a rollback path', async (t) => {
  const { run, start } = await fixture(t, { environments: { staging: {
    deploy: stage('deploy', 'process.exit(0)'),
    smoke: stage('smoke', 'process.exit(9)'),
    rollback: stage('rollback', 'process.exit(0)'),
  } } });
  const ready = start('Update value');
  assert.equal(ready.status, 0, ready.err);
  const committed = run('commit', '--run', ready.id, '--message', 'Update value');
  const release = run('deploy', '--run', ready.id, '--environment', 'staging', '--commit', committed.data.commit);
  assert.equal(release.status, 2);
  const receipt = run('status', '--run', ready.id).data.deployments.staging;
  assert.equal(receipt.status, 'smoke-failed');
  assert.equal(receipt.steps.smoke.code, 9);
  assert.equal(run('rollback', '--run', ready.id, '--environment', 'staging').data.status, 'rolled-back');
});

test('Codex subagent installation is idempotent and preserves author edits', async (t) => {
  const { run } = await fixture(t);
  const first = run('install-agents');
  assert.equal(first.data.files.length, 5);
  assert.equal(run('install-agents').status, 0);
  const custom = first.data.files[0];
  await writeFile(custom, 'user-owned role\n');
  assert.equal(run('install-agents').status, 1);
  assert.equal(await readFile(custom, 'utf8'), 'user-owned role\n');
});
