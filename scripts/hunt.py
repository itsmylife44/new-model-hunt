#!/usr/bin/env python3
"""new-model-hunt run tooling. Every prompt's wording lives here.

    hunt.py prompts  run.json   write prompts/{correctness,clarity}-<key>.md
    hunt.py skeptics run.json   write skeptics/<track>-<key>-<n>.md for findings without a verdict
    hunt.py status   run.json   list expected outputs that are missing or unparsable
    hunt.py report   run.json   write REPORT.md, PATCHLIST.md, patch-common.md
    hunt.py args     run.json hunt|skeptics   print the args JSON for workflows/hunt.js (prompts still pending)

run.json:
  { "root": "<abs repo>", "notes": ["<abs path>", ...], "model": "<name>", "run_dir": "<abs dir>",
    "tracks": ["correctness", "clarity"],            # optional, default both
    "subsystems": [ { "key": "...", "files": "..." } ],
    "lenses":     [ { "key": "...", "files": "...", "focus": "..." } ] }

Layout under run_dir: prompts/ findings/ skeptics/ verdicts/ REPORT.md PATCHLIST.md patch-common.md
A verdict file may be {"alias": "<track>-<key>-<n>"} to fold a duplicate under the original.
"""
import glob
import json
import os
import re
import sys

RANK = {'high': 0, 'medium': 1, 'low': 2, None: 3}


def load_json(path):
    text = open(path).read().strip()
    text = re.sub(r'^\s*```(?:json)?\s*|\s*```\s*$', '', text)
    return json.loads(text, strict=False)


def load_run(path):
    run = json.load(open(path))
    run.setdefault('tracks', ['correctness', 'clarity'])
    run.setdefault('lenses', [])
    for sub in ('prompts', 'findings', 'skeptics', 'verdicts'):
        os.makedirs(os.path.join(run['run_dir'], sub), exist_ok=True)
    return run


def notes_sentence(run):
    return ' and '.join(run['notes']) if run['notes'] else 'the repository README'


# ---------------------------------------------------------------- prompts ----

CORRECTNESS_SCOPE_SUBSYSTEM = (
    'Your subsystem is "{key}": {files}. Read every file in it completely. '
    'Read neighbouring files when you need them to trace a call to its end.')
CORRECTNESS_SCOPE_LENS = (
    'Your lens is "{key}". Focus: {focus}\n'
    'Files to read in full: {files}. Read whatever else you need to trace a path end to end.')

CORRECTNESS_PROMPT = """You are hunting CORRECTNESS DEFECTS in the repository at {root}. Not style, not clarity — bugs.

First read {notes} in full. They document the system's invariants and the gotchas already fixed. A defect is anything the code does that contradicts one of those invariants, or any ordinary bug: wrong result, off-by-one, integer overflow or truncation, wrong sign or unit, a state written but never read back, a comparison against the wrong value, an error swallowed where the caller then acts on stale data, an inverted condition, a lost update, a race, a leak, a double free, an unbounded growth, a string or path handled in a way that breaks on real inputs (unicode, spaces, a trimmed fragment, a very long line), a shell script whose quoting or exit-status handling fails on a real path, a Makefile rule whose prerequisites lie.

{scope}

Rules:
- Every finding must have a concrete failure: an input, a sequence of calls, or an interleaving that leads to an observable wrong outcome. "This could go wrong if..." without a way to make it happen is not a finding.
- No over-guarding. Do not report a missing check unless you name the valid input that reaches the bad state, and do not propose fixes that add speculative validation. The fix is the edit that makes the code correct, usually small.
- Do not report anything the notes explain as intentional, unless you can show the note's reasoning no longer holds in the code.
- Do not report hypothetical hardening (a malicious peer, a lying kernel). The boundary of interest is untrusted bytes from the outside world and the wire between the repository's own programs.
- Rank by severity. Zero findings is an acceptable result for a clean area; do not pad. Typically 2-8 real findings per hunt.
- Anchor every finding at a 1-indexed line in a repo-relative file, and quote the decisive snippet.
- Do NOT modify any file in the repository. This is a read-only review.

Return a single JSON object: {{"findings": [ {{"file": "<repo-relative path>", "line": <1-indexed int>, "title": "<one line, <= 90 chars, the defect stated as a fact>", "evidence": "<the code path, quoting the decisive lines with file:line for each step>", "failure": "<concrete inputs or interleaving -> wrong observable outcome>", "fix": "<the smallest edit that removes the defect, 1-3 sentences; must not add a speculative guard>"}} ] }}. No prose outside the JSON.

Before replying, write the exact same JSON object to {out} (create it; it is outside the repository and is the only file you may write).
"""

