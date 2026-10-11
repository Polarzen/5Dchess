# Arena acceptance status

This document is the durable status for the Planner reliability work around
PR #24. The current baseline is `70a5f495`; durable baseline run
`34745200932` remains the acceptance reference.

## Current follow-up: prefer available King defenses for local checks

Implementation `8e7ea9a6` passes the local suite (594 passed, 2 skipped) and
CI `38148554985` / Training CI `38148557749`. The fresh fixed-seed batch stops
at seed 42: zero planning failures but one neural Action recovery at Action 88,
ply 130, with 25 required boards on 31 timelines (90.735 seconds). Seeds
43/51/53/55 and all Arena tiers were not run on that implementation.

The new snapshot has a board-local virtual check. Incoming capture priority
consumes another board before the threatened King uses its own legal escape.
Defense ordering now defers that capture priority only when canonical Move
generation confirms a legal departure for the King. Without a King departure,
incoming capture priority remains; captures against nonlocal targets keep their
priority. Every legal Move remains in the fallback order, and preparation
continues to respect the shared deadline.

The diagnostic returns 24 replayable candidates in 2.297 seconds for the new
state; three historical large snapshots also return 24. The focused run passes
45 tests; two new blocked-King test layouts initially leave inter-timeline King
escapes open. Corrected layouts close those routes, and all five local-check/
interruption boundary tests pass. Fresh full-suite and fixed/Arena acceptance
are pending.

## Earlier follow-up: skip structurally impossible single-Move probes

Implementation `aa916b87` passes the local suite (590 passed, 2 skipped), all
five fixed seeds and Easy20 (W16 D3 L1, 197.547 seconds), with zero failures
or Action recoveries. Training CI `38147636546` passes. CI `38147634092` fails
one captured 23-required-board test: no candidate in five seconds, 15 states;
510 tests pass and 6 skip. Medium and Hard are not started on this version.

The production single-Move probe cannot succeed with more than two required
boards when the existing allocation/activity certificate proves those boards
cannot be deferred by branching. A canonical Move advances at most two old
boards. The planner now skips only that structurally impossible probe and
keeps the original global budget for deep search. No failed-state or artificial
depth-cutoff evidence is recorded. Real active rewinds remain eligible; the
explicit minimax strategy is unchanged. Telemetry identifies the skipped phase.

The focused probe/MRV/defense suite passes 42 tests, including canonical
one-Move exhaustion followed by a multi-Move witness, a proved terminal state,
and actual active-rewind escapes. The new captured primary-budget regression
passes locally. Fresh full-suite, CI and fixed/Arena acceptance are pending.

## Earlier follow-up: avoid historical copies in internal royal queries

Implementation `4cadbfc1` passes 577 tests (2 skipped), all five fixed seeds,
Easy20 (W16 D3 L1, 189.437 seconds) and Medium20 (W0 D0 L20, 119.938 seconds),
with zero planning failures, Action recoveries or illegal/stale/unexpected
errors. Both CI `38144452970` and Training CI `38144455731` pass. Hard is
stopped during game 12 after neural Black needs one recovered Action in game
10 at Action 115. That game ends in stalemate at Action 118. No full Hard20
result exists, and the zero-recovery gate has not passed.

The captured position has 23 required boards. Repeated generic deep copies of
historical Positions in virtual-Present royal checks consume much of the
primary budget. Internal threat queries now borrow unchanged canonical history
and copy only touched timeline containers and new virtual successors. They
only read that view and return frozen threat values or a boolean. The default
isolated virtual-pass API remains unchanged; subclasses, dynamic attributes
and nonstandard position mappings retain the generic deepcopy fallback.

The diagnostic view returns 11 canonical candidates under the original
5-second budget, compared with zero before. Six captured differential cases
compare both colors against the isolated virtual-pass result, and source/
successor isolation and fallback tests cover mutable boundaries. The focused
suite passes 56 tests; the new captured primary-budget replay also passes.
The full suite passes 590 tests, with 2 skipped and one existing telemetry warning, in 252.72 seconds. Fresh fixed/Arena acceptance is pending.

## Earlier follow-up: certify an unavailable last active rewind

