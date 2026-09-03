#!/usr/bin/env python3
"""Self-test for hunt.py. No model calls, no network, no repository needed.

    python3 scripts/selftest.py

Builds a synthetic repo and run dir under a temp directory, then checks the
parts that decide a run's cost and correctness: the anchor check, the duplicate
check, the grouping, --solo, resume of a run written by an older version, waves,
and that report still reads what the skeptics wrote.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import hunt  # noqa: E402

PASS = FAIL = 0


def ok(label, cond, detail=''):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f'  [OK ] {label}')
    else:
        FAIL += 1
        print(f'  [NO ] {label}' + (f'  -- {detail}' if detail else ''))
    return cond


def run_py(*args):
    out = subprocess.run([sys.executable, f'{HERE}/hunt.py', *args],
                         capture_output=True, text=True)
    return out.stdout + out.stderr


def build(tmp, findings_by_hunt, nlines=40):
    """A repo of one file per hunt key, and a run dir holding the given findings."""
    root = f'{tmp}/repo'
    run_dir = f'{tmp}/run'
    for d in (root, run_dir, f'{run_dir}/findings'):
        os.makedirs(d, exist_ok=True)
    for key in findings_by_hunt:
        open(f'{root}/{key}.ts', 'w').write('\n'.join(f'line {i}' for i in range(1, nlines + 1)))
    run = {'root': root, 'notes': [], 'model': 'test', 'run_dir': run_dir,
           'tracks': ['correctness'], 'lenses': [],
           'subsystems': [{'key': k, 'files': f'{k}.ts'} for k in findings_by_hunt]}
    json.dump(run, open(f'{run_dir}/run.json', 'w'))
    for key, fs in findings_by_hunt.items():
        json.dump({'findings': fs}, open(f'{run_dir}/findings/correctness-{key}.json', 'w'))
    return run_dir, root


def finding(key, line, title, **kw):
    return dict({'file': f'{key}.ts', 'line': line, 'title': title,
                 'evidence': 'e', 'failure': 'f', 'fix': 'x'}, **kw)


def verdicts(run_dir):
    return {os.path.basename(p)[:-5]: json.load(open(f'{run_dir}/verdicts/{p}'))
            for p in os.listdir(f'{run_dir}/verdicts')}


def main():
    tmp = tempfile.mkdtemp(prefix='hunt-selftest-')
    try:
        # ------------------------------------------------ the anchor check ----
        print('anchor check')
        root = f'{tmp}/anchors'
        os.makedirs(root, exist_ok=True)
        open(f'{root}/a.ts', 'w').write('\n'.join(f'line {i}' for i in range(1, 11)))
        cases = [
            ('a real line', {'file': 'a.ts', 'line': 5}, True),
            ('the last line', {'file': 'a.ts', 'line': 10}, True),
            ('end of file, n+1', {'file': 'a.ts', 'line': 11}, True),
            ('past the end', {'file': 'a.ts', 'line': 12}, False),
            ('line zero', {'file': 'a.ts', 'line': 0}, False),
            ('a file that is not there', {'file': 'ghost.ts', 'line': 1}, False),
            ('a line that is not a number', {'file': 'a.ts', 'line': 'x'}, False),
            ('no file at all', {'line': 1}, False),
        ]
        for label, f, want_ok in cases:
            got = hunt._anchor_miss(root, f)
            ok(f'{label} -> {"kept" if want_ok else "refuted"}', (got is None) == want_ok, str(got))

        # ---------------------------------------------- the duplicate check ----
        print('duplicate check')
        base = {'file': 'a.ts', 'line': 10, 'title': 'Cursor pagination drops the last page'}
        pairs = [
            ('same defect, one line apart, reworded',
             {'file': 'a.ts', 'line': 11, 'title': 'Cursor pagination drops the final page'}, True),
            ('same title, different file', {'file': 'b.ts', 'line': 10, 'title': base['title']}, False),
            ('same title, 30 lines apart', {'file': 'a.ts', 'line': 40, 'title': base['title']}, False),
            ('same anchor, unrelated defect',
             {'file': 'a.ts', 'line': 10, 'title': 'Unbounded retry loop on a 429 response'}, False),
            ('an empty title never matches', {'file': 'a.ts', 'line': 10, 'title': ''}, False),
        ]
        for label, other, want in pairs:
            ok(label, hunt._same_defect(base, other) is want)

        # -------------------------------------------------------- grouping ----
        print('grouping')
        shutil.rmtree(f'{tmp}/run', ignore_errors=True)
        run_dir, repo = build(tmp, {
            'cli': [finding('cli', i, f'Defect number {i} in the parser') for i in (5, 9, 13, 17, 21)],
            'daemon': [finding('daemon', i, f'Defect number {i} in the loop') for i in (5, 9, 13)],
        })
        out = run_py('skeptics', f'{run_dir}/run.json')
        m = json.load(open(f'{run_dir}/skeptics/batches.json'))
        ok('8 findings in 2 prompts at the default batch', len(m) == 2 and sum(len(v) for v in m.values()) == 8,
           f'{len(m)} prompts')
        ok('sizes follow the hunts', sorted((len(v) for v in m.values()), reverse=True) == [5, 3],
           str(sorted((len(v) for v in m.values()), reverse=True)))
        ok('one prompt per hunt, named for it',
           set(os.path.basename(p) for p in m) == {'correctness-cli.md', 'correctness-daemon.md'},
           str(sorted(os.path.basename(p) for p in m)))
        body = open(f'{run_dir}/skeptics/correctness-cli.md').read()
        anchored = [l for l in body.splitlines() if l.startswith('  WRITE VERDICT TO: /')]
        ok('the prompt names every verdict path it must write', len(anchored) == 5, str(len(anchored)))
        ok('each path is a distinct verdict file', len(set(anchored)) == 5)
        ok('the prompt asks for exactly that many verdicts', '5 in total' in body)
        ok('a batch splits at --batch',
           len(json.load(open(f'{run_dir}/skeptics/batches.json'))) == 2)

        shutil.rmtree(f'{run_dir}/skeptics'); shutil.rmtree(f'{run_dir}/verdicts')
        run_py('skeptics', f'{run_dir}/run.json', '--batch', '2')
        m2 = json.load(open(f'{run_dir}/skeptics/batches.json'))
        ok('--batch 2 splits 5+3 into 3+2 prompts', len(m2) == 5, f'{len(m2)} prompts')
        ok('every finding still has exactly one prompt',
           sorted(f for v in m2.values() for f in v) == sorted(
               f'correctness-{k}-{i}' for k, n in (('cli', 5), ('daemon', 3)) for i in range(1, n + 1)))

        # ------------------------------------------------------------ solo ----
        print('--solo')
        shutil.rmtree(f'{run_dir}/skeptics'); shutil.rmtree(f'{run_dir}/verdicts')
        run_py('skeptics', f'{run_dir}/run.json', '--solo')
        m3 = json.load(open(f'{run_dir}/skeptics/batches.json'))
        ok('one prompt per finding', len(m3) == 8, f'{len(m3)} prompts')
        ok('every prompt carries one finding', all(len(v) == 1 for v in m3.values()))
        solo_body = open(sorted(m3)[0]).read()
        ok('the solo prompt asks for one verdict object', 'Return a single JSON object with exactly these keys' in solo_body)

        # -------------------------------------- prefilter and dedup at work ----
        print('prefilter and dedup in one pass')
        shutil.rmtree(f'{tmp}/run', ignore_errors=True)
        run_dir, repo = build(tmp, {'cli': [
            finding('cli', 5, 'A real defect at line five'),
            finding('cli', 6, 'A real defect at line 5'),          # duplicate of the above
            finding('cli', 999, 'Anchored past the end of the file'),
            dict(finding('cli', 5, 'Names a file that is not there'), file='ghost.ts'),
            finding('cli', 20, 'A second unrelated defect'),
        ]})
        out = run_py('skeptics', f'{run_dir}/run.json')
        v = verdicts(run_dir)
        ok('the duplicate is aliased to the original',
           v.get('correctness-cli-2', {}).get('alias') == 'correctness-cli-1', json.dumps(v.get('correctness-cli-2')))
        ok('the anchor past the end is refuted, not sent to an agent',
           v.get('correctness-cli-3', {}).get('refuted') is True, json.dumps(v.get('correctness-cli-3')))
        ok('the missing file is refuted', v.get('correctness-cli-4', {}).get('refuted') is True)
        ok('a refused finding carries the four keys report reads',
           set(v['correctness-cli-3']) == {'refuted', 'reason', 'severity', 'corrected_title'})
        m = json.load(open(f'{run_dir}/skeptics/batches.json'))
        ok('only the 2 survivors reach a prompt', sum(len(x) for x in m.values()) == 2,
           str(sum(len(x) for x in m.values())))
        ok('the run says what it settled', 'auto-refuted' in out and 'auto-aliased' in out)

        # ---------------------------------- a root that is not on this disk ----
        print('a root that is not on this disk')
        shutil.rmtree(f'{run_dir}/skeptics'); shutil.rmtree(f'{run_dir}/verdicts')
        r = json.load(open(f'{run_dir}/run.json'))
        r['root'] = '/nonexistent/repository'
        json.dump(r, open(f'{run_dir}/run.json', 'w'))
        out = run_py('skeptics', f'{run_dir}/run.json')
        v = verdicts(run_dir)
        ok('no finding is refuted for an anchor nobody could check',
           not any(x.get('refuted') for x in v.values()), json.dumps(v))
        ok('and it says so', 'skipping the anchor check' in out, out.strip()[:120])
        ok('the duplicate check still runs', any('alias' in x for x in v.values()))
        r['root'] = repo
        json.dump(r, open(f'{run_dir}/run.json', 'w'))

        # ----------------------------------------------------------- waves ----
        print('waves')
        shutil.rmtree(f'{tmp}/run', ignore_errors=True)
        run_dir, repo = build(tmp, {k: [finding(k, 5, f'A defect in {k}'),
                                        finding(k, 20, f'Another defect in {k}')]
                                    for k in ('a', 'b', 'c', 'd', 'e')})
        run_py('skeptics', f'{run_dir}/run.json')
        for w, launching, left in ((2, 2, 3), (5, 5, 0), (99, 5, 0)):
            d = json.loads(run_py('args', f'{run_dir}/run.json', 'skeptics', '--wave', str(w)))
            ok(f'--wave {w} launches {launching}, leaves {left}',
               len(d['prompt_files']) == launching and d['wave']['still_pending_after'] == left,
               json.dumps(d.get('wave')))
        d = json.loads(run_py('args', f'{run_dir}/run.json', 'skeptics'))
        ok('no --wave means every pending prompt and no wave key',
           len(d['prompt_files']) == 5 and 'wave' not in d)
        ok('args says the prompts are batched', d['batched'] is True)

        # a wave shrinks as verdicts land
        m = json.load(open(f'{run_dir}/skeptics/batches.json'))
        for fid in list(m.values())[0]:
            json.dump({'refuted': True, 'reason': 'r', 'severity': 'low', 'corrected_title': ''},
                      open(f'{run_dir}/verdicts/{fid}.json', 'w'))
        d = json.loads(run_py('args', f'{run_dir}/run.json', 'skeptics'))
        ok('a finished prompt drops out of the next wave', len(d['prompt_files']) == 4,
           str(len(d['prompt_files'])))

        # ----------------------------- a run written by an older version ----
        print('resume of a run written before skeptics were grouped')
        os.remove(f'{run_dir}/skeptics/batches.json')
        for p in os.listdir(f'{run_dir}/skeptics'):
            os.remove(f'{run_dir}/skeptics/{p}')
        for p in os.listdir(f'{run_dir}/verdicts'):
            os.remove(f'{run_dir}/verdicts/{p}')
        ids = [fid for fid, *_ in hunt.iter_findings(hunt.load_run(f'{run_dir}/run.json'))]
        for fid in ids:
            open(f'{run_dir}/skeptics/{fid}.md', 'w').write('a prompt from the older layout')
        d = json.loads(run_py('args', f'{run_dir}/run.json', 'skeptics'))
        ok('its per-finding prompts are still found', len(d['prompt_files']) == len(ids),
           f'{len(d["prompt_files"])} of {len(ids)}')
        ok('and reported as not batched', d['batched'] is False)
        json.dump({'refuted': True, 'reason': 'r', 'severity': 'low', 'corrected_title': ''},
                  open(f'{run_dir}/verdicts/{ids[0]}.json', 'w'))
        d = json.loads(run_py('args', f'{run_dir}/run.json', 'skeptics'))
        ok('a verdict already there is never redone', len(d['prompt_files']) == len(ids) - 1)

        # ------------------------------------------------------------ plan ----
        print('plan')
        out = run_py('plan', f'{run_dir}/run.json')
        ok('plan prints a line per batch size', out.count('skeptics  --batch') == 4, out)
        ok('plan marks the default', '<- default' in out)
        ok('plan names the one-agent-per-finding cost', 'one agent per finding' in out)

        # ---------------------------------------------------------- report ----
        print('report reads what the skeptics wrote')
        shutil.rmtree(f'{tmp}/run', ignore_errors=True)
        run_dir, repo = build(tmp, {'cli': [finding('cli', i, f'Defect {i}') for i in (5, 12, 20)]})
        run_py('skeptics', f'{run_dir}/run.json')
        m = json.load(open(f'{run_dir}/skeptics/batches.json'))
        fids = [f for v in m.values() for f in v]
        for i, fid in enumerate(fids):
            json.dump({'refuted': i == 0, 'reason': f'decided {fid}',
                       'severity': 'high', 'corrected_title': 'a better title' if i == 1 else ''},
                      open(f'{run_dir}/verdicts/{fid}.json', 'w'))
        out = run_py('report', f'{run_dir}/run.json')
        ok('report counts them', '3 findings' in out and '2 confirmed' in out and '1 refuted' in out, out.strip()[:160])
        rep = open(f'{run_dir}/REPORT.md').read()
        ok('a corrected title is what the report shows', 'a better title' in rep)
        ok('the skeptic reason reaches the report', 'decided' in rep)
        ok('PATCHLIST.md holds the confirmed set', os.path.exists(f'{run_dir}/PATCHLIST.md'))
        ok('patch-common.md is written for the patch agents', os.path.exists(f'{run_dir}/patch-common.md'))
        out = run_py('status', f'{run_dir}/run.json')
        ok('status sees every verdict', '3/3 present' in out, out.strip()[:120])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print(f'\n{PASS} pass, {FAIL} fail')
    return 1 if FAIL else 0


if __name__ == '__main__':
    sys.exit(main())
