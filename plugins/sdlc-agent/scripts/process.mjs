import { spawn } from 'node:child_process';
import { createWriteStream } from 'node:fs';
import { finished } from 'node:stream/promises';
import { StringDecoder } from 'node:string_decoder';
import { performance } from 'node:perf_hooks';

export async function execute(argv, { cwd, input, env, timeout = 120_000, log, onLine } = {}) {
  const start = performance.now();
  const child = spawn(argv[0], argv.slice(1), {
    cwd, env: { ...process.env, ...env }, shell: false, windowsHide: true, detached: process.platform !== 'win32',
    stdio: [input === undefined ? 'ignore' : 'pipe', 'pipe', 'pipe'],
  });
  const output = log ? createWriteStream(log, { mode: 0o600 }) : null;
  const flushed = output ? finished(output) : Promise.resolve();
  flushed.catch(() => {});
  const decoder = new StringDecoder('utf8');
  let residual = '', stdout = '', stderr = '', timedOut = false, truncated = false, firstOutputMs, failure;
  const limit = 2_000_000;

  const terminate = () => {
    if (!child.pid) return;
    try {
      if (process.platform === 'win32') {
        spawn('taskkill', ['/pid', String(child.pid), '/t', '/f'], { windowsHide: true, stdio: 'ignore' })
          .on('error', () => child.kill());
      } else {
        process.kill(-child.pid, 'SIGKILL');
      }
    } catch (error) {
      if (error.code !== 'ESRCH') child.kill();
    }
  };

  const emitLines = (text) => {
    if (!onLine || failure) return;
    try {
      residual += text;
      const lines = residual.split('\n');
      residual = lines.pop();
      if (residual.length > limit) throw new Error('Provider event exceeds the supported line size');
      for (const line of lines) onLine(line);
    } catch (error) {
      failure = error;
      terminate();
    }
  };

  const capture = (stream, save) => (chunk) => {
    firstOutputMs ??= Math.round(performance.now() - start);
    save(chunk);
    if (output && !output.destroyed && !output.write(chunk)) {
      stream.pause();
      const resume = () => {
        output.off('drain', resume);
        output.off('close', resume);
        stream.resume();
      };
      output.on('drain', resume);
      output.on('close', resume);
    }
  };
  child.stdout.on('data', capture(child.stdout, (chunk) => {
    const text = decoder.write(chunk);
    if (stdout.length + text.length > limit) truncated = true;
    if (log) stdout = (stdout + text).slice(-8_000);
    else if (!truncated) stdout += text;
    emitLines(text);
  }));
  child.stderr.setEncoding('utf8');
  child.stderr.on('data', capture(child.stderr, (text) => { stderr = (stderr + text).slice(-8_000); }));
  if (input !== undefined) {
    child.stdin.on('error', () => {});
    child.stdin.end(input);
  }
  output?.on('error', (error) => { failure = error; terminate(); });
  const timer = setTimeout(() => { timedOut = true; terminate(); }, timeout);
  let result;
  try {
    result = await new Promise((resolve) => {
      child.on('error', (error) => { failure = error; });
      child.on('close', (code, signal) => resolve({ code, signal }));
    });
    emitLines(decoder.end() + '\n');
  } finally {
    clearTimeout(timer);
    output?.end();
    await flushed;
  }
  if (failure) throw failure;
  if (!log && truncated) throw new Error(`Output too large: ${argv[0]}`);
  return { ...result, stdout, stderr, timedOut, firstOutputMs: firstOutputMs ?? null, elapsedMs: Math.round(performance.now() - start) };
}