Implementation `271b37be` passes 569 tests (2 skipped), all five fixed seeds,
Easy20 (W16 D3 L1, 202.265 seconds) and Medium20 (W0 D0 L20, 94.141 seconds),
with zero planning failures, Action recoveries or illegal/stale/unexpected
errors. Both CI `38141939326` and Training CI `38141941492` pass. Hard is
stopped during game 8 after a baseline White planning failure in game 6 at
Action 112; its secondary search is unresolved. No full Hard20 result exists.

Both required boards expose fixed royal attacks. The general activity guard
previously declined because one more active branch could be allocated, but
every legal early branch either exposes an irreversible attacker or is absent.
The new certificate checks this last active allocation with canonical legal
Moves, after checking fixed ownership/allocation and active opponent lanes.
All original acting sources must be at or after Present. Non-branching Moves
cannot create an earlier acting-phase destination before the first branch;
after that branch all later actor allocations are inactive. Interruptions,
multiple remaining active allocations and real rewind escapes decline proof.

The captured failure is now proved terminal in approximately 0.13 seconds.
Exhaustive small White/Black cases and an existing canonical rewind escape
check the boundary. The full suite passes 577 tests, with 2 skipped and one existing telemetry warning, in 235.65 seconds. Fresh fixed/Arena acceptance is pending.

## Earlier follow-up: preserve threatened King boards during arrivals

