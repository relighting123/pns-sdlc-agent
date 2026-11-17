const string = { type: 'string' };
const list = { type: 'array', items: string };
const record = (fields) => ({
  type: 'object', properties: fields, required: Object.keys(fields), additionalProperties: false,
});
const rows = (fields) => ({ type: 'array', items: record(fields) });

export const roles = {
  requirements: {
    title: 'Requirements analyst',
    instructions: 'Trace the request to existing behavior and repository evidence. Identify scope, non-goals, constraints, failure cases and measurable acceptance criteria. Use unique criterion IDs R1, R2, etc. Report only questions that block a correct implementation.',
    fields: { scope: list, nonGoals: list, evidence: list, blockers: list,
      criteria: rows({ id: string, behavior: string, verification: string }) },
  },
  design: {
    title: 'Software architect',
    instructions: 'Compare viable designs and choose one with trade-offs. Name files, interfaces, dependency order, affected callers and migration/compatibility strategy. Cover idempotency, partial failures and concurrency where applicable. Map acceptance criteria to concrete verification.',
    fields: { decision: string, alternatives: list, tasks: list, compatibility: list, risks: list,
      verification: rows({ criterion: string, procedure: string }) },
  },
  implement: {
    title: 'Software engineer',
    instructions: 'Implement the agreed design in the working directory. Reuse existing abstractions; preserve callers and data. Add regression tests for changed behavior, including meaningful failures. On a repair, address the supplied findings and failing checks. Keep specific unresolved gaps visible. Do not create commits or push.',
    fields: { changes: list, handled: list, gaps: list },
  },
  review: {
    title: 'Independent reviewer',
    instructions: 'Inspect the actual changes against the requested behavior and design. Use the provided changed paths, including new files. Look for regressions, authorization mistakes, data integrity, retries and missing failure-path tests. Ground findings at file:line. Return request_changes for blocking problems. Keep review read-only and defensive.',
    fields: { verdict: { type: 'string', enum: ['approve', 'request_changes'] },
      findings: rows({ severity: { type: 'string', enum: ['blocker', 'high', 'medium', 'low'] }, location: string, issue: string, fix: string }),
      coverage: rows({ criterion: string, evidence: string, status: { type: 'string', enum: ['covered', 'gap'] } }) },
  },
  release: {
    title: 'Release engineer',
    instructions: 'Prepare rollout against the verified change. State migrations and backward compatibility, preconditions, smoke signals, stop criteria and rollback procedure. Identify any unresolved item that should block deployment. The runtime performs deployment; do not deploy.',
    fields: { notes: string, preconditions: list, rollout: list, smoke: list, rollback: list, blockers: list },
  },
};

for (const role of Object.values(roles)) role.schema = record({ summary: string, ...role.fields });

export function validateResult(schema, data, path = '$') {
  if (schema.type === 'array') {
    if (!Array.isArray(data)) throw new Error(`Expected array at ${path}`);
    data.forEach((item, i) => validateResult(schema.items, item, `${path}[${i}]`));
    return data;
  }
  if (schema.type === 'object') {
    if (!data || typeof data !== 'object' || Array.isArray(data)) throw new Error(`Expected object at ${path}`);
    for (const key of schema.required) {
      if (!Object.hasOwn(data, key)) throw new Error(`Missing ${path}.${key}`);
      validateResult(schema.properties[key], data[key], `${path}.${key}`);
    }
    if (Object.keys(data).some((key) => !Object.hasOwn(schema.properties, key))) throw new Error(`Unexpected property at ${path}`);
    return data;
  }
  if (typeof data !== schema.type || !data.trim() || (schema.enum && !schema.enum.includes(data))) {
    throw new Error(`Invalid value at ${path}`);
  }
  return data;
}

export const priorities = {
  requirements: ['Inventory current behavior and callers', 'Define scope and non-goals', 'Write testable acceptance criteria', 'Record blockers and failure modes'],
  design: ['Map components and interfaces', 'Evaluate alternatives', 'Plan compatibility, migration and failure recovery', 'Map criteria to tests and order work'],
  implement: ['Isolate work in Git worktree', 'Implement production paths', 'Cover regression and failure paths', 'Produce exact patch and surface gaps'],
  verify: ['Run configured tests/build/lint', 'Save logs and exit evidence', 'Repair bounded failures then rerun checks'],
  review: ['Review actual diff in separate context', 'Confirm each acceptance criterion', 'Block on high-severity findings or coverage gaps'],
  release: ['Prepare rollout, smoke and rollback', 'Pin verification to Git tree and commit', 'Run configured deploy, smoke and rollback commands when explicitly invoked'],
};