CLARITY_PROMPT = """You are reviewing one subsystem of the repository at {root} for CODE CLARITY and CORRECTNESS.

First read, in full:
1. {notes} — the repository's agent notes. Much of what looks odd is a deliberate answer to a documented gotcha. A concept the notes justify is Keep, not a finding.
2. {clarity_skill} — the review method: count concepts, not lines; store state only when it cannot be derived; add an error type only when a caller branches on it; add a branch only when a valid input reaches it and the response differs; collapse failures by recovery behaviour; one owner per behaviour; verdict table Delete / Derive / Fold / Keep / Prove.

Then read EVERY file in your subsystem completely. Subsystem "{key}": {files}
Read neighbouring files only when you need them to judge whether a concept is used or derivable — do not review them.

For each type and function, also ask the strict maintainability question: is there a move that keeps behaviour and makes whole branches, flags, modes, or layers disappear? Report it ONLY when the move removes concepts. A remedy that introduces a protocol, an actor, a manager, a policy object, a state machine, a wrapper, a new mode, or a new file to hold the same logic is not a finding here.

What to report (each as one finding):
- Bug: a concrete correctness defect — wrong result, race, leak, off-by-one, a state that can never be updated, a code path that contradicts what the notes guarantee. Must have concrete inputs -> wrong outcome.
- Delete: a stored property, enum case, flag, error case, branch, wrapper, protocol, or helper that no supported behaviour depends on. Cite that nothing reads or distinguishes it (grep the repo to confirm).
- Derive: a stored or duplicated value that an existing authoritative fact already determines.
- Fold: two paths, types, or error cases that share the same recovery behaviour or the same mechanics and should be one.
- Simplify: control flow that hides the normal path (nesting where an early return reads flat, a pass-through method, a callback promoted to state), a comment that narrates code rather than rationale, a name that lies about what it holds.

What NOT to report — no over-guarding, no over-design:
- Do not propose adding defensive checks, validation, nil-guards, retries, or error cases. A missing guard is a finding only if you can name the valid input that reaches the bad state.
- DO report existing guards that protect a scenario that cannot occur or that has no distinct response.
- Do not report style (line wrapping, argument labels, MARK comments), naming taste without a lying name, or "could be a protocol / could be an actor" speculation.
- Do not report anything the notes justify; if you think the note is wrong, say why under evidence.
- Do not pad. Zero findings for a clean file is a correct result. Aim for what a senior maintainer would act on: typically 3-10 per subsystem, ranked most valuable first.

Precision: every finding names the file and the 1-indexed line where the change starts, quotes the relevant snippet in evidence, and states the observable behaviour. A finding you cannot anchor to a line is not a finding. Do NOT modify any file in the repository.

Return a single JSON object: {{"findings": [ {{"file": "<repo-relative path>", "line": <1-indexed int>, "verdict": "Bug|Delete|Derive|Fold|Simplify", "title": "<one line, <= 90 chars>", "evidence": "<what the code does, citing exact lines/symbols; quote the key snippet>", "behavior": "<for Bug: concrete inputs -> wrong result. Otherwise: the observable behaviour that is unchanged, and the concept count removed>", "change": "<the concrete edit in 1-3 sentences>"}} ] }}. No prose outside the JSON.

Before replying, write the exact same JSON object to {out} (create it; it is outside the repository and is the only file you may write).
"""

