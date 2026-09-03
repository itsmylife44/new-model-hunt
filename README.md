# New-model hunt

A skill that runs a **whole-repository adversarial review** against a new model: parallel correctness hunters and code-clarity reviewers per subsystem, cross-cutting lenses, a skeptic per hunt prompted to refute each finding, a report on the Desktop, then (if you want) per-subsystem patches, build/test, one commit per group, a UI-copy pass, and a release.

Every judgement is anchored, refuted by default, and forbids over-guarding and over-design. Zero findings for a clean area is a correct result.

## Install

```bash
# Claude Code
git clone https://github.com/Lakr233/new-model-hunt.git ~/.claude/skills/new-model-hunt
# Grok
git clone https://github.com/Lakr233/new-model-hunt.git ~/.grok/skills/new-model-hunt
# Cursor
git clone https://github.com/Lakr233/new-model-hunt.git ~/.cursor/skills/new-model-hunt
```

Then run `/new-model-hunt` in a **clean** git checkout of the repo under review. Hosts that match on description also pick it up for "hunt bugs in the whole repo" or "adversarial review".

The optional [code-clarity](https://github.com/Lakr233/code-clarity) skill is read when installed (same `skills/` home). The optional [ui-copy-polish](https://github.com/Lakr233/ui-copy-polish) skill is run after commits unless you pass `--no-copy`.

## Usage

```
/new-model-hunt
/new-model-hunt --model <name>
/new-model-hunt --only correctness
/new-model-hunt --only clarity
/new-model-hunt --no-patch
/new-model-hunt --no-copy
/new-model-hunt --release 1.2.3
/new-model-hunt cli daemon
```

| Flag | Effect |
| --- | --- |
| _(none)_ | Both tracks, then ask which confirmed set to patch |
| `--model <name>` | Recorded in the run dir and the report header |
| `--only correctness` / `--only clarity` | Skip the other track |
| `--no-patch` | Stop after the report |
| `--no-copy` | Skip the UI-copy phase |
| `--release <x.y.z>` | After commits, cut the release with the repo's own release target |
| other tokens | Restrict the run to those paths or subsystem keys |

The working tree must be clean (`git status --porcelain` empty). Run state lives under `/tmp/<repo>-hunt-<model>`, never inside the repo. The report is copied to `~/Desktop/<repo>-review-<model>/`.

## What it does

1. **Carve** the tree into subsystems of at most ~3 000 lines, plus three cross-cutting lenses (`wire-contract`, `concurrency`, `lifecycle`).
2. **Hunt** — one read-only agent per subsystem (and per lens on the correctness track). Each writes JSON under the run dir.
3. **Skeptics** — one read-only agent per hunt, carrying that hunt's findings and prompted to refute each. Default is `refuted=true`. Findings with an anchor that does not exist, or that repeat another finding, are settled by the script before any agent runs. `--solo` puts one agent on each finding.
4. **Report** — confirmed findings by severity with evidence, failure, fix, and the skeptic's reason; refuted ones with why they fell. This is the model's scorecard.
5. **Ask** — which set to patch. Default offer: all confirmed correctness, clarity in a second pass.
6. **Patch** — one agent per disjoint file group. Surgical edits only; they never change git state or build into the repo.
7. **Verify** — repo checks, then the fast tests three times in a row. Undo any install-as-side-effect.
8. **Commit** — one commit per group, staged by pathspec, in the repo's own commit style.
9. **UI copy** (unless `--no-copy`) and **release** (only with `--release`).

`scripts/hunt.py` owns every prompt. `python3 scripts/hunt.py status run.json` is the source of truth on resume: never redo a findings or verdict file that is already there.

## Structure

```
new-model-hunt/
├── SKILL.md                    # Orchestrator
├── references/
│   ├── roles.md                # Hunter, reviewer, skeptic, patcher, orchestrator
│   └── lessons.md              # What previous runs taught, and the rule each left
├── scripts/
│   ├── hunt.py                 # prompts · skeptics · plan · status · report · args
│   └── selftest.py             # anchors, duplicates, grouping, waves, resume, report
└── workflows/
    ├── hunt.js                 # Optional Claude Code Workflow fan-out
    └── selftest.mjs            # hunt.js fan-out and schema routing
```

## Tests

Neither test calls a model, touches the network, or needs a repository:

```bash
python3 scripts/selftest.py        # 52 checks on the run tooling
node workflows/selftest.mjs        # 19 checks on the Workflow fan-out
```

On Claude Code, `python3 scripts/hunt.py args run.json hunt|skeptics` prints the `args` for `workflows/hunt.js`; add `--wave <n>` to take one wave at a time and see how many prompts remain. Anywhere else the orchestrator launches one subagent per prompt file.

`run.json` accepts a `models` map (`hunt` / `skeptic` / `patch`) so the hunters run on the model under test while the skeptics verify on a cheaper one. Under the `Workflow` tool a model is chosen by agent definition rather than by name, so pass `skeptic_agent_type`.

## License

MIT — see [LICENSE](LICENSE).
