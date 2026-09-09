# Arena acceptance status

This document records the current acceptance gate for
`feat/local-ai-training-v2` / PR #24.

## Current validated state

The fixed-seed Easy Arena attribution run `34092867501` used:

- checkpoint from Stage 1 `best`
- Easy opponent
- 20 games
- seeds 42–61
- model side balanced 10 White / 10 Black
- planner budget 5.0 s / 1024 states / 24 candidate Actions / 32 move depth

Observed result:

- 7 wins / 2 draws / 11 losses
- illegal action failures: 0
- stale failures: 0
- unexpected failures: 0
- planning failures: 11
  - neural: 5
    - time budget: 3
    - state budget: 2
  - Easy baseline: 6
    - time budget: 3
    - state budget: 3

Failure attribution by seed:

- neural: 42 (time), 46 (state), 48 (time), 50 (state), 60 (time)
- baseline: 43 (state), 51 (time), 52 (time), 53 (state), 55 (time), 56 (state)

Actor-specific reporting was accepted by run `34101659061` on head
`afa4075d7202f820b297475c1003a76064ca2bdb`. It reproduced the same 11
failures as 5 neural + 6 baseline failures while retaining the strict aggregate
failure gate.

The current branch head also passes both required validation suites. For head
`040fab7f9898aacff174d270b43bc8a3c2f35c1f`:

- CI run `34180368954`: success
- Local AI Training v2 CI runs `34180366685` and `34180369003`: success

## Reliability work completed after attribution

Arena now distinguishes three outcomes after a bounded planner stops without a
candidate:

1. A larger canonical `ActionSearch` finds a legal witness. Arena applies it
   through the normal transactional `apply_action_plan()` path and records an
   actor-specific planner recovery.
2. The larger search proves that no legal Action exists. Arena adjudicates the
   proven checkmate or stalemate.
3. The larger search is also inconclusive. Arena preserves the original
   planning failure and the strict CLI failure gate remains non-zero.

The following invariants are enforced in the result builder:

```text
planning_failure_count
  == neural_planning_failure_count + baseline_planning_failure_count

planner_recovery_count
  == neural_planner_recovery_count + baseline_planner_recovery_count
```

Recovery does not bypass `MoveValidator`, `ActionRules.can_submit`,
`RoyalRules.is_action_safe`, stale-plan checks, or the transactional application
probe.

## Residual planner bottleneck

The recovery path reduced ambiguity but did not make the fixed failure set
reliable. Follow-up runs against seeds 51, 53, and 55 still produced at least
one unresolved planning failure per game under the unchanged production budget.
Increasing the proof search to 8192 states / 30 seconds and 16384 states / 45
seconds did not resolve those three seeds.

The latest focused profile used seed 53 with the neural model playing Black.
The Easy baseline failed on White at action index 38 / ply 42 with three
timelines and two required boards:

- termination: state budget
- explored states: 1024
- completed candidate Actions: 0
- failed-state cache hits: 0
- planner wall time: 4.65 s
- `can_submit_action`: 1052 calls / 2.36 s
- `RoyalRules.is_action_safe`: 1052 calls / 2.33 s
- `clone_for_simulation`: 1034 calls / 0.95 s
- planner state-key construction: 1024 calls / 0.70 s

This evidence identifies canonical royal-safety evaluation as the largest
measured cost in the residual seed-53 search. It does not justify weakening or
skipping royal safety: the search must first establish a semantics-preserving
ordering, incremental query, or narrower proven-dead-state rule.

Experiments that did not pass the acceptance gate are intentionally not part of
production code:

- moving the failed-state lookup before submission checks
- prioritizing optional-board moves before required-board moves
- pruning every royal-unsafe state after required-board progress completes

The temporary workflows used for the completed attribution, revalidation, and
seed-53 profiling have been removed. Durable manual Arena validation remains in
`.github/workflows/local-ai-arena-validate.yml`; deterministic planner
before/after evidence remains in `.github/workflows/planner-regression.yml`.

## Next production gate

Do not advance to Medium/Hard Arena or scale beyond the Stage 1 checkpoint yet.
The next planner change must satisfy all of the following:

- preserve canonical complete-Action semantics and every existing safety rail
- add a focused regression for the exact state class it optimizes
- reduce unresolved failures for the published fixed seed set without relaxing
  the 5.0 s / 1024-state production envelope
- keep illegal, stale, and unexpected failures at zero
- retain actor-specific failure and recovery accounting
- pass normal CI, training CI, and the fixed-seed planner regression workflow

Until such a change is validated, the 7/2/11 result must not be interpreted as
model quality and no Medium/Hard benchmark or larger training run is accepted.

## PR policy

PR #24 remains experimental and must stay Draft and unmerged. Do not mutate
`main`, enable auto-merge, or mark the PR Ready for Review during this stage.