SKEPTIC_CORRECTNESS = """You are the skeptic. A reviewer reported this correctness defect in the repository at {root}. Your job is to REFUTE it. Default to refuted=true when the failure does not follow from the code.

Finding (from hunt "{key}"):
  file: {file}
  line: {line}
  title: {title}
  evidence: {evidence}
  failure: {failure}
  proposed fix: {fix}

Procedure:
1. Read {notes}. If the notes state that this exact scenario is intentional or impossible (a documented gotcha, a platform constraint, an authenticated boundary), the finding is refuted unless the reviewer shows the note's reasoning no longer matches the code.
2. Open {file} around line {line}, read the whole enclosing function and type, and check that the quoted snippet exists and behaves as claimed.
3. Trace the failure path yourself, reading every file it crosses. Confirm each step. One step that does not hold refutes it.
4. Check the repository's tests: if a test already exercises this path and passes, explain why the finding is still real or refute it. If no test covers it, say so in reason — the patcher will add one.
5. Check whether the proposed fix adds a speculative guard or a new concept. If the defect is real but the fix is over-guarding, keep refuted=false and say in reason what the minimal fix is.
6. A duplicate of a scenario the notes already document as fixed, or a purely theoretical concern (a malicious peer, a lying kernel), is refuted.

Return refuted=false only when you can narrate the failure end to end from the code. If the finding stands but is misstated or mis-anchored, keep refuted=false and give a corrected_title.

Do NOT modify any file in the repository. Return a single JSON object with exactly these keys: refuted (boolean), reason (string: the decisive fact with file:line), severity ("high" = data loss, hang, crash, or a wrong result a user will hit; "medium" = wrong result on a plausible but uncommon path; "low" = latent, needs an unusual input), corrected_title (string, empty if the title stands). Before replying, write that same JSON object to {out} (the only file you may write). Your reply must be only the JSON.
"""

SKEPTIC_CLARITY = """You are the skeptic. A code-clarity reviewer reported this finding in the repository at {root}. Your job is to REFUTE it. Default to refuted=true when the evidence does not hold up.

Finding (subsystem "{key}"):
  file: {file}
  line: {line}
  verdict: {verdict}
  title: {title}
  evidence: {evidence}
  behavior: {behavior}
  proposed change: {change}

Procedure:
1. Read {notes}. If the notes document a reason for exactly this concept (a gotcha that bit the project, a platform limit, a resource constraint), the finding is refuted unless the reviewer's evidence shows the note no longer applies.
2. Open {file} around line {line} and read the whole surrounding type/function. Check that the quoted snippet exists and does what the reviewer says.
3. grep the repository for every symbol the finding says is unused, duplicated, or unreachable. A single real reader or a real caller that behaves differently refutes a Delete/Derive/Fold.
4. For a Bug, trace the concrete inputs the reviewer gave. If the bad outcome does not follow, refuted. If it follows only for an input the notes rule out, refuted.
5. For a clarity verdict: would deleting/deriving/folding this change any observable behaviour for a supported scenario? Would the proposed change ADD a guard, a branch, a type, a protocol, a wrapper, a mode, or a file instead of removing one? If so, refuted — the user has asked for no over-guarding and no over-design.
6. Style-only or taste findings (formatting, naming without a lying name, "could be an actor") are refuted.

Return refuted=false only when the finding is accurate, anchored, and actionable. If it stands but the reviewer overstated it or anchored it to the wrong place, keep refuted=false and give a corrected_title.

Do NOT modify any file in the repository. Return a single JSON object with exactly these keys: refuted (boolean), reason (string: the decisive fact with file:line), severity ("high" = user-visible bug or a real correctness risk; "medium" = a concept a maintainer must understand that earns nothing; "low" = local tidy-up), corrected_title (string, empty if the title stands). Before replying, write that same JSON object to {out} (the only file you may write). Your reply must be only the JSON.
"""

