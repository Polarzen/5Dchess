# Arena acceptance status

This document is the durable status for the Planner reliability work around
PR #24. The current baseline is `70a5f495`; durable baseline run
`34745200932` remains the acceptance reference.

## Decision

The local fixed-seed gate now **PASSES** for seeds 51, 53, and 55 under the
unchanged production budget. Wider Arena acceptance remains **PENDING**:
Easy20 is running, and control seeds 42/43 retain planning failures.
Medium/Hard Arena and large self-play remain blocked. PR #24 remains Draft
and **DO NOT MERGE**. Historical remote results below refer to `8d2ffb23`.

## 2026-10-11: exact required-board threat certificate

The `8d2ffb23` seed 53 failure was reproduced locally with the exact remote
state signature, at white Action 40 / ply 43 / six timelines. This state is
now retained as `tests/fixtures/seed53_uncapturable_threat_state.json.gz`.
It has four required boards and 357 legal root moves. Every one of the 108
current legal moves advancing L0 leaves a direct royal threat. That finite
observation motivated a stronger proof; it is not itself the terminal oracle.

`src/engine/action_proof.py` proves only a restricted, unavoidable threat:

1. No future branch by the acting player can be active, and no existing
   opponent timeline can become newly active. The required board must therefore
   advance before submission; it cannot be deferred by rewinding The Present.
2. Its virtual successor contains an enemy attacker whose target King and
   entire attack path already exist on opponent-phase boards. These boards are
   immutable during the current Action; virtual-only King/path boards are
   explicitly rejected as evidence.
3. No piece on any currently movable board, including optional/inactive boards,
   can geometrically capture that attacker. Geometry deliberately ignores
   occupancy and local safety, so it overapproximates possible legal captures.
   Pawn attackers are excluded to avoid an en-passant exception.
4. All successors created during this Action have the opponent's side to move,
   including new branches. No new acting-color source can arise later; existing
   capture sources only disappear. The attacker and its fixed attack therefore
   survive every possible completion.

This independent certificate is checked at the search root, inside existing
deadlines and state accounting. Missing evidence or interruption returns to
ordinary bounded search; timeout still means unknown. No legality, royal-safety,
Arena scoring, recovery, or production-budget rule was relaxed. The planner
uses it only for the existing exact 5/1024/24/32 envelope; canonical terminal
search also uses the same proof.

The Stage 1 model is unchanged, SHA-256
`de4997302ab767a797ee91da1b2aa2f73576b17a7174a65c800ae0f1d04e2e55`.
Local seed 53 now ends after 40 Actions as a proven Black win, with zero
planning failures/recoveries, in 8.547 seconds. Seeds 51 and 55 also have zero
planning failures/recoveries. Controls 42 and 43 have one failure each, with
one and zero recoveries respectively. All five have zero illegal/stale/
unexpected failures and consistent actor-specific accounting.

Validation: full local suite 472 passed / 2 skipped, followed by the added
Black-symmetry regression passing. Coverage includes exhaustive canonical
search agreement in small White/Black positions, a real capture escape, a real
active-branch escape, optional capture sources, mutable virtual paths/Kings,
allocation/activity preconditions, and interrupted proof handling. Compileall
and browser/invite checks passed. The original GitHub checkpoint artifact from
run `34028226472` has expired; these fixed-seed results use its locally retained,
hash-verified model and are not a new remote workflow PASS.

The earlier branch-local depth-cutoff fix remains valid historical context: a
cutoff in one DFS branch must not suppress later siblings. The current failure
class is different. A large required-board subtree can consume the bounded
search before a later complete Action is visited. The production envelope is
unchanged at 5 seconds, 1024 states, 24 Actions, and move depth 32, with the
existing canonical legality, royal-safety, cache, hybrid, and transactional
application rules.

## Durable baseline

The five-seed baseline reported the following aggregate results. `F` is a
planning failure and `R` is a Planner recovery; illegal, stale, and unexpected
failures were zero for every seed.

| Seed | Actor | F | R |
| ---: | :--- | ---: | ---: |
| 42 | white | 1 | 0 |
| 43 | black | 1 | 0 |
| 51 | black | 0 | 0 |
| 53 | black | 1 | 3 |
| 55 | black | 0 | 0 |

For seed 53, the actor breakdown is baseline F1/R2 and neural F0/R1. The
published remote final failure is white, action 88 at ply 131, with 20
timelines, 183 explored states, and 5.1229 seconds. A separate local final
failure is white, action 86 at ply 129, with 19 timelines, one required board,
two movable boards, and 169 root moves. These are different captures and must
not be combined.

## Seed 53 witness and failure evidence

The durable large-required fixture is action 77 at ply 99: black to move, 14
required boards, 14 movable boards, zero optional boards, and 1,639 root legal
moves. The later action history contains an actual submitted 11-move witness
for this state. Its canonical replay submitted successfully, changed the
turn, and left the source signature unchanged. This proves that the archived
path is legal and replayable; it does not prove that the unchanged production
five-second search discovers it in time.

The large-required regression exposed the baseline `time_budget` failure; the
current candidate repairs that case, while the retained historical
two-required regression remains passing. The durable fixed-seed gate for
`8d2ffb23` **FAILED** with seed 53 unresolved.

