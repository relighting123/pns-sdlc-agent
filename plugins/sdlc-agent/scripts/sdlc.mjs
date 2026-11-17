#!/usr/bin/env node
import { readFile } from 'node:fs/promises';
import { parseArgs } from 'node:util';
import { loadConfig } from './config.mjs';
import { repository } from './repository.mjs';
import { advance, Blocked, loadRun, metricsFor, startRun, unlock, withRun } from './flow.mjs';
import { commit, compareMetrics, deploy, rollback } from './release.mjs';
import { installCodexAgents } from './install-agents.mjs';
import { priorities } from './roles.mjs';

const usage = `sdlc-agent <command> [--workspace path]
  catalog
  install-agents
  plan | run --config path (--request text | --request-file path)
  resume --run id [--clarification text]
  status | metrics | unlock --run id
  compare --baseline id --run id
  commit --run id --message text
  deploy --run id --environment name --commit full-sha
  rollback --run id --environment name
`;

const options = {
  help: { type: 'boolean', short: 'h' },
  workspace: { type: 'string', default: process.cwd() },
  config: { type: 'string' }, request: { type: 'string' }, 'request-file': { type: 'string' },
  run: { type: 'string' }, clarification: { type: 'string' }, baseline: { type: 'string' },
  message: { type: 'string' }, environment: { type: 'string' }, commit: { type: 'string' },
};
const commandOptions = {
  catalog: [], 'install-agents': [], plan: ['config', 'request', 'request-file'], run: ['config', 'request', 'request-file'],
  resume: ['run', 'clarification'], status: ['run'], metrics: ['run'], unlock: ['run'],
  compare: ['run', 'baseline'], commit: ['run', 'message'], deploy: ['run', 'environment', 'commit'],
  rollback: ['run', 'environment'],
};

async function main() {
  const { values, positionals } = parseArgs({ options, allowPositionals: true });
  const [action] = positionals;
  if (values.help || !action) { process.stdout.write(usage); return undefined; }
  if (positionals.length !== 1 || !Object.hasOwn(commandOptions, action)) throw new Error('Unknown command. See --help.');
  const permitted = ['workspace', ...commandOptions[action]];
  for (const option of Object.keys(values)) if (!permitted.includes(option)) throw new Error(`Unexpected --${option} for ${action}.`);
  if (action === 'catalog') return priorities;
  const repo = await repository(values.workspace);
  if (action === 'install-agents') return { files: await installCodexAgents(repo.root) };
  if (action === 'plan' || action === 'run') {
    if (!values.config || (values.request === undefined) === (values['request-file'] === undefined)) {
      throw new Error('Pass --config and exactly one request input.');
    }
    const request = values.request ?? await readFile(values['request-file'], 'utf8');
    const id = await startRun(repo, await loadConfig(values.config), request);
    process.stderr.write(`SDLC run ${id}\n`);
    return withRun(repo, id, (run) => advance(run, { planOnly: action === 'plan' }));
  }
  if (action === 'status') return (await loadRun(repo, values.run)).state;
  if (action === 'metrics') return metricsFor((await loadRun(repo, values.run)).state);
  if (action === 'compare') {
    const [baseline, candidate] = await Promise.all([loadRun(repo, values.baseline), loadRun(repo, values.run)]);
    if (baseline.state.base !== candidate.state.base || baseline.state.request !== candidate.state.request) {
      throw new Error('Compare runs with the same base commit and request.');
    }
    return compareMetrics(metricsFor(baseline.state), metricsFor(candidate.state));
  }
  if (action === 'unlock') { await unlock(repo, values.run); return { unlocked: values.run }; }
  return withRun(repo, values.run, async (run) => {
    if (action === 'resume') return advance(run, { clarification: values.clarification });
    if (action === 'commit') return commit(run, values.message);
    if (action === 'deploy') return deploy(run, values.environment, values.commit);
    return rollback(run, values.environment);
  });
}

try {
  const result = await main();
  if (result !== undefined) process.stdout.write(JSON.stringify(result, null, 2) + '\n');
} catch (error) {
  process.stderr.write(error.message + '\n');
  process.exitCode = error instanceof Blocked ? 2 : 1;
}
