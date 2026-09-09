# Arena acceptance status

This document records the acceptance gate for `feat/local-ai-training-v2` /
PR #24. The stable implementation head for the evidence below is
`b84c9cee494a1ab21c34c4e0fc289cf376b05afd` (before this documentation update).

## Decision

The engineering validations pass, but the Arena acceptance gate is **BLOCKED**.
The fixed-seed Planner Regression still has an unresolved seed 53 failure.
Medium/Hard Arena and larger self-play remain blocked.

## Root cause and planner fixes

The original planner defect was a move-depth cutoff treated as global state:
when one DFS branch reached its depth bound, later sibling branches could be
skipped. Commit `1fab473e` makes the cutoff branch-local; the regression test
also proves that a later sibling can remain a canonical, safe complete Action
and that the source engine is not mutated.

The remaining reliability problem is different: a deep/root subtree can spend
the bounded state or wall budget before a later shallow completion is visited.
This is search-order starvation, not evidence that canonical legality or royal
safety can be bypassed.

Commit `c5b3db5` productionizes a deliberately narrow hybrid path. Only the
exact budget `(max_seconds=5.0, max_states=1024, max_actions=24,
max_move_depth=32)` gets a depth-1, 1-second probe followed by a depth-32
fallback. Both phases share one prepared root, global tracker/deadline,
state/action counters, failed-state cache, and exact `MoveSpec` candidate-path
deduplication. All non-envelope budgets retain ordinary single-phase DFS.

Canonical ActionRules, MoveValidator, RoyalRules, replay/stale checks,
transactional plan application, and Arena recovery/adjudication/accounting were
not changed by this reliability work. Temporary diagnostic workflows were
removed at `b84c9ce`; the durable Arena and planner-regression workflows remain
the validation surfaces.

## Evidence for the depth and starvation behavior

The historical shallow-depth matrix is a diagnostic fixture, not a current
Arena result:

- seed 53 produced no candidate at move depths 2 through 8;
- seed 55 produced a length-2 candidate at depth 2;
- later depth-1 control runs found canonical length-1 witnesses.

A deterministic scheduling experiment showed ordinary deep-first DFS consuming
its bounded search before a later two-move witness, while a shallow probe could
preserve an already found shallow witness for fallback. This demonstrates the
starvation mechanism and the value of candidate preservation; it does not prove
that every deep subtree can be solved within the unchanged production envelope.

The correctness evidence is narrower and positive. The branch-local cutoff
test proves that one cutoff does not poison siblings. Hybrid tests cover local
probe interruption, global-deadline precedence, cumulative budgets, cutoff
cache exclusion, exact path deduplication including promotion, and canonical
replay/source immutability. The production search still discovers and applies
only canonical complete Actions through the existing safety rails.

The following alternatives were rejected or remain no-go options:

- larger proof budgets of 8192 states / 30 seconds and 16384 states / 45
  seconds did not resolve seeds 51, 53, and 55;
- moving failed-state lookup before completion checks, prioritizing optional
  boards ahead of required boards, or pruning every royal-unsafe state after
  progress did not pass the correctness gate;
- global caching of depth-cutoff or interrupted states is unsound because
  those states are unresolved;
- exposing geometric iterative-deepening or diagnostic public APIs would
  change ordinary budget behavior and was not productionized.

## Before/after status

The historical 20-game Easy run `34092867501` reported 7 wins, 2 draws, and 11
losses with 11 planning failures (5 neural, 6 Easy baseline), while illegal,
stale, and unexpected failures were zero. That run predates the current
branch-local and exact-envelope reliability work and is retained only as a
baseline; it is not a current PASS claim.

Current local validation of the stable head passed the full suite with 448
passed and 2 skipped tests. Current-head CI run `34380462968` succeeded, and
training CI runs `34380462975` and `34380465712` succeeded.

## Fixed-seed Planner Regression

Planner Regression run `34380464000` failed its durable gate with unresolved
seeds `[53]`; seeds 51 and 55 resolved. In CI, seed 53 still had one planning
failure and two planner recoveries. This is an explicit unresolved failure,
not a PASS.

The current-head local capture was repeated twice with seed 53, neural Black
versus Easy, one game, Stage 1 `best`, and the exact 5.0/1024/24/32 budget.
Both local runs captured the same unresolved Black planner state at ply 99:

- zero candidates and `time_budget` termination;
- 16 timelines and 14 required/movable boards;
- 0 optional boards and 1,639 root legal moves;
- archive restoration and a second production search reproduced the zero-
  candidate result with an unchanged engine signature.

The local Arena aggregate was one planning failure and three recoveries. This
differs from the CI artifact's one failure/two recoveries and is recorded as
local-versus-CI variance, not as a successful reproduction. The requested
Easy20 acceptance run was not started because the durable fixed-seed gate
remained failed. The disposable local capture files were removed after these
facts and restoration checks were recorded.

## Next production gate

Do not advance to Medium/Hard Arena or scale beyond the Stage 1 checkpoint until
the fixed-seed gate is resolved. The next planner change must:

- preserve canonical complete-Action semantics and all safety rails;
- include a focused regression for the exact state class it optimizes;
- reduce unresolved failures for the published fixed seeds without relaxing
  the 5.0-second / 1024-state production envelope;
- retain zero illegal, stale, and unexpected failures plus actor-specific
  recovery accounting; and
- pass normal CI, training CI, and the fixed-seed Planner Regression.

## PR policy

PR #24 remains experimental and must stay Draft and unmerged. Do not mutate
`main`, enable auto-merge, or mark the PR Ready for Review during this stage.