PATCH_COMMON = """# Common rules for every patch agent

Repository: {root} (git). Read {notes} first — the hard rules there apply.

Other agents are editing OTHER files in the same working tree at the same time. Therefore:

- Edit ONLY the files listed in your group (plus new test files where your group says so). If a fix seems to need a change outside your list, do not make it — describe it in your final report instead.
- Use surgical string-replacement edits. NEVER rewrite a whole file (another agent may have edited it in the meantime).
- Do NOT run any git command that changes state (no commit, stash, checkout, reset, add). `git diff` / `git status` are fine.
- Do NOT run the repository's build system into its own build directory (no xcodebuild, no `make` targets that build or install) — the orchestrator builds afterwards. You may compile into a /tmp directory exactly the way the repository's test harness target does, when your group says you may.
- Do not add comments that narrate the code. A comment is only for a non-obvious constraint or trade-off; match the repository's comment style.
- Do not over-guard: fix the actual defect with the smallest honest change. Where the skeptic's note corrects the hunter's proposed fix, follow the skeptic.
- Keep temporary scripts under /tmp, never in the repo.
- Do not add user-facing strings or localization entries unless a fix genuinely needs one.

Each finding below has: EVIDENCE (what the code does, with line numbers that may have drifted), FAILURE (the observable bug), PROPOSED FIX (the hunter's), SKEPTIC (the verifier's confirmation, sometimes with a corrected mechanism or a better fix). Read the real code before editing; do not trust line numbers.

Final response: a concise list, one line per finding — `file:line — what you changed` — followed by anything you could not do and why, and any change needed in files outside your group.
"""


def write_prompts(run):
    root, notes, run_dir = run['root'], notes_sentence(run), run['run_dir']
    clarity_skill = 'the code-clarity method summarised here'
    for home in ('~/.grok/skills', '~/.claude/skills', '~/.cursor/skills', '~/.agents/skills'):
        candidate = os.path.expanduser(f'{home}/code-clarity/SKILL.md')
        if os.path.exists(candidate):
            clarity_skill = candidate
            break
    written = []
    if 'correctness' in run['tracks']:
        for s in run['subsystems']:
            scope = CORRECTNESS_SCOPE_SUBSYSTEM.format(**s)
            out = f"{run_dir}/findings/correctness-{s['key']}.json"
            p = f"{run_dir}/prompts/correctness-{s['key']}.md"
            open(p, 'w').write(CORRECTNESS_PROMPT.format(root=root, notes=notes, scope=scope, out=out))
            written.append(p)
        for l in run['lenses']:
            scope = CORRECTNESS_SCOPE_LENS.format(**l)
            out = f"{run_dir}/findings/correctness-{l['key']}.json"
            p = f"{run_dir}/prompts/correctness-{l['key']}.md"
            open(p, 'w').write(CORRECTNESS_PROMPT.format(root=root, notes=notes, scope=scope, out=out))
            written.append(p)
    if 'clarity' in run['tracks']:
        for s in run['subsystems']:
            out = f"{run_dir}/findings/clarity-{s['key']}.json"
            p = f"{run_dir}/prompts/clarity-{s['key']}.md"
            open(p, 'w').write(CLARITY_PROMPT.format(
                root=root, notes=notes, clarity_skill=clarity_skill, out=out, **s))
            written.append(p)
    for p in written:
        print(p)
    print(f'{len(written)} prompts; launch one agent per file, all at once, read-only.')


# --------------------------------------------------------------- findings ----

def expected_findings(run):
    keys = []
    if 'correctness' in run['tracks']:
        keys += [f"correctness-{s['key']}" for s in run['subsystems']]
        keys += [f"correctness-{l['key']}" for l in run['lenses']]
    if 'clarity' in run['tracks']:
        keys += [f"clarity-{s['key']}" for s in run['subsystems']]
    return keys


