-- 5D Chess canonical replay/storage schema
-- MySQL 8.0+

CREATE DATABASE IF NOT EXISTS chess_5d
    CHARACTER SET utf8mb4
    COLLATE utf8mb4_unicode_ci;

USE chess_5d;

CREATE TABLE IF NOT EXISTS games (
    game_id         INT AUTO_INCREMENT PRIMARY KEY,
    mode            ENUM('pvp', 'pve', 'replay') NOT NULL,
    player_white    VARCHAR(64) NOT NULL DEFAULT 'Player1',
    player_black    VARCHAR(64) NOT NULL DEFAULT 'Player2',
    ai_difficulty   ENUM('easy', 'medium', 'hard') NULL,
    result          VARCHAR(32) NOT NULL DEFAULT 'ongoing',
    start_time      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    end_time        DATETIME NULL,
    total_moves     INT NOT NULL DEFAULT 0,
    total_actions   INT NOT NULL DEFAULT 0,
    total_timelines INT NOT NULL DEFAULT 1,
    archive_version INT NOT NULL DEFAULT 2,
    INDEX idx_mode (mode),
    INDEX idx_result (result),
    INDEX idx_start_time (start_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- timeline_row_id is a database identity only.
-- lane_id is the canonical signed L coordinate and may be negative.
CREATE TABLE IF NOT EXISTS timelines (
    timeline_row_id INT AUTO_INCREMENT PRIMARY KEY,
    game_id         INT NOT NULL,
    lane_id         INT NOT NULL,
    parent_lane_id  INT NULL,
    branch_move_id  INT NULL,
    branch_turn     INT NULL,
    owner           ENUM('white', 'black') NULL,
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (game_id) REFERENCES games(game_id) ON DELETE CASCADE,
    UNIQUE KEY uq_game_lane (game_id, lane_id),
    INDEX idx_parent_lane (game_id, parent_lane_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS actions (
    action_id              INT AUTO_INCREMENT PRIMARY KEY,
    game_id                INT NOT NULL,
    action_index           INT NOT NULL,
    color                  ENUM('white', 'black') NOT NULL,
    starting_present_json  JSON NULL,
    submitted              BOOLEAN NOT NULL DEFAULT FALSE,
    move_count             INT NOT NULL DEFAULT 0,
    created_at             DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (game_id) REFERENCES games(game_id) ON DELETE CASCADE,
    UNIQUE KEY uq_game_action (game_id, action_index),
    INDEX idx_action_color (color)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS moves (
    move_id                 INT AUTO_INCREMENT PRIMARY KEY,
    game_id                 INT NOT NULL,
    action_index            INT NOT NULL,
    move_index              INT NOT NULL,
    piece_type              ENUM('K', 'Q', 'R', 'B', 'N', 'P') NOT NULL,
    piece_color             ENUM('white', 'black') NOT NULL,

    source_timeline         INT NOT NULL,
    source_turn             INT NOT NULL,
    source_side             ENUM('white', 'black') NOT NULL,
    source_x                TINYINT NOT NULL,
    source_y                TINYINT NOT NULL,

    destination_timeline    INT NOT NULL,
    destination_turn        INT NOT NULL,
    destination_side        ENUM('white', 'black') NOT NULL,
    destination_x           TINYINT NOT NULL,
    destination_y           TINYINT NOT NULL,

    -- Compatibility/debug half-move representation. Canonical T+side above is primary.
    from_time               INT NOT NULL,
    to_time                 INT NOT NULL,

    is_branching            BOOLEAN NOT NULL DEFAULT FALSE,
    is_cross_timeline       BOOLEAN NOT NULL DEFAULT FALSE,
    is_castling             BOOLEAN NOT NULL DEFAULT FALSE,
    is_en_passant           BOOLEAN NOT NULL DEFAULT FALSE,
    created_timeline        INT NULL,
    captured_type           ENUM('K', 'Q', 'R', 'B', 'N', 'P') NULL,
    captured_color          ENUM('white', 'black') NULL,
    promotion               ENUM('Q') NULL,
    notation                VARCHAR(192) NOT NULL DEFAULT '',
    created_at              DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (game_id) REFERENCES games(game_id) ON DELETE CASCADE,
    FOREIGN KEY (game_id, action_index)
        REFERENCES actions(game_id, action_index) ON DELETE CASCADE,
    UNIQUE KEY uq_action_move (game_id, action_index, move_index),
    INDEX idx_source_board (game_id, source_timeline, source_turn, source_side),
    INDEX idx_destination_board (
        game_id, destination_timeline, destination_turn, destination_side
    ),
    INDEX idx_piece_color (piece_color)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS positions (
    position_id     INT AUTO_INCREMENT PRIMARY KEY,
    game_id         INT NOT NULL,
    lane_id         INT NOT NULL,
    board_turn      INT NOT NULL,
    board_side      ENUM('white', 'black') NOT NULL,
    time_point      INT NOT NULL,
    board_fen       VARCHAR(256) NOT NULL DEFAULT '',
    board_json      JSON NOT NULL,
    is_playable     BOOLEAN NOT NULL DEFAULT FALSE,
    is_check        BOOLEAN NOT NULL DEFAULT FALSE,
    is_checkmate    BOOLEAN NOT NULL DEFAULT FALSE,
    FOREIGN KEY (game_id) REFERENCES games(game_id) ON DELETE CASCADE,
    UNIQUE KEY uq_position (game_id, lane_id, time_point),
    INDEX idx_board_coord (game_id, lane_id, board_turn, board_side)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS game_stats (
    stat_id             INT AUTO_INCREMENT PRIMARY KEY,
    game_id             INT NOT NULL UNIQUE,
    avg_branch_depth    FLOAT NOT NULL DEFAULT 0,
    max_timelines       INT NOT NULL DEFAULT 1,
    white_time_travels  INT NOT NULL DEFAULT 0,
    black_time_travels  INT NOT NULL DEFAULT 0,
    FOREIGN KEY (game_id) REFERENCES games(game_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS openings (
    opening_id      INT AUTO_INCREMENT PRIMARY KEY,
    name            VARCHAR(128) NOT NULL,
    moves_sequence  JSON NOT NULL,
    win_rate_white  FLOAT NOT NULL DEFAULT 0.5,
    total_games     INT NOT NULL DEFAULT 0,
    created_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_name (name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
