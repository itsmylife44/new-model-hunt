---
name: new-model-hunt
description: >-
  Whole-repository adversarial review and patch run for trying out a new model:
  parallel correctness hunters and code-clarity reviewers per subsystem plus
  cross-cutting lenses, a skeptic per hunt prompted to refute each finding, a
  consolidated report saved to the Desktop, then per-subsystem patch agents,
  build/test, one commit per subsystem, a UI-copy pass, and (on request) the
  release. Use when the user says /new-model-hunt, "run the hunt with the new
  model", "hunt bugs in the whole repo", "adversarial review", or wants to
  benchmark a new model on this codebase. Every judgement is anchored,
  refuted-by-default, and forbids over-guarding and over-design.
disable-model-invocation: true
---

# New-model hunt

You are the orchestrator. You carve the repo, launch the agents, join their
output, report, and only then patch. You do not review or patch code yourself
in the parent session (the exceptions are listed under Patch).

`SKILL_DIR` is the directory containing this file.

| File | Purpose |
| --- | --- |
| `SKILL_DIR/scripts/hunt.py` | `prompts` · `skeptics` · `plan` · `status` · `report` · `args` — all prompt wording lives here |
| `SKILL_DIR/workflows/hunt.js` | Claude Code `Workflow` fan-out over the prompt files — optional |
| `SKILL_DIR/scripts/selftest.py` · `workflows/selftest.mjs` | Check the run tooling without spending an agent |
| `SKILL_DIR/references/roles.md` | What each role is and the bar it is held to |
| `SKILL_DIR/references/lessons.md` | What went wrong on previous runs and the rule each left behind |

Read `roles.md` and `lessons.md` once before phase 1. The prompts in `hunt.py`
already encode them; read them so you can brief the user and judge output.

## Arguments

Parse `$ARGUMENTS`:

- `--model <name>` — recorded in the run dir and the report header (default: ask the host, else `unknown`)
- `--only correctness|clarity` — skip the other track (default: both)
- `--no-patch` — stop after the report
- `--no-copy` — skip the UI-copy phase
- `--release <x.y.z>` — after commits, cut the release with the repo's own release target
- `--skeptic-model <name>` — model for phase 2 (default: the host's cheaper tier)
- `--batch <n>` — findings per skeptic prompt (default 8; `--solo` is one agent per finding)
- `--max-agents <n>` — agents per wave (default 8)
- Every other token is a path or subsystem key to restrict the run to

Defaults: both tracks, patch after the user picks, no release.

## Budget

Every agent is a fresh context that re-reads the notes and its own files, so **agent count is what the run costs**.

`hunt.py plan` prints the count for each phase, and `hunt.py args … --wave <n>` hands you at most `n` still-pending prompts and says how many remain after them. Launch a **wave**, wait for it, ask for the next. State lives in `$RUN`, so a wave that dies against a rate or session limit costs one wave: `hunt.py status` says what is missing.

The hunters are the model under test and run on `--model`. The skeptics are the verification harness and run on `--skeptic-model`; a verifier independent of the model under test is the point of the phase, not a compromise. Record both under `models` in `run.json`. Pass the model on each agent launch where the host's launcher takes one; under the `Workflow` tool the model comes from the agent definition instead, so pass `skeptic_agent_type`.

## Phase 0 — Preflight and carve

1. `git status --porcelain` must be empty. If not, stop: this run edits many files and commits by pathspec; a dirty tree cannot be told apart from the run's work.
2. Read the repository's agent notes (`CLAUDE.md` / `AGENTS.md` / `ARCHITECTURE.md`). They are the contract every finding is judged against; a concept the notes justify is *Keep*, and a note the code no longer matches is itself a finding.
3. Carve the tree into **subsystems** of at most ~3 000 lines each, by ownership (a program, a layer, a feature folder, the build/test scripts). Name each with a short key and a file list (globs are fine). Every source file must belong to exactly one subsystem.
4. Add the three **lenses** — `wire-contract`, `concurrency`, `lifecycle` — with the files each crosses and a focus paragraph naming the concrete shapes to look for in *this* repo (see `roles.md` for the templates). Add a fourth lens only if the repo has another cross-cutting seam (a persistence format, a plugin ABI).
5. Write the run config:

```bash
RUN=/tmp/<repo>-hunt-<model>            # never inside the repo
mkdir -p "$RUN"
cat > "$RUN/run.json" <<EOF
{ "root": "<abs repo path>", "notes": ["<abs CLAUDE.md>", ...], "model": "<model>",
  "run_dir": "$RUN",
  "models": { "hunt": "<model>", "skeptic": "<skeptic-model>", "patch": "<model>" },
  "subsystems": [ { "key": "cli", "files": "cmd/** src/cli/**" }, ... ],
  "lenses": [ { "key": "wire-contract", "files": "...", "focus": "..." }, ... ] }
EOF
python3 "$SKILL_DIR/scripts/hunt.py" prompts "$RUN/run.json"
```

6. Print the budget and hand it to the user before spending it:

```bash
python3 "$SKILL_DIR/scripts/hunt.py" plan "$RUN/run.json"
```

Tell the user in two lines: N subsystems, M lenses, which tracks, where the run dir is — then `plan`'s agent counts, verbatim. The user decides whether that number is worth it; a count you paraphrased instead of ran is a count you guessed.

## Phase 1 — Hunt and review (parallel, read-only)

One agent per prompt file under `$RUN/prompts/`. Correctness hunters (`correctness-<key>.md`) and clarity reviewers (`clarity-<key>.md`) run at the same time; they are independent. Each prompt already tells the agent to write its JSON to `$RUN/findings/<track>-<key>.json` and to touch nothing in the repo.

- Launch them in waves, in the background, read-only agent type when the host has one. `python3 hunt.py args "$RUN/run.json" hunt --wave <--max-agents>` gives you one wave's prompt files and the count still pending; when the wave lands, ask for the next. Report the pending count to the user between waves.
- Do **not** poll. Run `python3 hunt.py status "$RUN/run.json"` when a completion notice arrives, or when nothing has arrived for 20 minutes; it lists expected outputs that are still missing.
- An agent that produced no file after ~60 minutes is stalled. Relaunch that one prompt (same file). Never wait on a stalled agent; never relaunch one that has written its file.
- If the host has the Claude Code `Workflow` tool, `hunt.js` fans the agents out for you: `python3 hunt.py args "$RUN/run.json" hunt` prints the `args` to pass (only prompts still without a findings file). Add `read_only_agent_type`, and for phase 2 `skeptic_agent_type` — `agent()` selects a model by agent definition, not by a model name, and `args` prints the name you need to map under `agent_type_hint`. The agents write the same files, so nothing else in this skill changes; run it again with `args … skeptics` in phase 2.

## Phase 2 — Skeptics (parallel, read-only, refute by default)

```bash
python3 "$SKILL_DIR/scripts/hunt.py" skeptics "$RUN/run.json"        # --batch <n> · --solo
```

Writes one prompt per hunt under `$RUN/skeptics/`, each carrying up to `--batch` of that hunt's findings, and skips findings that already have a verdict. Grouping by hunt is what makes this phase affordable: one skeptic reads the notes and that subsystem's files once and then judges each finding on its own, where one agent per finding re-reads the same file once per finding. `--solo` restores one agent per finding when you want the strictest independence and can pay for it.

Two things the command settles before any agent runs, and prints:

- A finding whose `file:line` anchor does not exist in the repo is refuted on the spot — a hallucinated anchor is the cheapest refutation there is, and it costs no agent.
- A finding that repeats another's defect (same file, anchors within 3 lines, titles that agree) is aliased to it, and the report folds it under the original. This is the duplicate scan the orchestrator used to do by eye.

Each skeptic writes one `verdicts/<id>.json` per finding, so `status` and `report` read the same layout as ever.

Then run `hunt.py plan "$RUN/run.json"` again and give the user its skeptic counts before launching, the same way phase 0 did. Launch in waves via `hunt.py args … skeptics --wave <n>`, as in phase 1.

The skeptic's bar (in the prompt): the finding stands only when the failure can be narrated end to end from the code, is not something the notes rule out, and its fix does not add a speculative guard or a new concept. A misplaced or overstated finding that survives gets a `corrected_title`; the corrected title is what the report shows and what the patcher follows.

## Phase 3 — Report, save, ask

```bash
python3 "$SKILL_DIR/scripts/hunt.py" report "$RUN/run.json"
mkdir -p ~/Desktop/<repo>-review-<model> && cp "$RUN/REPORT.md" "$RUN/PATCHLIST.md" ~/Desktop/<repo>-review-<model>/
```

`REPORT.md` has the model, the counts (findings / confirmed / refuted / unverified per track — this is the model's scorecard), then confirmed findings by severity with evidence, failure, fix, and the skeptic's reason; refuted ones with the reason they fell. `PATCHLIST.md` is the confirmed set grouped by file, ready to paste into patch prompts.

**Stop here and ask** — this is the one decision that is the user's: which set to patch (default offer: all confirmed correctness, clarity in a second pass) and whether one commit per subsystem is wanted. `--no-patch` ends the run here.

## Phase 4 — Patch (parallel, disjoint file groups)

1. Group the chosen findings into **disjoint file sets** that follow the subsystem carve (one commit per group later). A file two groups both need goes to exactly one group; if the other group needs a *narrow* edit in it, name the function and the lines in that group's header and say the rest of the file belongs to someone else.
2. For each group write `$RUN/task-<group>.md` = a header (files it may edit, decisions you have already made where a skeptic corrected the hunter's fix, which tests to extend) + `$RUN/patch-common.md` (written by `report`) + that group's `PATCHLIST.md` sections. Where a skeptic said "no test covers this", the header tells the group to add the test in the repo's own harness.
3. Launch one read-write agent per group, in the background, all at once. The common rules already say: surgical edits only, never `Write` a whole file, no git state changes, no `xcodebuild`/`make` into the repo's build dir, compile into `/tmp` the way the repo's harness target does, no narrating comments, no over-guarding, report anything needed outside the group.
4. Small groups with no build dependency (shell scripts, Makefile) you may patch yourself while the agents run; syntax-check them (`bash -n`).
5. When a group reports a change needed *outside* its files, wait for the owning group to finish, then make that edit yourself (or resume the owning agent). Do not touch a file an agent is still working in.

## Phase 5 — Verify

- Repo-level checks first (`make check` or the repo's equivalent), then the fast tests **three times in a row** — a timing test in the first run's harness failed one time in four, and a single green run hides that.
- Build every product the repo ships. Builds that share a cache (DerivedData, a Gradle daemon, `target/`) run **sequentially** in one shell; tests that build into `/tmp` may run beside them. Set `block_until_ms` above the build's real duration or background it and read the log — a foreground wait that gets interrupted kills the shell and the remaining steps with it.
- Fix fallout yourself. Note any target that installs something on the machine as a side effect (a LaunchAgent, a systemd unit, a login item) and undo it before finishing.

## Phase 6 — Commit, one per group

Match the repo's commit-message style (read `git log -10` first — some repos title commits as a sentence about behaviour, not `area: verb`). Stage by pathspec. When one file carries two groups' edits, stage the other group's hunk alone with `git diff <file> > d && <filter the hunk> && git apply --cached d` before its commit; never `git add -A`.

If the run changed a behaviour the agent notes describe (a protocol field, a flow-control rule, a request shape), update the notes in a final commit; a note that lies is the next run's false refutation.

## Phase 7 — UI copy (unless `--no-copy`)

Patches add and reword user-facing strings. Read `ui-copy-polish/SKILL.md` from the first of `~/.grok/skills/`, `~/.claude/skills/`, `~/.cursor/skills/` that has it, and run it on the repo with `--no-push`. Skip the phase if the skill is not installed; say so.

## Phase 8 — Release (only with `--release`)

Push, then run the repo's release target (`make release VERSION=x.y.z` or the equivalent). Its preflight usually demands `main == origin/main`; the run's commits must be pushed first. Background the wait for CI and any package that has to rebuild, and keep working; report the served version when it lands.

## Hard rules

- **Refuted by default.** A finding without a concrete input, interleaving, or unused symbol is not a finding. Zero findings for a clean area is a correct result; agents are told not to pad.
- **No over-guarding.** A missing check is a defect only when a valid input reaches the bad state. Fixes never add speculative validation, retries, or new error cases.
- **No over-design.** Structural findings must *delete* concepts (a layer, a flag, a duplicate path). A proposal that adds a protocol, a manager, a wrapper, or a mode is refuted even when it reads cleaner.
- **The notes are the contract.** Anything the agent notes justify is Keep unless the reviewer shows the note no longer matches the code.
- **State lives on disk, in `$RUN`.** Every agent writes its own JSON; a lost notification, a session limit, or a stalled agent costs one relaunch, not the run. On resume, `hunt.py status` says what is missing — never redo what is there.
- **Agents never change git state, never build into the repo, never edit outside their file list.**
- The parent session never rewrites code from feedback it has not read; it reads the diff before every commit.