def iter_findings(run):
    """Yield (id, track, key, finding) for every parsable findings file."""
    for key in expected_findings(run):
        path = f"{run['run_dir']}/findings/{key}.json"
        if not os.path.exists(path):
            continue
        try:
            data = load_json(path)
        except Exception:
            continue
        track = key.split('-', 1)[0]
        for i, f in enumerate(data.get('findings', []), 1):
            yield f'{key}-{i}', track, key[len(track) + 1:], f


def status(run):
    run_dir = run['run_dir']
    missing, bad, present = [], [], 0
    for key in expected_findings(run):
        path = f'{run_dir}/findings/{key}.json'
        if not os.path.exists(path):
            missing.append(key)
            continue
        try:
            load_json(path)
            present += 1
        except Exception as e:
            bad.append(f'{key}: {e}')
    print(f'findings: {present} present, {len(missing)} missing, {len(bad)} bad')
    for m in missing:
        print(f'  MISSING  {run_dir}/prompts/{m}.md')
    for b in bad:
        print(f'  BAD      {b}')
    total = pending = 0
    for fid, *_ in iter_findings(run):
        total += 1
        if not os.path.exists(f'{run_dir}/verdicts/{fid}.json'):
            pending += 1
    print(f'verdicts: {total - pending}/{total} present' + (f', {pending} pending' if pending else ''))


def write_skeptics(run):
    root, notes, run_dir = run['root'], notes_sentence(run), run['run_dir']
    n = 0
    for fid, track, key, f in iter_findings(run):
        if os.path.exists(f'{run_dir}/verdicts/{fid}.json'):
            continue
        out = f'{run_dir}/verdicts/{fid}.json'
        tpl = SKEPTIC_CORRECTNESS if track == 'correctness' else SKEPTIC_CLARITY
        fields = {k: f.get(k, '') for k in ('file', 'line', 'title', 'evidence', 'failure', 'fix', 'verdict', 'behavior', 'change')}
        p = f'{run_dir}/skeptics/{fid}.md'
        open(p, 'w').write(tpl.format(root=root, notes=notes, key=key, out=out, **fields))
        print(f"{p}  --  {f.get('file')}:{f.get('line')}  {f.get('title')}")
        n += 1
    print(f'{n} skeptic prompts. Scan for duplicates (same file, same defect): write {{"alias": "<id>"}} to the duplicate\'s verdict file instead of launching it.')


# ----------------------------------------------------------------- report ----

def collect(run):
    run_dir = run['run_dir']
    items = []
    for fid, track, key, f in iter_findings(run):
        f = dict(f, id=fid, track=track, key=key)
        vp = f'{run_dir}/verdicts/{fid}.json'
        if os.path.exists(vp):
            try:
                v = load_json(vp)
            except Exception:
                v = None
            if v and 'alias' in v:
                continue
            f['skeptic'] = v
        items.append(f)
    return items


def state(f):
    s = f.get('skeptic')
    if not s:
        return 'UNVERIFIED', None
    return ('REFUTED' if s.get('refuted') else 'CONFIRMED'), s.get('severity')


def section(title, items, track):
    out = [f'\n## {title}\n']
    conf = [f for f in items if state(f)[0] == 'CONFIRMED']
    conf.sort(key=lambda f: (RANK.get(state(f)[1], 3), f['file'], f['line']))
    for f in conf:
        s = f['skeptic']
        t = s.get('corrected_title') or f['title']
        verdict = f.get('verdict', 'Bug')
        out.append(f"- **[{state(f)[1]}] {verdict} — `{f['file']}:{f['line']}`** — {t}  ({f['id']})")
        out.append(f"  - evidence: {f.get('evidence', '')}")
        out.append(f"  - {'behavior' if track == 'clarity' else 'failure'}: {f.get('behavior') or f.get('failure', '')}")
        out.append(f"  - fix: {f.get('change') or f.get('fix', '')}")
        out.append(f"  - skeptic: {s.get('reason', '')}")
    ref = [f for f in items if state(f)[0] == 'REFUTED']
    unv = [f for f in items if state(f)[0] == 'UNVERIFIED']
    if ref:
        out.append('\n### Refuted')
        for f in ref:
            out.append(f"- `{f['file']}:{f['line']}` — {f['title']}\n  - why: {f['skeptic'].get('reason', '')}")
    if unv:
        out.append('\n### Unverified')
        for f in unv:
            out.append(f"- `{f['file']}:{f['line']}` — {f['title']}")
    return out, len(conf), len(ref), len(unv)


