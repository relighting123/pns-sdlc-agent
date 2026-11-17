import { join } from 'node:path';
import { randomUUID } from 'node:crypto';
import { git, snapshot } from './repository.mjs';
import { Blocked, runCommand } from './flow.mjs';

async function assertVerified(run) {
  const { state, directory } = run;
  if (state.status !== 'ready') throw new Blocked('Run has no verified release.');
  if ((await snapshot(state.worktree, directory, state.base)).hash !== state.verified.tree) {
    throw new Blocked('Worktree changed after verification. Resume and reverify before release.');
  }
}

export async function commit(run, message) {
  const { state } = run;
  const { worktree, verified } = state;
  if (!message?.trim()) throw new Error('Pass a commit --message.');
  await assertVerified(run);
  const head = (await git(worktree, ['rev-parse', 'HEAD'])).trim();
  const existing = (await git(worktree, ['rev-parse', 'HEAD^{tree}'])).trim();
  if (existing === verified.tree) return { commit: head, tree: existing, existing: true };
  if (head !== state.base) throw new Blocked('Worktree HEAD changed. Commit the verified tree manually or start a new run.');
  await git(worktree, ['add', '-A', '--', '.']);
  if ((await git(worktree, ['write-tree'])).trim() !== verified.tree) throw new Blocked('Staged tree differs from the verified tree.');
  await git(worktree, ['commit', '-m', message]);
  const sha = (await git(worktree, ['rev-parse', 'HEAD'])).trim();
  if ((await git(worktree, ['rev-parse', 'HEAD^{tree}'])).trim() !== verified.tree) {
    throw new Blocked(`Created ${sha}, but a hook changed the verified tree. Resume before release.`);
  }
  return { commit: sha, tree: verified.tree };
}

function environmentFor(state, name) {
  if (!name || !Object.hasOwn(state.config.environments, name)) throw new Error('Choose a configured --environment.');
  return state.config.environments[name];
}

export async function deploy(run, name, sha) {
  const { state, directory, save } = run;
  const config = environmentFor(state, name);
  if (!/^(?:[a-f0-9]{40}|[a-f0-9]{64})$/.test(sha ?? '')) throw new Error('Pass the full verified Git commit SHA via --commit.');
  await assertVerified(run);
  if (Object.hasOwn(state.deployments, name)) throw new Blocked('This run already attempted that environment. Inspect the receipt before a new deployment.');
  const head = (await git(state.worktree, ['rev-parse', 'HEAD'])).trim();
  const tree = (await git(state.worktree, ['rev-parse', 'HEAD^{tree}'])).trim();
  if (head !== sha || tree !== state.verified.tree) throw new Blocked('Deployment commit must be the current worktree HEAD and match the verified tree.');
  const receipt = { operation: randomUUID(), environment: name, commit: sha, tree, status: 'deploying', started: new Date().toISOString(), steps: {} };
  state.deployments[name] = receipt;
  await save();
  const env = releaseEnvironment(state, receipt);
  try {
    receipt.steps.deploy = await runCommand(config.deploy, state.worktree, directory, `deploy-${name}`, env);
    receipt.status = receipt.steps.deploy.passed ? 'checking-smoke' : 'deploy-failed';
    await save();
    if (!receipt.steps.deploy.passed) throw new Blocked('Deployment command failed. Inspect the receipt and use rollback if needed.');
    receipt.steps.smoke = await runCommand(config.smoke, state.worktree, directory, `smoke-${name}`, env);
    receipt.status = receipt.steps.smoke.passed ? 'deployed' : 'smoke-failed';
    await save();
    if (!receipt.steps.smoke.passed) throw new Blocked('Deployment smoke check failed. Rollback is available for this receipt.');
    return receipt;
  } catch (error) {
    if (!(error instanceof Blocked)) {
      receipt.status = 'deploy-uncertain';
      receipt.error = error.message;
      await save();
    }
    throw error;
  }
}

function releaseEnvironment(state, receipt) {
  return {
    SDLC_RUN_ID: state.id, SDLC_OPERATION_ID: receipt.operation, SDLC_ENVIRONMENT: receipt.environment,
    SDLC_COMMIT: receipt.commit, SDLC_TREE: receipt.tree, SDLC_BASE_COMMIT: state.base,
  };
}

export async function rollback(run, name) {
  const { state, directory, save } = run;
  const config = environmentFor(state, name);
  const receipt = state.deployments[name];
  if (!receipt) throw new Blocked('There is no deployment receipt to roll back.');
  if (receipt.status === 'rolled-back') return receipt;
  if (receipt.status === 'rolling-back') throw new Blocked('Previous rollback outcome is uncertain. Check the deployment system before taking further action.');
  if ((await git(state.worktree, ['rev-parse', 'HEAD'])).trim() !== receipt.commit
      || (await snapshot(state.worktree, directory, state.base)).hash !== receipt.tree) {
    throw new Blocked('Restore the recorded release tree before running rollback.');
  }
  receipt.status = 'rolling-back';
  await save();
  try {
    receipt.steps.rollback = await runCommand(config.rollback, state.worktree, directory, `rollback-${name}`, releaseEnvironment(state, receipt));
    receipt.status = receipt.steps.rollback.passed ? 'rolled-back' : 'rollback-failed';
    await save();
    if (!receipt.steps.rollback.passed) throw new Blocked('Rollback command failed. Inspect the receipt and log before retrying.');
    return receipt;
  } catch (error) {
    if (!(error instanceof Blocked)) {
      receipt.error = error.message;
      await save();
    }
    throw error;
  }
}

export function compareMetrics(baseline, candidate) {
  const delta = (a, b) => Number.isFinite(a) && Number.isFinite(b) ? b - a : null;
  return {
    baseline: baseline.id, candidate: candidate.id,
    inputTokenDelta: baseline.modelInvocations === baseline.invocationsReportingInput
      && candidate.modelInvocations === candidate.invocationsReportingInput
      ? delta(baseline.measuredInputTokens, candidate.measuredInputTokens) : null,
    cacheReadRatioDelta: delta(baseline.cacheReadRatio, candidate.cacheReadRatio),
    summedModelMsDelta: delta(baseline.summedModelMs, candidate.summedModelMs),
    activePipelineMsDelta: delta(baseline.activePipelineMs, candidate.activePipelineMs),
    invocationDelta: candidate.modelInvocations - baseline.modelInvocations,
  };
}