Implementation `17d9d1fa` passes 566 tests (2 skipped) and both
[CI](https://github.com/Polarzen/5Dchess/actions/runs/38140184768) and
[Training CI](https://github.com/Polarzen/5Dchess/actions/runs/38140187745).
Seeds 51/53/55 pass, but control 42 reaches a new 20-required-board position
at Action 68 and ends with one neural planning failure, zero recoveries,
and zero illegal/stale/unexpected errors (91.829 seconds). The batch stops;
seed 43 and all Arena tiers were not rerun on that implementation.

The arrival prefix used the threatened King's board to advance an immobile
neighbor, consuming the board's royal-defense opportunity. The resulting
partial Action has a conservative required-board threat certificate; other
arrival sources preserve an escape. The follow-up orders those other sources
first only for immobile-board arrivals. Moves of the threatened King itself
and captures of a known attacker retain their original priority; unrelated
departures from that board are deferred and remain searchable. The established
later capture-defense order is unchanged. No proof rule,
model, recovery path or search budget is changed.

The diagnostic prototype returns 24 candidates in 4.078 seconds for the new
position, with an 11-Move first Action. The older two-immobile-board and
19-required-board snapshots also retain canonical candidates. Focused
validation initially passes 34 tests, but the first full suite exposes one
old arrival regression (566 passed, one failed): deferring a whole threatened
source also delays its King escape. The refined per-Move order preserves that
escape, passes four critical captured regressions and two candidate-set/source
immutability checks. The final full suite passes 569 tests, with 2 skipped
and one existing telemetry warning, in 237.70 seconds. Fresh fixed-seed and
Arena gates remain pending.

## Earlier follow-up: skip forced multi-Move prefixes in the short probe

Implementation `51921ee2` passes 562 tests (2 skipped), all five fixed seeds,
Easy20 (W16 D3 L1, 192.688 seconds) and Medium20 (W0 D0 L20, 93.422 seconds),
with zero planning failures, Action recoveries and illegal/stale/unexpected
errors. Neither completed Arena tier invokes secondary search. Both
[CI](https://github.com/Polarzen/5Dchess/actions/runs/38137214339) and
[Training CI](https://github.com/Polarzen/5Dchess/actions/runs/38137216744) pass.

Its Hard diagnostic reaches a new baseline failure at game 16 / Action 118.
Primary and secondary searches are inconclusive there. The run is stopped
while starting game 18, after game 17 completes, without a 20-game aggregate.
This is not a Hard acceptance pass. The captured eight-required-board position
has a legal one-Move rewind; the one-second probe has insufficient margin
because it also clones non-branching prefixes which cannot finish in one Move.

The follow-up skips such prefixes only during minimax's one-Move probe. A
non-branching Move can advance only its source and destination and cannot
change timeline activity. If another required board remains, the path needs
another Move. Recording a depth cutoff preserves that path for the deep phase
and prevents incorrect failed-state memoization. Branches and optional arrivals
which can complete the required-board progress remain eligible. Other planner
strategies and all global budgets are unchanged. The explicit probe also
respects a configured move-depth limit of zero.

The new captured state yields 24 canonical candidates in 0.781 seconds.
Focused validation passes 60 tests, including deep-phase preservation and a
one-Move arrival from an optional board. The final full suite passes 566 tests,
with 2 skipped and one existing telemetry warning, in 271.50 seconds. Fresh
fixed-seed and Arena validation remain pending on this source.

## Earlier follow-up: bounded minimax probe and fixed-successor checks

Implementation `46140100` passes 546 tests (2 skipped), all five fixed seeds
51/53/55/42/43, Easy20 (W16 D3 L1) and Medium20 (W0 D0 L20), with zero
planning failures, Action recoveries and illegal/stale/unexpected errors.
Both [CI](https://github.com/Polarzen/5Dchess/actions/runs/38133991344) and
[Training CI](https://github.com/Polarzen/5Dchess/actions/runs/38133994097) pass.
Easy's single terminal adjudication comes from an ordinary exhaustive primary
search; neither completed Arena tier uses a secondary search.

Hard20 was stopped during diagnosis and has no final 20-game aggregate.
Game 10 requires two baseline Action recoveries (Actions 108 and 110), then
has an unresolved baseline planning failure at Action 112. The latest progress
file records game 13 completed; this is not a Hard20 acceptance pass.

The new follow-up gives minimax an explicit one-second one-Move probe followed
by its established depth-first board order. Both phases share the original
state, candidate, depth and absolute five-second limits. Admission uses the
configured budget, not rounded remaining time; other configured budgets keep
their previous strategy. Search filters a Move only when advancing its source
or non-branching destination would materialize an enemy attacker against an
already-existing opponent-phase King and clear path. Capturing that attacker
remains available; Pawns and virtual King/path evidence do not certify a prune.

All four old/new nonterminal Hard snapshots now return canonically replayable
Actions. The final snapshot exhausts without a candidate or timeout, rather
than being classified terminal from a budget failure. Focused tests cover
White/Black captures, cross-board arrivals, branch preservation, interruption,
source immutability, strategy reset and shared budgets. The full suite passes
562 tests, with 2 skipped and one existing telemetry warning, in 225.63 seconds.
Fresh fixed-seed/Arena gates remain pending for this follow-up.

## Earlier follow-up: retain arrival priority and safe rewind sources

Implementation `7f65cbe1` passes 544 local tests (2 skipped, one telemetry
warning; 223.36 seconds) and both [CI](https://github.com/Polarzen/5Dchess/actions/runs/38133043598)
and [Training CI](https://github.com/Polarzen/5Dchess/actions/runs/38133045806).
Seed 53 passes with zero failures/recoveries in 7.187 seconds. Seed 42 reaches
two new positions and finishes with one neural failure and one neural recovery
in 174.516 seconds. The gate stops there; seeds 43/51/55 and all Arena tiers
were not run on this implementation.

The new follow-up keeps root immobile-board arrival priorities through
descendants until those boards advance. This prevents the second immobile
board from losing its incoming sources after the first is handled. The
one-Move rewind probe also tries sources without a known virtual attacker
before sources that would expose that attacker. Both are ordering changes;
all legal moves remain available and no timeout is treated as terminal.

Captured seed 42 Action 72 now yields 21 candidates (first Action: 14 Moves),
and Action 80 yields 24 one-Move candidates in 0.656 seconds. Both first
candidates replay canonically and leave their sources unchanged. Captured
regressions also check that planner arrival hints reset for a fresh search.
The full suite passes **546 tests, with 2 skipped and one existing telemetry
warning**, in 222.13 seconds. The fresh fixed gate is running. No completion
cache, Royal copy optimization, model change, or budget increase is included.

## Earlier follow-up: preserve defenses and arrival sources

Implementation `19ecc4d8` passes the full local suite (541 passed, 2 skipped,
one telemetry warning) and both [CI](https://github.com/Polarzen/5Dchess/actions/runs/38131254706)
and [Training CI](https://github.com/Polarzen/5Dchess/actions/runs/38131256889).
The fresh fixed gate still fails the no-recovery requirement: seed 43 has
zero failures / two recoveries (199.359 seconds), seed 42 has zero failures /
three recoveries (278.422 seconds), and seed 51 has zero failures / recoveries
(16.625 seconds). Seed 53 was stopped during diagnosis after another empty
primary search; seed 55 and all Arena tiers were not run on this revision.

The new follow-up narrows one-board arrival priority to immobile
required boards and reuses their prepared legal moves. Exact source-square
queries now restrict destination generation in capture checks. Large quiet
frontiers use lazy generation; immobile kingless required boards receive an
arrival before other defenses consume their sources. Smaller frontiers with
concrete required-board attackers prioritize defense during the deep phase.
All moves, proof boundaries, and primary/secondary budgets remain unchanged.

A focused run passed 62 tests before the final small-frontier defense admission
was added. Captured seed 42 Actions 76/77/78 return replayable candidates under
the primary budget; seed 43 Actions 80/87 have captured replay regressions.
A new seed 53 three-required-board regression covers the final admission.
The final full suite passes **544 tests, with 2 skipped and one existing
telemetry warning**, in 223.36 seconds. The fresh gate later failed on seed 42 as recorded above.
Copy optimizations remain experiments only; no Royal virtual-copy change is
included.

## Earlier follow-up: late seed 43 positions

Implementation `e90bfe46` preceded this follow-up. Its 523-test suite and both
[CI](https://github.com/Polarzen/5Dchess/actions/runs/38127749935) and
[Training CI](https://github.com/Polarzen/5Dchess/actions/runs/38127752371) pass.
Seeds 51/53/55/42 have zero failures and recoveries, but the fresh control 43
game reaches different late positions and ends with one neural planning
failure and six Action recoveries (281.469 seconds). The current no-recovery
acceptance gate therefore remains open; no Arena tier has been rerun on this
implementation. Earlier passes below are not relabeled as current results.

The next uncommitted follow-up addresses the captured positions with targeted
canonical destination generation, optional arrivals to an immobile required
board, and a conservative full-capacity certificate for a sole arrival source
whose every arrival creates an irreversible direct threat. White/Black small
positions are compared against exhaustive search, including alternate-source,
attacker-removal, spare-capacity, and interruption escapes.

Large-board defense tries captures from other boards in the established
defense-board priority, then lazily generates required-board progress before
other historical destinations. Using canonical source order for that capture
prefix regressed the older 19-required-board fixture; the priority correction
handles both that fixture and the new 27-required-board fixture. Royal geometry
uses primitive cache keys with the same exact geometry and path predicates.
A separate defect discarded an already-proved two-board completion when
preparing later candidates timed out; complete candidates are now retained
immediately. A deterministic clock regression covers that loss of evidence.

All seven new captured states now either return a canonically replayable
candidate (Actions 94/95/100/101/103/104) or prove terminal (Action 105), with
the unchanged primary budget in the earlier snapshot probe. The first full
suite exposed the capture-order regression above (540 passed, one failed).
After correcting that priority, the full suite passes: **541 passed, 2 skipped,
one existing telemetry warning**, in 226.71 seconds. Fresh fixed-seed and Arena
validation remain pending. A virtual-copy optimization was investigated but
is not included.

## Earlier capacity and minimax follow-ups

The next acceptance phase is in progress. It must resolve the Easy recovery
dependency and seed 42 before proceeding to Medium20 and Hard20 with the same
Stage 1 model and 5/1024/24/32 primary planner budget.

On baseline `dfe1c13c` (implementation `c573320e`), seed 42 was reproduced:
one neural recovery at Action 54 and one baseline failure at Action 75,
in 201.657 seconds. The failure signature matches the historical capture.
At Action 75 all 32 timeline slots are occupied. Required board L10 has 21
nominal legal moves, but all require a new branch and execution rejects every
one; no existing source can advance that board by arrival.

Legal-Move APIs now exclude branch allocations at full capacity, consistently
with execution. The immobility certificate then proves this captured state
is stalemate. At capacity there can be no new lanes, activity changes, or future
branch destinations; below capacity the previous conservative guards remain.
Tests compare generated moves with actual execution and use exhaustive small
White/Black positions, plus a spare-slot escape, to check the proof boundary.

Multi-board search also prioritizes moves advancing two required boards before
ordinary piece preferences. Board MRV and the exact production-budget admission
remain unchanged; all executable moves and optional sources remain searchable.
The captured 26-board Easy recovery and 14-board seed 42 recovery both have
canonical complete candidates within the unchanged primary budget.

Implementation `02e2abd6`: focused checks 17 passed; full suite 514 passed,
2 skipped, one existing telemetry warning. Seeds 51/53/55 and controls 42/43
all pass with zero failures/recoveries in 24.969 / 7.359 / 9.796 / 34.875 /
165.672 seconds. Illegal/stale/unexpected failures are also zero.
[CI 38125405239](https://github.com/Polarzen/5Dchess/actions/runs/38125405239)
and [training CI 38125407568](https://github.com/Polarzen/5Dchess/actions/runs/38125407568)
both passed. Easy20 passes the strict no-recovery gate: 17 wins / 2 draws /
1 loss, zero planning/illegal/stale/unexpected failures, zero recoveries,
one proven terminal adjudication, and 278.563 seconds. Medium20 also has zero
planning/illegal/stale/unexpected failures and zero recoveries, in 138.172
seconds; the model loses all 20 games. This passes the reliability gate but
does not establish competitive playing strength.

The first Hard20 attempt was stopped after game 13 completed: game 12 needed
secondary search at Actions 50 and 58. Its partial run is diagnostic evidence,
not a completed Hard20 result. Two captured positions show that the exact
five-second profile can time out while depth-first enumeration finds candidates.
Alpha-beta previously selected that profile accidentally when the remaining
time rounded to exactly five seconds. The follow-up explicitly selects stable
depth-first ordering for minimax and shares its original absolute deadline;
the default Easy/neural strategy is unchanged. Fresh validation is in progress.
The minimax follow-up passes 9 focused regressions and the full suite:
523 passed, 2 skipped, one existing telemetry warning (207.80 seconds).
The fixed seeds and all three Arena tiers are being revalidated before any
results from the new implementation are accepted.

Zero recovery here means no Action required a witness from the secondary
search. Easy20 game 3 / Action 37 still timed out in the primary planner and
was then proved terminal by the existing secondary ActionSearch (budget:
15 seconds / 4096 states / depth 64). This is counted as one terminal
adjudication, not an Action recovery. It does not establish that every terminal
determination completes within the five-second primary budget.

New evidence in `reliability_phase2` of `planner-validation-20261011.json`
records raw source fingerprints and the original model SHA-256. Early fixed
runs preceded a three-line comment clarification; their exact previous bytes
were reconstructed and Python AST equality checked. No executable source
changed between these runs and the implementation commit.

## Previous completed local gate

The requested **local fixed-seed gate and Easy20 zero-failure gate PASS** on
`c573320e`, using the original hash-verified Stage 1 model and unchanged
5-second / 1024-state / 24-candidate / depth-32 planner budget.

- Seeds 51/53/55: zero planning failures, zero recoveries, and zero
  illegal/stale/unexpected failures.
- Easy20: 17 wins / 3 draws / 0 losses; zero planning/illegal/stale/unexpected
  failures; one neural recovery and one proven terminal adjudication, in
  590.610 seconds. Colors alternate, seed is 42, maximum 120 Actions per game.
- Full local suite: 507 passed, 2 skipped, one existing telemetry warning.
  [CI 38123333450](https://github.com/Polarzen/5Dchess/actions/runs/38123333450)
  and [training CI 38123835529](https://github.com/Polarzen/5Dchess/actions/runs/38123835529)
  both passed on the implementation commit.

This is **not** a strict no-recovery or merge-readiness PASS. Easy20 game 1 /
Action 76 needed the existing recovery path, which has its own larger budget;
the primary planner did not complete every Arena Action within five seconds.
The W/D/L describes the evaluated system including that recovery. Control 42
also has an unresolved F1/R1 result on `50ebcd3b`; control 43 passed there.
These extra controls were not rerun on `c573320e` and are not relabeled as such.

The original remote checkpoint artifact expired, so the local Planner/Arena
results are not a remote workflow PASS. Workflow-file changes remain only in
the preserved local follow-up patch because the current credential lacks
`workflow` scope. PR #24 and stacked PR #25 remain Draft and unmerged;
`main` and `feat/local-ai-training-v2` are unchanged. Medium/Hard and larger
self-play remain deferred until wider reliability work is complete.

Final compact evidence is `followup_v6` in `planner-validation-20261011.json`.
The sections below preserve earlier implementation-specific evidence.

## Pinned-capture rewind follow-up

Easy20 on `50ebcd3b` completed in 448.890 seconds: 15 wins / 3 draws / 2 losses,
two planning failures (neural game 1 / Action 74; baseline game 7 / Action 49),
one neural recovery (game 1 / Action 68), and one terminal adjudication.
The implementation passed [CI 38122105669](https://github.com/Polarzen/5Dchess/actions/runs/38122105669)
and [training CI 38122108143](https://github.com/Polarzen/5Dchess/actions/runs/38122108143).
Full compact results are stored as `followup_v5`.

Both counted failures have immutable royal targets and geometric captures that
are canonically illegal. The rewind hint now checks actual legal captures,
including pins and blocked paths. It lazily prepares historical branches from
one source board at a time, optional sources first, so preparation of a large
frontier cannot consume the entire one-second probe before trying a move.
This remains ordering only; fallback and terminal proof rules are unchanged.
Both captured states now produce complete one-Move candidates with canonical
replay. Eleven focused checks passed. Full suite: 507 passed, 2 skipped, one
existing telemetry warning. Fixed seeds 51/53/55 passed with zero planning
failures/recoveries in 30.234 / 9.281 / 12.515 seconds. Its completed Easy20
result and CI links are recorded in the Decision above.
The extra controls are retained at their explicitly identified `50ebcd3b`
results and are not claimed as new runs of this follow-up.

A diagnostic faster virtual-pass copy reduced scan time but did not resolve
these counted failures. That experimental copy implementation is not included.

## King-escape and royal-scan follow-up

Easy20 on `a3ef5109` completed in 396.672 seconds with 16 wins / 3 draws / 1 loss,
one neural failure at game 1 / Action 60, zero recoveries, and one terminal
adjudication. The earlier game 12 failure did not recur. Implementation
`a3ef5109` passed [CI 38121032672](https://github.com/Polarzen/5Dchess/actions/runs/38121032672)
and [training CI 38121034818](https://github.com/Polarzen/5Dchess/actions/runs/38121034818).
Its compact results are recorded as `followup_v4`.

The remaining 19-board state has a complete King-escape Action. The first two
King destinations create different virtual threats; a later destination is
safe. The follow-up orders threatened King boards first and defers unsafe King
moves within the admitted large-board defense strategy. Deferred moves remain
searchable: virtual threats are not a no-Action proof. All prepared children
use canonical execution and the same deadline. The active-rewind probe now
also covers one-/two-required-board roots; control 43 has a one-Move escape.

Royal threat enumeration now prefilters the attacker/King cross-product with
the existing exact integer geometry predicate. It pre-extracts King coordinates
and leaves the canonical path check and threat order intact. Differential tests
compare full enumeration with the previous unfiltered predicate on both colors
and real/virtual boards. No budget, legality, scoring, or recovery is relaxed.
The full suite passes: 505 tests, 2 skipped, one existing telemetry warning.
Fixed seeds 51/53/55 pass with zero planning failures/recoveries in
33.469 / 9.891 / 11.750 seconds. Control 43 passes (69.469 seconds); control
42 has one baseline failure and one neural recovery (188.688 seconds).
Its Easy20 outcome is recorded in the subsequent pinned-capture follow-up above.

## Active-branch rewind follow-up

Easy20 on `835e4718` completed in 279.125 seconds: 15 wins / 3 draws / 2 losses,
one baseline planning failure, one neural recovery, and one proven terminal
adjudication; illegal/stale/unexpected failures were zero. The counted failure
was game 12 / Action 114, a seven-required-board state. An uncapturable Queen
threat makes advancing one board unsafe, but an active historical branch can
rewind The Present and defer it. A single canonical branch Move was found and
replayed in a separate 0.125-second diagnostic. This is an escape, not a
terminal certificate.

The follow-up prioritizes eligible rewinds from every movable board, including
optional sources, only within the existing one-second depth-one probe. Deep
fallback ordering remains intact, and all unprioritized Moves remain searchable.
Preparation and execution share the original deadline/state/action limits.

Lazy defense ordering is now restricted to roots with at least 17 required
boards, plus a check threat or missing local King. Smaller roots keep MRV.
The earlier broader admission could time out on the 14-board fixture when run
in isolation, despite prior full-suite/CI passes. The revised boundary passes
the 14-/19-/32-board compatibility checks alongside active-rewind and optional-
source tests (16 focused checks passed). Full suite: 497 passed, 2 skipped,
one existing telemetry warning. Fixed seeds 51/53/55 passed with zero planning
failures/recoveries in 32.047 / 10.703 / 12.938 seconds. Controls 42/43 still
have one failure each (42 also has one recovery), in 152.766 / 111.922 seconds.
All five have zero illegal/stale/unexpected failures. Its completed Easy20
result is recorded in the subsequent King-escape follow-up above.

Implementation `835e4718` passed remote
[CI 38119059656](https://github.com/Polarzen/5Dchess/actions/runs/38119059656)
and [training CI 38119061935](https://github.com/Polarzen/5Dchess/actions/runs/38119061935).
Its compact evidence is retained as `followup_v3` in
`planner-validation-20261011.json`; it is not the final rewind candidate.

## Further follow-up: coupled threats, immobile boards, and defense ordering

Two further terminal certificates cover captured failures from the second
Easy20 run. Distinct non-Pawn attackers on the same required successor cannot
both be removed by one advancement when each attacks an immutable King/path.
The game 11 / Action 33 fixture exercises this case, including individually
legal captures that cannot jointly solve the Action.

The game 20 / Action 118 fixture is stalemate: a required board has no current
incoming or outgoing legal move, and its remaining Pawns/Rooks cannot reach
future new lanes. The same activity/allocation guard prevents deferring that
board. New acting-color sources cannot appear; old-board capture/arrival paths
remain immutable. The mobility certificate conservatively declines other
piece types, clear Rook rays toward new lanes, activity escapes, available
optional incoming moves, or interrupted generation.

For complex Actions with more than two required boards, a root check threat
or absence of a board-local King admits defense ordering. It prioritizes
captures of virtual attackers and moves of threatened Kings, then boards
without a King and Pawn moves. Legal move lists are generated lazily per
visited board. All required/optional moves remain searchable; virtual threats
are ordering evidence, not terminal proofs. Ordinary multi-board roots retain
MRV, the two-board completion path is unchanged, and the strategy resets for
each search. The 19-required-board game 1 fixture now yields complete candidates
that replay canonically under the existing 5/1024/24/32 budget.

Focused checks for the combined follow-up passed: 61 tests, including captured
candidate replay, strategy reset, late-preparation rejection, proof boundaries,
state/depth/time budgets, and ordinary MRV behavior. Full suite: 494 passed,
2 skipped, one existing telemetry warning. Fixed seeds 51/53/55 again have zero
planning failures and recoveries (23.343 / 41.110 / 8.860 seconds). Fresh Easy20
is still required before changing the acceptance decision.

Forensic attribution of the prior Easy20 was also checked: its first counted
failure was game 11 / Action 33, followed by game 20 / Action 118. Game 1 was
recovered, and game 3 was adjudicated terminal. With both new root certificates
disabled, the original recovery search still found no witness for games 11/20
before its 4096-state / 15-second limits; those bounded results are unknown,
not the proof. Game 3 exhaustively completed with no Action in 897 states.

## 2026-10-11 follow-up: immutable direct threats and legal captures

The required-board certificate now checks canonical capture legality, including
board-local King safety. While a capture source and its required target remain
playable, their occupancy and local safety cannot change. Capture rays between
original boards lie inside existing lane extrema, whereas the certificate's
allocation guard places new lanes outside those extrema. New branches therefore
cannot fill a missing capture-path board. All optional sources remain included.

A separate certificate prunes already-materialized direct royal threats at
each search node. The opponent-phase attacker, King and clear path cannot be
changed by the actor's remaining moves. This predicate deliberately excludes
virtual-pass threats and does not confuse an unadvanced Present with an
irreversible attack. Both proofs honor interruption; timeout remains unknown.

Saved Easy20 failures at games 7 and 16 are now proven terminal in one explored
state. Game 11 has complete defenses; the planner finds 24 candidates and all
24 replay through canonical application. These three states are retained as
small compressed regression fixtures. The 26-timeline game 1 state remains
unresolved within five seconds. Experimental capture/spatial ordering and lazy
MRV preparation did not resolve it and are not included in production.

The local fixed-seed gate was rerun with the unchanged model and 5/1024/24/32
budget: seeds 51, 53, and 55 each have zero planning failures and recoveries,
and zero illegal/stale/unexpected failures. Their elapsed times were 24.250,
7.266, and 8.969 seconds.

Validation for this follow-up: 482 passed, 2 skipped, with one existing planner
telemetry warning. This includes exact exhaustive toy comparisons, real optional
capture escapes, pinned and missing-path defenses, and late-proof rejection.

Implementation `3ab86203` passed fresh remote
[CI 38115887660](https://github.com/Polarzen/5Dchess/actions/runs/38115887660)
and [training CI 38115890180](https://github.com/Polarzen/5Dchess/actions/runs/38115890180).
Fresh local Easy20 used the same model, alternating colors, seed 42, max 120
Actions/game, and unchanged explicit budget. It completed in 361.203 seconds:
15 wins / 3 draws / 2 losses; two baseline planning failures, one baseline
recovery, zero neural planning failures/recoveries, zero illegal/stale/unexpected
failures, and one proven terminal adjudication. W/D/L is still contaminated by
planning failures and is not a model-quality PASS. New pre-recovery snapshots
were captured at games 1/3/11/20, Actions 67/37/33/118 respectively; a snapshot
alone is not proof that Arena counted a failure, because adjudication and
recovery happen afterwards. Compact evidence is in the `followup` object of
`planner-validation-20261011.json`.

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

Implementation commit `38ad0da6` passed fresh remote
[CI 38114254595](https://github.com/Polarzen/5Dchess/actions/runs/38114254595)
and [training CI 38114257887](https://github.com/Polarzen/5Dchess/actions/runs/38114257887).
The stacked [Draft PR #25](https://github.com/Polarzen/5Dchess/pull/25) targets
`feat/local-ai-training-v2`; PR #24 remains Draft, unmerged, with auto-merge off.

Easy20 completed locally in 486.469 seconds using that same implementation,
the verified Stage 1 model, alternating neural colors, seed 42, max 120 Actions
per game, and explicit 5/1024/24/32 limits. Results: 13 wins, 3 draws, 4 losses;
four planning failures (one neural, three baseline); zero planner recoveries;
zero illegal, stale, or unexpected failures; one proven terminal adjudication.
Planning failures contaminate W/D/L, so this is **not** a model-quality PASS.
Compact checked evidence is in `planner-validation-20261011.json`. The five
pre-recovery failure snapshots are retained locally for further diagnosis.

Workflow changes adding the new proof path trigger and explicit Arena state
budget were saved as a local patch rather than pushed: the current Git OAuth
credential lacks `workflow` scope. The existing Arena workflow still defaults
to the CLI's 256 states, so it must not be represented as the exact 1024-state
acceptance run. No model weights or temporary diagnostics were committed.

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

The requested local fixed-seed and Easy20 zero-failure gates are complete.
The next reliability work is to eliminate the remaining recovery dependency
and resolve control 42 under the same model and 5/1024/24/32 limits.
Remote fixed-seed execution additionally needs restoration of the expired
checkpoint artifact; local results must not be presented as a remote PASS.
Medium/Hard and large self-play stay blocked until wider Arena reliability is
established, including the remaining control failures.

Temporary profiling and trace files are diagnostic only. Root may remove them
after preserving compact evidence. The bounded local acceptance phase is
complete; wider reliability, remote reproduction, and merge readiness remain open.
