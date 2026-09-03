// Self-test for hunt.js. Stubs the Workflow globals (args, log, agent, parallel) and asserts
// the fan-out decisions: schema per phase, agent-type routing, one agent per prompt file, and
// that no option outside {label, phase, schema, agentType} reaches agent().
//
//     node workflows/selftest.mjs workflows/hunt.js
//
// This exercises the script's logic, not the live Workflow runtime.
import { readFileSync } from 'node:fs'

const target = process.argv[2] || new URL('./hunt.js', import.meta.url).pathname
const RAW = readFileSync(target, 'utf8')
// `export` is illegal inside new Function; the Workflow runtime reads meta separately anyway.
const SRC = RAW.replace(/^export\s+const\s+/m, 'const ')
if (/^export\s/m.test(SRC)) { console.error('altri export non gestiti'); process.exit(2) }
let pass = 0, fail = 0
const ok = (label, cond, detail = '') => {
  if (cond) { pass++; console.log(`  [OK ] ${label}`) }
  else { fail++; console.log(`  [NO ] ${label}${detail ? '  — ' + detail : ''}`) }
}

async function run(args) {
  const calls = [], logs = []
  const agent = (prompt, opts) => { calls.push({ prompt, opts }); return Promise.resolve({ ok: true }) }
  const parallel = (fns) => Promise.all(fns.map(f => f()))
  const log = (m) => logs.push(String(m))
  const body = `return (async () => {\n${SRC}\n})()`
  const fn = new Function('args', 'log', 'agent', 'parallel', body)
  const result = await fn(args, log, agent, parallel)
  return { calls, logs, result }
}

const files = ['/run/skeptics/correctness-cli.md', '/run/skeptics/correctness-daemon.md']

console.log('=== validazione args ===')
for (const [label, bad] of [
  ['args mancanti', undefined],
  ['prompt_files non array', { phase: 'hunt', prompt_files: 'x' }],
  ['phase sconosciuta', { phase: 'nope', prompt_files: [] }],
]) {
  let threw = false
  try { await run(bad) } catch { threw = true }
  ok(`rifiuta: ${label}`, threw)
}

console.log('=== schema per fase ===')
{
  const { calls } = await run({ phase: 'hunt', prompt_files: files })
  const s = calls[0].opts.schema
  ok('hunt usa FINDINGS_SCHEMA', s.required?.includes('findings'), JSON.stringify(s.required))
}
{
  const { calls } = await run({ phase: 'skeptics', prompt_files: files, batched: true })
  const s = calls[0].opts.schema
  ok('skeptics batched usa lo schema {verdicts:[...]}', s.required?.includes('verdicts'), JSON.stringify(s.required))
  const item = s.properties.verdicts.items
  ok('ogni verdetto richiede id + i 4 campi',
    ['id','refuted','reason','severity','corrected_title'].every(k => item.required.includes(k)),
    JSON.stringify(item.required))
  ok('severity e un enum chiuso',
    JSON.stringify(item.properties.severity.enum) === '["high","medium","low"]')
}
{
  const { calls } = await run({ phase: 'skeptics', prompt_files: files, batched: false })
  const s = calls[0].opts.schema
  ok('skeptics --solo torna allo schema a verdetto singolo',
    s.required?.includes('refuted') && !s.required?.includes('verdicts'), JSON.stringify(s.required))
}

console.log('=== instradamento agentType (il meccanismo che sostituisce model) ===')
{
  const { calls, logs } = await run({ phase: 'skeptics', prompt_files: files, batched: true,
    read_only_agent_type: 'Explore', skeptic_agent_type: 'cheap-verifier' })
  ok('gli skeptic vanno su skeptic_agent_type', calls.every(c => c.opts.agentType === 'cheap-verifier'),
    calls[0].opts.agentType)
  ok('il log nomina l agentType usato', logs.some(l => l.includes('cheap-verifier')), logs.join(' | '))
}
{
  const { calls } = await run({ phase: 'hunt', prompt_files: files,
    read_only_agent_type: 'Explore', skeptic_agent_type: 'cheap-verifier' })
  ok('gli hunter NON vengono deviati sull agente skeptic', calls.every(c => c.opts.agentType === 'Explore'),
    calls[0].opts.agentType)
}
{
  const { calls } = await run({ phase: 'skeptics', prompt_files: files, batched: true })
  ok('default a Explore senza agent type', calls.every(c => c.opts.agentType === 'Explore'), calls[0].opts.agentType)
}
{
  const { calls } = await run({ phase: 'skeptics', prompt_files: files, batched: true, agent_model: 'sonnet' })
  const keys = Object.keys(calls[0].opts).sort()
  ok('nessuna opzione fuori da {label,phase,schema,agentType}',
    JSON.stringify(keys) === '["agentType","label","phase","schema"]', JSON.stringify(keys))
}

console.log('=== fan-out e report ===')
{
  const { calls, result, logs } = await run({ phase: 'hunt', prompt_files: files })
  ok('un agente per prompt file', calls.length === files.length, String(calls.length))
  ok('ogni prompt nomina il proprio file', files.every((f, i) => calls[i].prompt.includes(f)))
  ok('label derivata dal basename', calls[0].opts.label === 'hunt:correctness-cli', calls[0].opts.label)
  ok('phase leggibile', calls[0].opts.phase === 'Hunt', calls[0].opts.phase)
  ok('ritorna il conteggio', result?.returned === 2 && result?.failed?.length === 0, JSON.stringify(result))
  ok('il log rimanda a hunt.py status', logs.some(l => l.includes('status')))
}

console.log(`\n${pass} pass, ${fail} fail`)
process.exit(fail ? 1 : 0)
