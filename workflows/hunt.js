// Claude Code Workflow engine for new-model-hunt: fan out one agent per prompt file.
// The sandbox has no file access, so every prompt lives on disk (written by hunt.py) and each
// agent is told to read its own. Run once for the hunt phase and once for the skeptic phase:
//
//   python3 scripts/hunt.py prompts  run.json && python3 scripts/hunt.py args run.json hunt     # -> args
//   Workflow({ scriptPath: "<SKILL_DIR>/workflows/hunt.js", args })
//   python3 scripts/hunt.py skeptics run.json && python3 scripts/hunt.py args run.json skeptics # -> args
//   Workflow({ scriptPath: "<SKILL_DIR>/workflows/hunt.js", args })
//
// args: { "phase": "hunt" | "skeptics", "prompt_files": ["<abs path>", ...], "read_only_agent_type": "Explore",
//         "batched": true, "agent_model": "<name>" }
// A batched skeptic prompt carries several findings and returns one verdict per finding; hunt.py
// writes the files either way, so hunt.py status / report work unchanged.
// Every agent writes its JSON where its prompt says, so hunt.py status / report work unchanged.
export const meta = {
  name: 'new-model-hunt',
  description: 'Parallel correctness hunters and clarity reviewers, then a skeptic per hunt prompted to refute each finding',
  whenToUse: 'When the user runs /new-model-hunt on a repository',
  phases: [
    { title: 'Hunt', detail: 'one read-only hunter or reviewer per prompt file' },
    { title: 'Verify', detail: 'one read-only skeptic per hunt, adjudicating that hunt\'s findings' },
  ],
}

if (!args || !Array.isArray(args.prompt_files) || !['hunt', 'skeptics'].includes(args.phase)) {
  throw new Error('args must be { phase: "hunt" | "skeptics", prompt_files: [...] } — from `hunt.py args run.json <phase>`')
}

const readOnly = args.read_only_agent_type || 'Explore'
const phase = args.phase === 'hunt' ? 'Hunt' : 'Verify'

const FINDINGS_SCHEMA = {
  type: 'object',
  required: ['findings'],
  properties: {
    findings: {
      type: 'array',
      items: {
        type: 'object',
        required: ['file', 'line', 'title', 'evidence'],
        properties: {
          file: { type: 'string' }, line: { type: 'integer' }, title: { type: 'string' }, evidence: { type: 'string' },
          failure: { type: 'string' }, fix: { type: 'string' },
          verdict: { type: 'string', enum: ['Bug', 'Delete', 'Derive', 'Fold', 'Simplify'] }, behavior: { type: 'string' }, change: { type: 'string' },
        },
      },
    },
  },
}
const VERDICT_FIELDS = {
  refuted: { type: 'boolean' },
  reason: { type: 'string' },
  severity: { type: 'string', enum: ['high', 'medium', 'low'] },
  corrected_title: { type: 'string' },
}
const VERDICT_REQUIRED = ['refuted', 'reason', 'severity', 'corrected_title']
const VERDICT_SCHEMA = { type: 'object', required: VERDICT_REQUIRED, properties: VERDICT_FIELDS }
const BATCH_VERDICT_SCHEMA = {
  type: 'object',
  required: ['verdicts'],
  properties: {
    verdicts: {
      type: 'array',
      items: {
        type: 'object',
        required: ['id', ...VERDICT_REQUIRED],
        properties: { id: { type: 'string' }, ...VERDICT_FIELDS },
      },
    },
  },
}
const schema = args.phase === 'hunt' ? FINDINGS_SCHEMA
  : args.batched ? BATCH_VERDICT_SCHEMA : VERDICT_SCHEMA

log(`${args.prompt_files.length} ${args.phase} agents`)

const results = await parallel(args.prompt_files.map(file => () =>
  agent(
    `Your complete instructions are in the file ${file}. Read it in full and carry it out exactly: it names the repository, what to read first, what to report, the JSON object to return, and the files you may write. Write them before you reply.`,
    {
      label: `${args.phase}:${file.split('/').pop().replace(/\.md$/, '')}`,
      phase, schema, agentType: readOnly,
      ...(args.agent_model ? { model: args.agent_model } : {}),
    },
  ).then(r => ({ file, ok: !!r })).catch(e => ({ file, ok: false, error: String(e) }))
))

const failed = results.filter(r => !r.ok)
log(`${results.length - failed.length} returned, ${failed.length} failed; next: hunt.py status <run.json>`)
return { returned: results.length - failed.length, failed: failed.map(f => f.file) }
