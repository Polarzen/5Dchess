# Arena acceptance status

This document records the current acceptance gate for `feat/local-ai-training-v2` / PR #24.

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

Cleanup head `d9c28eae665b34144a15dfce392619a9f70e9995` passed both required validation workflows:

- CI run `34094705484`: success
- Local AI Training v2 CI run `34094705603`: success

## Acceptance interpretation

The aggregate 7/2/11 W/D/L is not a clean model-quality measurement because the Easy baseline itself accounts for 6 of the 11 planning failures. The evidence also rules out a neural-only failure mode: both actors are hitting the shared bounded complete-Action search limits.

Do not advance to Medium/Hard Arena and do not scale training while this reliability ambiguity remains.

## Next production gate

`src/training/arena.py` should report planning failures by actor while retaining the existing aggregate field for compatibility.

Required fields:

- `planning_failure_count`
- `neural_planning_failure_count`
- `baseline_planning_failure_count`

Required invariant:

```text
planning_failure_count == neural_planning_failure_count + baseline_planning_failure_count
```

The existing strict Arena/CLI failure gate must continue to use the aggregate count. This change is reporting-only and must not relax planner budgets, canonical move validation, Royal safety, stale-plan rejection, or any other safety rail.

After the reporting change passes CI, rerun the exact same Easy seed schedule and budget. Acceptance requires the actor-specific fields to reproduce the established attribution of 5 neural and 6 baseline planning failures. Only then should planner reliability work proceed against the fixed failing seeds.

## PR policy

PR #24 remains experimental and must stay Draft and unmerged. Do not mutate `main`, enable auto-merge, or mark the PR Ready for Review during this stage.
