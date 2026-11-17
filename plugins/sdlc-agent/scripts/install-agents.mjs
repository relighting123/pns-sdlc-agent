import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { join } from 'node:path';
import { roles } from './roles.mjs';

export async function installCodexAgents(root) {
  const directory = join(root, '.codex', 'agents');
  await mkdir(directory, { recursive: true });
  const files = [];
  for (const [role, { title, instructions }] of Object.entries(roles)) {
    const name = 'sdlc-' + role;
    const path = join(directory, name + '.toml');
    const text = [
      'name = ' + JSON.stringify(name),
      'description = ' + JSON.stringify(title + ' for the SDLC Agent delivery workflow.'),
      'developer_instructions = ' + JSON.stringify(instructions),
    ].join('\n') + '\n';
    try { await writeFile(path, text, { flag: 'wx' }); }
    catch (error) {
      if (error.code !== 'EEXIST' || await readFile(path, 'utf8') !== text) throw error;
    }
    files.push(path);
  }
  return files;
}
