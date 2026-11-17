import { readFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import { roles } from './roles.mjs';

const named = /^[a-z][a-z0-9-]{0,39}$/;
const bad = (label) => { throw new Error(`Invalid configuration: ${label}`); };

function object(value, keys, label) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) bad(label);
  for (const key of Object.keys(value)) if (!keys.includes(key)) bad(`${label}.${key}`);
  return value;
}

function integer(value, min, max, label) {
  if (!Number.isSafeInteger(value) || value < min || value > max) bad(label);
  return value;
}

function command(entry, label, timeoutMs) {
  object(entry, ['name', 'argv', 'timeoutMs'], label);
  if (typeof entry.name !== 'string' || !named.test(entry.name)) bad(`${label}.name`);
  if (!Array.isArray(entry.argv) || !entry.argv.length || !entry.argv.every((part) => typeof part === 'string' && !part.includes('\0')) || !entry.argv[0]) bad(`${label}.argv`);
  return { name: entry.name, argv: entry.argv, timeoutMs: integer(entry.timeoutMs ?? timeoutMs, 100, 3_600_000, label) };
}

export async function loadConfig(path) {
  const raw = JSON.parse(await readFile(resolve(path), 'utf8'));
  object(raw, ['provider', 'executable', 'models', 'timeoutMs', 'promptBytes', 'contextBytes', 'repairAttempts', 'maxInputTokens', 'checks', 'environments'], 'root');
  const provider = raw.provider ?? 'codex';
  if (!['codex', 'claude'].includes(provider)) bad('provider');
  const executable = raw.executable ?? provider;
  if (typeof executable !== 'string' || !executable || executable.includes('\0')) bad('executable');
  const timeoutMs = integer(raw.timeoutMs ?? 600_000, 100, 3_600_000, 'timeoutMs');
  const promptBytes = integer(raw.promptBytes ?? 24_000, 4_000, 200_000, 'promptBytes');
  const contextBytes = integer(raw.contextBytes ?? 4_000, 100, Math.floor(promptBytes / 2), 'contextBytes');
  const repairAttempts = integer(raw.repairAttempts ?? 2, 0, 10, 'repairAttempts');
  const maxInputTokens = integer(raw.maxInputTokens ?? 0, 0, 20_000_000, 'maxInputTokens');
  const models = object(raw.models ?? {}, Object.keys(roles), 'models');
  for (const model of Object.values(models)) if (typeof model !== 'string' || !model.trim()) bad('models');
  if (!Array.isArray(raw.checks) || !raw.checks.length) bad('checks: provide at least one real check command');
  const checks = raw.checks.map((entry, index) => command(entry, `checks[${index}]`, timeoutMs));
  if (new Set(checks.map(({ name }) => name)).size !== checks.length) bad('checks: duplicate name');
  const entries = raw.environments ?? {};
  object(entries, Object.keys(entries), 'environments');
  const environments = Object.fromEntries(Object.entries(entries).map(([name, e]) => {
    if (!named.test(name)) bad('environments name');
    object(e, ['deploy', 'smoke', 'rollback'], `environments.${name}`);
    return [name, Object.fromEntries(['deploy', 'smoke', 'rollback'].map((step) =>
      [step, command(e[step], `environments.${name}.${step}`, timeoutMs)]))];
  }));
  return { provider, executable, models, timeoutMs, promptBytes, contextBytes, repairAttempts, maxInputTokens, checks, environments };
}
