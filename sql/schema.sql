-- 5D Chess 数据库建表脚本
-- MySQL 8.0+

CREATE DATABASE IF NOT EXISTS chess_5d
    CHARACTER SET utf8mb4
    COLLATE utf8mb4_unicode_ci;

USE chess_5d;

-- ============================================
-- 游戏记录表
-- ============================================
CREATE TABLE IF NOT EXISTS games (
    game_id         INT AUTO_INCREMENT PRIMARY KEY,
    mode            ENUM('pvp', 'pve', 'replay') NOT NULL,
    player_white    VARCHAR(64) NOT NULL DEFAULT 'Player1',
    player_black    VARCHAR(64) NOT NULL DEFAULT 'Player2',
    ai_difficulty   ENUM('easy', 'medium', 'hard') NULL,
    result          ENUM('white_win', 'black_win', 'draw', 'ongoing') NOT NULL DEFAULT 'ongoing',
    start_time      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    end_time        DATETIME NULL,
    total_moves     INT NOT NULL DEFAULT 0,
    total_timelines INT NOT NULL DEFAULT 1,
    INDEX idx_mode (mode),
    INDEX idx_result (result),
    INDEX idx_start_time (start_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ============================================
-- 时间线表
-- ============================================
CREATE TABLE IF NOT EXISTS timelines (
    timeline_id     INT AUTO_INCREMENT PRIMARY KEY,
    game_id         INT NOT NULL,
    parent_id       INT NULL,
    branch_move_id  INT NULL,
    branch_turn     INT NULL,
    created_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (game_id) REFERENCES games(game_id) ON DELETE CASCADE,
    FOREIGN KEY (parent_id) REFERENCES timelines(timeline_id) ON DELETE SET NULL,
    INDEX idx_game_id (game_id),
    INDEX idx_parent_id (parent_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ============================================
-- 走子记录表
-- ============================================
CREATE TABLE IF NOT EXISTS moves (
    move_id             INT AUTO_INCREMENT PRIMARY KEY,
    game_id             INT NOT NULL,
    timeline_id         INT NOT NULL,
    turn_number         INT NOT NULL,
    piece_type          ENUM('K', 'Q', 'R', 'B', 'N', 'P') NOT NULL,
    piece_color         ENUM('white', 'black') NOT NULL,
    from_timeline_id    INT NOT NULL,
    from_x              TINYINT NOT NULL,
    from_y              TINYINT NOT NULL,
    from_time           INT NOT NULL,
    to_timeline_id      INT NOT NULL,
    to_x                TINYINT NOT NULL,
    to_y                TINYINT NOT NULL,
    to_time             INT NOT NULL,
    is_branching        BOOLEAN NOT NULL DEFAULT FALSE,
    new_timeline_id     INT NULL,
    notation            VARCHAR(128) NOT NULL DEFAULT '',
    created_at          DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (game_id) REFERENCES games(game_id) ON DELETE CASCADE,
    FOREIGN KEY (timeline_id) REFERENCES timelines(timeline_id) ON DELETE CASCADE,
    FOREIGN KEY (new_timeline_id) REFERENCES timelines(timeline_id) ON DELETE SET NULL,
    INDEX idx_game_id (game_id),
    INDEX idx_timeline_id (timeline_id),
    INDEX idx_turn_number (turn_number),
    INDEX idx_piece_color (piece_color)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ============================================
-- 棋盘快照表
-- ============================================
CREATE TABLE IF NOT EXISTS positions (
    position_id     INT AUTO_INCREMENT PRIMARY KEY,
    timeline_id     INT NOT NULL,
    turn_number     INT NOT NULL,
    time_point      INT NOT NULL,
    board_fen       VARCHAR(256) NOT NULL DEFAULT '',
    board_json      JSON NOT NULL,
    active_color    ENUM('white', 'black') NOT NULL DEFAULT 'white',
    is_check        BOOLEAN NOT NULL DEFAULT FALSE,
    is_checkmate    BOOLEAN NOT NULL DEFAULT FALSE,
    FOREIGN KEY (timeline_id) REFERENCES timelines(timeline_id) ON DELETE CASCADE,
    INDEX idx_timeline_id (timeline_id),
    INDEX idx_time_point (time_point)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ============================================
-- 对局统计表
-- ============================================
CREATE TABLE IF NOT EXISTS game_stats (
    stat_id             INT AUTO_INCREMENT PRIMARY KEY,
    game_id             INT NOT NULL UNIQUE,
    avg_branch_depth    FLOAT NOT NULL DEFAULT 0,
    max_timelines       INT NOT NULL DEFAULT 1,
    white_time_travels  INT NOT NULL DEFAULT 0,
    black_time_travels  INT NOT NULL DEFAULT 0,
    FOREIGN KEY (game_id) REFERENCES games(game_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ============================================
-- 开局库表
-- ============================================
CREATE TABLE IF NOT EXISTS openings (
    opening_id      INT AUTO_INCREMENT PRIMARY KEY,
    name            VARCHAR(128) NOT NULL,
    moves_sequence  JSON NOT NULL,
    win_rate_white  FLOAT NOT NULL DEFAULT 0.5,
    total_games     INT NOT NULL DEFAULT 0,
    created_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_name (name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 外键约束补充（解决循环引用）
ALTER TABLE timelines
    ADD CONSTRAINT fk_branch_move
    FOREIGN KEY (branch_move_id) REFERENCES moves(move_id) ON DELETE SET NULL;