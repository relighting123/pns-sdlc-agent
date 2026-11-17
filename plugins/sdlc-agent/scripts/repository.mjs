import { createHash } from 'node:crypto';
import { mkdir, mkdtemp, readFile, realpath, rename, rm, writeFile } from 'node:fs/promises';
import { basename, dirname, join, resolve } from 'node:path';
import { execute } from './process.mjs';

export async function git(cwd, args, env) {
  const out = await execute(['git', ...args], {
    cwd, env: { GIT_OPTIONAL_LOCKS: '0', GIT_TERMINAL_PROMPT: '0', ...env }, timeout: 60_000,
  });
  if (out.code !== 0) throw new Error(`git ${args[0]} failed: ${out.stderr.trim()}`);
  return out.stdout;
}

export async function repository(workspace) {
  const cwd = resolve(workspace);
  const root = await realpath((await git(cwd, ['rev-parse', '--show-toplevel'])).trimEnd());
  const dir = (await git(root, ['rev-parse', '--path-format=absolute', '--git-common-dir'])).trimEnd();
  return { root, storage: join(dir, 'sdlc-agent') };
}

export async function snapshot(tree, directory, base) {
  const scratch = await mkdtemp(join(directory, 'git-index-'));
  const env = { GIT_INDEX_FILE: join(scratch, 'index') };
  try {
    await git(tree, ['read-tree', 'HEAD'], env);
    await git(tree, ['add', '-A', '--', '.'], env);
    const hash = (await git(tree, ['write-tree'], env)).trim();
    const paths = (await git(tree, ['diff', '--no-renames', '--name-only', '-z', base, hash]))
      .split('\0').filter(Boolean);
    return { hash, paths };
  } finally {
    await rm(scratch, { recursive: true, force: true });
  }
}

const commonManifests = new Set([
  'package.json', 'pyproject.toml', 'Cargo.toml', 'go.mod', 'pom.xml', 'build.gradle',
  'build.gradle.kts', 'Makefile', 'Taskfile.yml', 'Dockerfile',
]);

function requestTerms(request) {
  return new Set((request.toLowerCase().match(/[\p{L}\p{N}_-]{3,}/gu) ?? []).slice(0, 100));
}

export async function contextFor(cwd, directory, tree, request, byteLimit) {
  const key = createHash('sha256').update(JSON.stringify([tree, request, byteLimit])).digest('hex');
  const cache = join(directory, 'context');
  const path = join(cache, key + '.json');
  try {
    return { data: JSON.parse(await readFile(path, 'utf8')), cacheHit: true };
  } catch (error) {
    if (error.code !== 'ENOENT') throw error;
  }
  const files = (await git(cwd, ['ls-tree', '-r', '--name-only', '-z', tree])).split('\0').filter(Boolean);
  const terms = requestTerms(request);
  const rank = (path) => {
    const words = path.toLowerCase().split(/[^\p{L}\p{N}_-]+/u);
    return words.reduce((score, word) => score + Number(terms.has(word)), 0)
      + (path === basename(path) && commonManifests.has(path) ? 3 : 0);
  };
  const ranked = files.map((path) => ({ path, score: rank(path) }))
    .sort((a, b) => b.score - a.score || a.path.localeCompare(b.path, 'en'));
  const data = { trackedPaths: files.length, selectedPaths: [] };
  for (const { path } of ranked) {
    if (data.selectedPaths.length === 80) break;
    data.selectedPaths.push(path);
    if (Buffer.byteLength(JSON.stringify(data)) > byteLimit) {
      data.selectedPaths.pop();
      break;
    }
  }
  await mkdir(cache, { recursive: true, mode: 0o700 });
  await atomicJson(path, data);
  return { data, cacheHit: false };
}

export async function atomicJson(path, content) {
  const scratch = await mkdtemp(join(dirname(path), '.write-'));
  const tmp = join(scratch, 'value.json');
  try {
    await writeFile(tmp, JSON.stringify(content, null, 2) + '\n', { mode: 0o600 });
    await rename(tmp, path);
  } finally {
    await rm(scratch, { recursive: true, force: true });
  }
}
