import { readFile, writeFile } from 'node:fs/promises';
import { join } from 'node:path';
import { execute } from './process.mjs';
import { roles, validateResult } from './roles.mjs';

const claudeReadTools = 'Read,Glob,Grep';
const claudeWriteTools = claudeReadTools + ',Edit,Write';

function usageFromClaude(raw) {
  if (!raw) return null;
  const cached = raw.cache_read_input_tokens ?? 0;
  return {
    input: Number.isInteger(raw.input_tokens) ? raw.input_tokens + cached + (raw.cache_creation_input_tokens ?? 0) : null,
    cachedInput: cached, cacheWrite: raw.cache_creation_input_tokens ?? 0,
    output: raw.output_tokens ?? null,
  };
}

function usageFromCodex(raw) {
  if (!raw) return null;
  return { input: raw.input_tokens ?? null, cachedInput: raw.cached_input_tokens ?? null, output: raw.output_tokens ?? null };
}

export async function runRole(provider, executable, role, prompt, { cwd, directory, attempt, timeout, model }) {
  const base = join(directory, `${role}-${attempt}`);
  const { schema } = roles[role];
  const outputPath = base + '.answer.json';
  const schemaPath = base + '.schema.json';
  const writing = role === 'implement';
  let argv, usage = null, response, firstEventMs = null;
  const start = Date.now();
  if (provider === 'codex') {
    await writeFile(schemaPath, JSON.stringify(schema));
    argv = [executable, '-a', 'never', 'exec', '--json', '--ephemeral', '--color', 'never',
      '--sandbox', writing ? 'workspace-write' : 'read-only', '--output-schema', schemaPath,
      '--output-last-message', outputPath, ...(model ? ['--model', model] : []), '-'];
  } else {
    const tools = writing ? claudeWriteTools : claudeReadTools;
    argv = [executable, '-p', '--output-format', 'stream-json', '--verbose', '--json-schema', JSON.stringify(schema),
      '--tools', tools, '--allowedTools', tools, '--permission-mode', writing ? 'acceptEdits' : 'default',
      '--strict-mcp-config', '--mcp-config', '{"mcpServers":{}}', '--no-session-persistence',
      ...(model ? ['--model', model] : [])];
  }

  const result = await execute(argv, { cwd, input: prompt, timeout, log: base + '.jsonl', onLine(line) {
    if (!line.startsWith('{')) return;
    let event;
    try { event = JSON.parse(line); } catch { return; }
    firstEventMs ??= Date.now() - start;
    if (event.type === 'turn.completed') usage = usageFromCodex(event.usage);
    if (event.type === 'result') {
      response = event;
      usage = usageFromClaude(event.usage);
    }
  } });
  if (result.timedOut || result.code !== 0 || response?.is_error || (provider === 'claude' && !response)) {
    const reason = result.timedOut ? 'timeout' : `exit ${result.code}`;
    throw new Error(`${provider} ${role} failed (${reason}). Log: ${base}.jsonl`);
  }
  const answer = provider === 'codex' ? JSON.parse(await readFile(outputPath, 'utf8')) :
    response.structured_output ?? JSON.parse(response.result);
  return {
    answer: validateResult(schema, answer),
    metric: { role, attempt, elapsedMs: result.elapsedMs, firstEventMs, promptBytes: Buffer.byteLength(prompt), usage },
  };
}
