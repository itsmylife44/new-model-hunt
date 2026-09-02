# Lessons from previous runs

Each entry is something that cost time on a real run and the rule it left in
the skill. Add to this file when a run teaches something new; do not soften
the existing rules.

## Agents and the harness

- **A session limit or a lost notification must not lose the run.** The first
  run stopped mid-way when the host's session limit hit, and the resumed
  session had to reconstruct state from a transcript with truncated JSON.
  Rule: every agent writes its own JSON to the run dir; `hunt.py status` is
  the source of truth on resume; the transcript is never parsed.
- **Agents stall.** A batch of hunters and skeptics sat "running" for an hour
  with no output. Rule: an agent with no file after ~60 minutes is relaunched
  with the same prompt file; one with a file is never relaunched. Do not
  await a stalled agent.
- **Structured-output replies arrive wrapped or truncated.** Findings came back
  fenced in ```json, with control characters, or cut off. Rule: the script
  strips fences and parses with `strict=False`; a file that still fails is
  listed by `status` as BAD, and that one agent is relaunched.
- **Duplicates waste skeptics.** Two hunts (or both tracks) report the same
  defect at the same file. Rule: alias the duplicate's verdict to the original
  before launching skeptics; the report shows one entry.
- **Line numbers drift.** Findings were anchored before other agents edited
  the file. Rule: every patcher is told to read the real code and not trust
  the line.

## Judgement

- **Refute by default or the report is noise.** Roughly one in twelve
  correctness findings and a third of "clarity" findings fell to the skeptic;
  the ones that fell were exactly the plausible-sounding ones a patcher would
  have "fixed" into a regression (a guard for an impossible state, a Delete of
  a symbol with one real reader, a race the queue discipline already
  prevents).
- **The skeptic's corrected title is the finding.** Several confirmed findings
  had the right file and the wrong mechanism (a SIGPIPE inheritance stated as
  an env-var bug; a "connection leak" that was really a `defer` placed after
  the throwing call). Patchers that followed the hunter's text would have
  patched the wrong thing.
- **The strict maintainability review adds value only under a deletion
  constraint.** Its "code judo" question found real folds, but its natural
  remedies (a policy object, a state machine, a dispatcher, split the file)
  are exactly what the user calls over-design. The clarity track keeps the
  question and refuses the remedies that add a concept.
- **The notes can be wrong.** A documented spawn path was contradicted by a
  later gotcha in the same notes; the code followed the gotcha. Treat a
  contradiction between notes and code as a finding against the notes, and
  fix the notes in the last commit.

## Patching

- **Disjoint file groups, or the agents overwrite each other.** One shared
  transport file was needed by two groups; giving one group only the
  request-building function and the other the rest of the file worked, and
  the hunk was later staged alone with `git apply --cached` so each commit
  carried its own change.
- **Small groups the parent can do itself.** Four shell-script fixes were
  quicker to apply and `bash -n` than to brief an agent — but the first
  attempt put scratch files in the package's staging root, which would have
  shipped them. Read the whole script, not the line.
- **A patcher's "needed outside my group" list is real work.** One group
  reported that another group's side still trimmed an oversized argv; the
  owning group did not know. The orchestrator applied it after the owning
  agent finished.
- **Patchers may exceed a budget when the alternative is a broken fix.** One
  group needed one stored property more than the header allowed to keep a
  connection alive across a deferred close; it explained why in its report.
  Read the reason, then accept or reject — do not reject on the count.

## Build, test, commit, release

- **Builds sharing a cache run sequentially; tests in /tmp run beside them.**
  `make check` and three `make test` runs finished while the product targets
  (Xcode, Gradle, Cargo) built into a shared cache.
- **Three test runs, not one.** The test harness failed one run in four on a
  timing test during the patch agent's own check; three green runs in a row
  is the bar before commit.
- **A foreground wait that gets interrupted kills the shell.** A later
  platform build chained behind earlier ones never ran because the wait was
  interrupted; background long chains and read the log.
- **A build target may install things.** A debug helper target registered
  itself under the production identifier (a LaunchAgent, a systemd unit, a
  login item), which broke the installed app. Undo the matching uninstall
  target before finishing.
- **Match the repo's commit style.** Some repos title commits as a sentence
  about behaviour; the first commit of a run used `Area: verb` and stood out
  in the log. Read `git log` first.
- **The release target wants main == origin/main.** Push the run's commits
  before `make release` (or the repo's equivalent); its preflight refuses
  otherwise. `CLAUDE.md` may be a symlink to `AGENTS.md` — edit once, check
  with `ls -l`.