def report(run):
    run_dir = run['run_dir']
    items = collect(run)
    summary, bodies = [], []
    for track, title in (('correctness', 'Correctness (bug hunt)'), ('clarity', 'Code clarity')):
        if track not in run['tracks']:
            continue
        sub = [f for f in items if f['track'] == track]
        body, c, r, u = section(title, sub, track)
        summary.append(f'{title}: {len(sub)} findings — {c} confirmed, {r} refuted, {u} unverified.')
        bodies += body
    rep = [f"# {os.path.basename(run['root'])} review — model: {run.get('model', 'unknown')}\n"] + summary + bodies
    open(f'{run_dir}/REPORT.md', 'w').write('\n'.join(rep) + '\n')

    conf = [f for f in items if state(f)[0] == 'CONFIRMED']
    by_file = {}
    for f in conf:
        by_file.setdefault(f['file'], []).append(f)
    pl = [f"# Patch list — confirmed findings by file ({len(conf)})\n"]
    for path in sorted(by_file):
        pl.append(f'\n# {path}\n')
        for f in sorted(by_file[path], key=lambda f: f['line']):
            s = f['skeptic']
            t = s.get('corrected_title') or f['title']
            pl.append(f"## [{s.get('severity')}] {path}:{f['line']} ({f['id']}, {f.get('verdict', 'Bug')})")
            pl.append(f'**{t}**\n')
            pl.append(f"EVIDENCE: {f.get('evidence', '')}\n")
            pl.append(f"FAILURE: {f.get('behavior') or f.get('failure', '')}\n")
            pl.append(f"PROPOSED FIX: {f.get('change') or f.get('fix', '')}\n")
            pl.append(f"SKEPTIC: {s.get('reason', '')}\n")
    open(f'{run_dir}/PATCHLIST.md', 'w').write('\n'.join(pl) + '\n')
    open(f'{run_dir}/patch-common.md', 'w').write(
        PATCH_COMMON.format(root=run['root'], notes=notes_sentence(run)))
    print('\n'.join(summary))
    print(f'wrote {run_dir}/REPORT.md, PATCHLIST.md ({len(conf)} confirmed across {len(by_file)} files), patch-common.md')


def workflow_args(run, phase):
    run_dir = run['run_dir']
    if phase == 'hunt':
        files = [f'{run_dir}/prompts/{k}.md' for k in expected_findings(run)
                 if not os.path.exists(f'{run_dir}/findings/{k}.json')]
    else:
        files = [f'{run_dir}/skeptics/{fid}.md' for fid, *_ in iter_findings(run)
                 if not os.path.exists(f'{run_dir}/verdicts/{fid}.json')
                 and os.path.exists(f'{run_dir}/skeptics/{fid}.md')]
    print(json.dumps({'phase': phase, 'prompt_files': files}, indent=1))


def main():
    cmds = {'prompts': write_prompts, 'skeptics': write_skeptics, 'status': status, 'report': report}
    if len(sys.argv) == 4 and sys.argv[1] == 'args' and sys.argv[3] in ('hunt', 'skeptics'):
        workflow_args(load_run(sys.argv[2]), sys.argv[3])
        return
    if len(sys.argv) != 3 or sys.argv[1] not in cmds:
        print(__doc__)
        sys.exit(64)
    cmds[sys.argv[1]](load_run(sys.argv[2]))


if __name__ == '__main__':
    main()
