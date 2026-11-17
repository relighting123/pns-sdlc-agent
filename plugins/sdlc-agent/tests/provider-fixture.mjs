#!/usr/bin/env node
import { existsSync, readFileSync, writeFileSync } from 'node:fs';
const args = process.argv.slice(2);
const claude = args.includes('--json-schema');
const schema = JSON.parse(claude ? args[args.indexOf('--json-schema') + 1] :
  readFileSync(args[args.indexOf('--output-schema') + 1], 'utf8'));
let prompt = '';
for await (const data of process.stdin) prompt += data;
const fields = schema.properties;
const source = 'value.txt';
const criterion = { id: 'R1', behavior: 'Returns the correct value', verification: 'Test the changed file' };
let content;
if (fields.criteria) {
  content = { scope: ['value.txt'], nonGoals: [], evidence: ['value.txt:1'],
    blockers: prompt.includes('Needs business rule') && !prompt.includes('User clarification:') ? ['Which value?'] : [], criteria: [criterion] };
} else if (fields.decision) {
  content = { decision: 'Update the source', alternatives: ['Keep behavior'], tasks: ['Edit value.txt'],
    compatibility: ['Existing public interface'], risks: [], verification: [{ criterion: 'R1', procedure: 'Run configured tests' }] };
} else if (fields.changes) {
  if (!(claude ? args.includes('acceptEdits') : args.includes('workspace-write'))) throw new Error('Write policy missing');
  const failOnce = prompt.includes('repair once') && !prompt.includes('"failingChecks"');
  writeFileSync(source, failOnce ? 'bad\n' : 'new\n');
  writeFileSync('new-file.txt', 'coverage\n');
  content = { changes: ['value.txt changed', 'new-file.txt created'], handled: ['R1'], gaps: [] };
} else if (fields.verdict) {
  if (!(claude ? args.includes('Read,Glob,Grep') : args.includes('read-only'))) throw new Error('Read policy missing');
  if (!existsSync('new-file.txt') || !prompt.includes('"new-file.txt"')) throw new Error('New file omitted from review');
  const gap = prompt.includes('Uncovered criterion');
  content = { verdict: 'approve', findings: [], coverage: [{ criterion: 'R1', evidence: 'value.txt:1', status: gap ? 'gap' : 'covered' }] };
} else {
  content = { notes: 'Versioned change', preconditions: ['Checks passed'], rollout: ['Deploy version'],
    smoke: ['Read version'], rollback: ['Restore prior version'], blockers: [] };
}
const answer = { summary: 'Structured result', ...content };
if (claude) {
  console.log(JSON.stringify({ type: 'result', structured_output: answer, usage: {
    input_tokens: 60, cache_creation_input_tokens: 20, cache_read_input_tokens: 20, output_tokens: 10,
  } }));
} else {
  writeFileSync(args[args.indexOf('--output-last-message') + 1], JSON.stringify(answer));
  console.log(JSON.stringify({ type: 'turn.completed', usage: { input_tokens: 100, cached_input_tokens: 20, output_tokens: 10 } }));
}
