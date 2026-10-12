"""Canonical terminal outcomes must survive Action-search horizon/budget cuts."""
import time

import pytest

from src.ai import (AlphaBetaAI, HardAI, ActionPlanner, ActionSearchBudget,
                    ActionSearchResult, apply_action_plan, engine_state_signature)
from src.engine import FiveDEngine
from src.engine.outcome_rules import OutcomeRules
from src.utils.constants import ChessColor, GameState
from tests.test_action_plan_outcome_efficiency import _install_position, _make_position, _specific_plan


def tactical_position(color=ChessColor.WHITE, mirrored=False):
    pieces = {(7, 0): 'k', (6, 2): 'Q', (5, 2): 'K'}
    if color == ChessColor.BLACK:
        # A distinct mating net whose winning move fits both default candidate caps.
        pieces = {(7, 7): 'K', (5, 4): 'q', (5, 6): 'k'}
    if mirrored:
        pieces = {(7-x, y): piece for (x, y), piece in pieces.items()}
    engine = FiveDEngine()
    _install_position(engine, _make_position(0, int(color == ChessColor.BLACK), pieces), color)
    return engine


@pytest.mark.parametrize('ai_type', [AlphaBetaAI, HardAI])
@pytest.mark.parametrize('color', list(ChessColor))
@pytest.mark.parametrize('mirrored', [False, True])
@pytest.mark.parametrize('depth', [1, 2])
def test_take_available_mate_instead_of_stalemate(ai_type, color, mirrored, depth):
    engine = tactical_position(color, mirrored)
    before = engine_state_signature(engine)
    ai = ai_type(color, search_depth=depth)
    plan = ai.plan_action(engine)
    assert engine_state_signature(engine) == before
    assert apply_action_plan(engine, plan)
    assert engine.game_state == GameState.CHECKMATE
    assert engine.current_turn_color == color.opposite()
    assert plan.score == 100000.0


@pytest.mark.parametrize('kind,coords', [
    (GameState.CHECKMATE, (6, 2, 6, 1)),
    (GameState.STALEMATE, (5, 2, 4, 1)),
])
@pytest.mark.parametrize('perspective', list(ChessColor))
@pytest.mark.parametrize('depth,expired', [(0, False), (2, True)])
def test_canonical_terminal_precedes_horizon_and_deadline(monkeypatch, kind, coords, perspective, depth, expired):
    engine = tactical_position()
    apply_action_plan(engine, _specific_plan(engine, coords))
    assert engine.game_state == kind
    ai = AlphaBetaAI(perspective)
    ai._start_time = time.monotonic() - (10 if expired else 0)

    def unexpected(*args, **kwargs):
        pytest.fail('Known outcomes require neither heuristic scoring nor further search')

    monkeypatch.setattr(ai.evaluator, 'evaluate_engine', unexpected)
    monkeypatch.setattr(ai, '_search_candidates', unexpected)
    expected = 0 if kind == GameState.STALEMATE else (100000 if perspective == ChessColor.WHITE else -100000)
    assert ai._search_state(engine, depth, float('-inf'), float('inf')) == expected


@pytest.mark.parametrize('coords,expected', [((6, 2, 6, 1), 100000), ((5, 2, 4, 1), 0)])
def test_complete_no_action_proof_is_classified_without_research(monkeypatch, coords, expected):
    engine = tactical_position()
    apply_action_plan(engine, _specific_plan(engine, coords))
    engine.game_state = GameState.PLAYING  # Outcome search may previously have been inconclusive.
    before = engine_state_signature(engine)
    ai = AlphaBetaAI(ChessColor.WHITE)
    ai._start_time = time.monotonic()
    result = ai._search_candidates(engine)
    assert not result.candidates and result.termination_reason is None
    monkeypatch.setattr(ai, '_search_candidates', lambda *a, **kw: result)
    monkeypatch.setattr(OutcomeRules, 'evaluate', lambda *a, **kw: pytest.fail('Proof must be reused'))
    assert ai._search_state(engine, 1, float('-inf'), float('inf')) == expected
    assert engine_state_signature(engine) == before


@pytest.mark.parametrize('reason', ['time_budget', 'state_budget', 'move_depth_budget', 'game_not_playing'])
def test_incomplete_no_candidate_search_never_means_mate(monkeypatch, reason):
    engine = tactical_position()
    ai = AlphaBetaAI(ChessColor.WHITE)
    ai._start_time = time.monotonic()
    monkeypatch.setattr(ai, '_search_candidates', lambda *a, **kw: ActionSearchResult((), 1, reason))
    monkeypatch.setattr(ai.evaluator, 'evaluate_engine', lambda *a: 17.0)
    monkeypatch.setattr(OutcomeRules, 'classify_proven_no_legal_action', lambda *a, **kw: pytest.fail('No proof'))
    assert ai._search_state(engine, 1, float('-inf'), float('inf')) == 17.0


def test_explicit_draw_is_neutral():
    engine = tactical_position()
    engine.game_state = GameState.DRAW
    assert AlphaBetaAI(ChessColor.WHITE)._search_state(engine, 0, -float('inf'), float('inf')) == 0.0


def defense_position(mirrored=False):
    # Black's tempting Rxa2 abandons the seventh rank and permits Qg7 mate.
    pieces = {(7, 0): 'k', (0, 1): 'r', (6, 2): 'Q', (5, 2): 'K', (0, 6): 'P'}
    if mirrored:
        pieces = {(7-x, y): piece for (x, y), piece in pieces.items()}
    engine = FiveDEngine()
    _install_position(engine, _make_position(0, 1, pieces), ChessColor.BLACK)
    return engine


@pytest.mark.parametrize('mirrored', [False, True])
def test_defend_against_mate_at_two_action_horizon(mirrored):
    engine = defense_position(mirrored)
    ai = AlphaBetaAI(ChessColor.BLACK)
    plan = ai.plan_action(engine)
    apply_action_plan(engine, plan)
    assert engine.game_state == GameState.PLAYING
    # Exhaust the actual opponent Action set, independently of its 16-candidate
    # planning cap, to prove the selected defense prevents immediate mate.
    result = ActionPlanner(ActionSearchBudget(None, None, 8, None)).search(engine)
    assert result.candidates and result.termination_reason is None
    assert all(ai._apply_candidate(engine, specs).game_state != GameState.CHECKMATE
               for specs in result.candidates)
