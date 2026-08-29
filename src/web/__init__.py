"""5D Chess Web Module"""
from src.web.app import (
    _coord_from_payload,
    _find_exact_legal_move,
    _game_session,
    _move_payload,
    app,
    get_game_state,
    run_server,
)
from src.web.p2p import register_p2p_routes

register_p2p_routes(
    app,
    _game_session,
    get_game_state=get_game_state,
    coord_from_payload=_coord_from_payload,
    find_exact_legal_move=_find_exact_legal_move,
    move_payload=_move_payload,
)
