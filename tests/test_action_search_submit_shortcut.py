"""Regression coverage for semantics-preserving ActionSearch submit shortcuts."""

from src.engine import ActionRules, ActionSearch, FiveDEngine


def test_action_search_skips_submit_predicate_while_required_boards_remain(monkeypatch):
    engine = FiveDEngine()
    action = engine._ensure_current_action()
    assert ActionRules.required_boards(action, engine.timeline_manager.timelines)

    original_can_submit = ActionRules.can_submit
    submit_checks = 0

    def guarded_can_submit(current_action, timelines):
        nonlocal submit_checks
        # ActionRules.can_submit is structurally false while any Present board
        # remains required. Calling it there can only waste a royal-safety scan.
        assert not ActionRules.required_boards(current_action, timelines)
        submit_checks += 1
        return original_can_submit(current_action, timelines)

    monkeypatch.setattr(ActionRules, "can_submit", guarded_can_submit)

    result = ActionSearch(
        max_states=64,
        max_depth=32,
        max_seconds=None,
    ).find_legal_action(engine)

    assert result.has_legal_action
    assert result.witness
    assert submit_checks >= 1