## Production admission boundary and validation delta

MRV B is now admitted only when `len(required) > 2` and the budget is exactly
`max_seconds=5.0`, `max_states=1024`, `max_actions=24`, and
`max_move_depth=32`. Other budgets retain the established ordering. An
unrestricted B implementation exhausted the existing 32-required regression
at 64 states with a 64-state, one-Action, depth-64, no-wall budget. The
restriction restores that compatibility behavior; it does not establish a
universal MRV improvement. The boundary was approved by expert review.

The measured B/E benefit therefore applies only to the exact production
envelope. The current candidate is committed and pushed as `8d2ffb23`.
Focused local validation reports 45 passed, including the complex 32-required
case, the large-required fixture, and each-field budget dispatch checks. The
latest local full run reports 460 passed, 2 skipped, and one existing telemetry
warning in 34.38 seconds; the prior 454 passed, 2 skipped, and 1 failed
snapshot is historical and has been repaired. The AI subset reports 22 passed
and the localization subset reports 2 passed. Compileall and the three Node
browser/invite syntax gates also passed.

Remote results for `8d2ffb23`, rechecked on 2026-10-11:

- Planner Regression [34803520789](https://github.com/Polarzen/5Dchess/actions/runs/34803520789): **FAIL**.
- CI [34803524555](https://github.com/Polarzen/5Dchess/actions/runs/34803524555): **PASS**.
- Training CI [34803527738](https://github.com/Polarzen/5Dchess/actions/runs/34803527738): **PASS**.

The candidate artifact reports zero planning failures for seeds 51 and 55.
Seed 53 still has one baseline (white) planning failure and zero recoveries:
action 40, ply 43, six timelines, 445 explored states, zero candidates, and
`time_budget` after 5.1083 seconds. Its state-signature SHA-256 is
`e74d20219af8ad5006d2981156b116f6c34e20336f3436a80690d8edf5537235`.
This is a different state from both older seed 53 captures described above.
Seeds 42 and 43 also retain one planning failure each; their recovery counts
are one and zero respectively. Illegal, stale, and unexpected failures remain
zero. Easy20 has not started.

## Cost and ordering evidence

Profile timings below are instrumented samples. Function times are inclusive,
so overlapping costs must not be added. They are separate from minimum
telemetry such as first-witness timing and from the charged search counters.
Counts from different instrumentation runs are not merged into before/after
comparisons.

| Capture | Royal safety | Clone | State key | Legal generation | First fallback root |
| --- | ---: | ---: | ---: | ---: | ---: |
| Many-required | 3.091 s | 1.282 s | 0.236 s | 0.250 s | 68 states / 3.985 s |
| Optional final failure | 1.596 s | 2.341 s | 0.705 s | 0.094 s | unresolved under A/B/E |

The three-round structural matrix used the unchanged 5/1024/24/32 envelope:

| Variant | Result | First observation | Full observation |
| --- | --- | --- | --- |
| A original | 0 candidates | 70–71 states | 5.047–5.063 s |
| B positive-count required-board MRV | 24 candidates, depth 8 | 9 states / 2.015–2.078 s | 32 states / 3.157–3.203 s |
| C merged required progress | 0 candidates | 77–80 states | 5.047–5.063 s |
| D root-only structural key | 0 candidates | 67–68 states | 5.046–5.063 s |
| E recursive structural key | 24 candidates, depth 8 | 9 states / 1.984–2.000 s | 32 states / 3.125–3.171 s |

Historical controls constrain the choice. Seed 51 produced zero candidates for
A/B/E at 118/118/119 states. Seed 55 produced 20 candidates for A, 24 for B,
and zero for E, so E is rejected despite its slightly shorter current timing.
B is the provisional data-supported direction because it is the simpler
successful required-board MRV variant; it is not yet an acceptance result.

Separate probe accounting reported the following charged counts:

| Probe schedule | Candidates | Charged count |
| --- | ---: | ---: |
| Eager | 0 | 343 |
| Lazy | 24 | 146 |
| Per-board | 24 | 158 |
| Priority-class | 0 | 370 |

The charged counter is not a pure expanded-state count, and none of these
probe schedules is a newly qualified production probe. No hidden probe budget
or changed safety/cache semantics is admitted.

## Remaining gate

The historical durable gate failed at `8d2ffb23`; the current local fixed-seed
gate passes as recorded above. The admitted MRV path must prepare required
boards only where the state class needs it, use
positive count with zero-outgoing boards last, reuse local legal lists, keep
optional handling lazy, and avoid inserting an interrupted preparation into
the failed state cache. It must retain canonical Move generation, safety
checks, and the 5/1024/24/32 limits without a seed-specific or state-specific
heuristic.

The next acceptance result is Easy20 using the same Stage 1 checkpoint and
explicit 5/1024/24/32 limits. Fresh remote CI and training CI are also required.
Remote fixed-seed execution additionally needs restoration of the expired
checkpoint artifact; local results must not be presented as a remote PASS.
Medium/Hard and large self-play stay blocked until wider Arena reliability is
established, including the remaining control failures.

Temporary profiling and trace files are diagnostic only. Root may remove them
after preserving the compact evidence above. This document deliberately makes
no final PASS or completion claim.
