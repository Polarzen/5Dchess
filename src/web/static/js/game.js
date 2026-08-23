/**
 * 5D Chess - 前端逻辑
 */

// ============================================================
// 全局状态
// ============================================================
let gameState = null;
let selectedSquare = null;      // [x, y] | null
let validTargets = [];          // [{x, y, is_branching, ...}, ...]
let mode = null;
let pieceSymbols = {
    'K': '♔', 'Q': '♕', 'R': '♖', 'B': '♗', 'N': '♘', 'P': '♙',
    'k': '♚', 'q': '♛', 'r': '♜', 'b': '♝', 'n': '♞', 'p': '♟',
};

// ============================================================
// API 调用
// ============================================================

async function api(path, method = 'GET', body = null) {
    try {
        const opts = { method, headers: { 'Content-Type': 'application/json' } };
        if (body) opts.body = JSON.stringify(body);
        const res = await fetch(path, opts);
        return await res.json();
    } catch (e) {
        console.error('API error:', e);
        return { error: e.message };
    }
}

// ============================================================
// 游戏控制
// ============================================================

async function startGame(m, difficulty = 'medium') {
    mode = m;
    const result = await api('/api/game/start', 'POST', { mode: m, difficulty, player_color: 'white' });
    if (result.error) {
        alert('启动失败: ' + result.error);
        return;
    }
    gameState = result;
    selectedSquare = null;
    validTargets = [];
    switchToScreen('game-screen');
    updateAll();
}

async function backToMenu() {
    switchToScreen('menu-screen');
    mode = null;
    gameState = null;
}

async function refreshState() {
    const result = await api('/api/game/state');
    if (!result.error) {
        gameState = result;
        updateAll();
    }
}

async function clickSquare(x, y) {
    if (!gameState || mode === 'replay') return;

    if (mode === 'pvp') {
        // PvP: 两步操作
        if (selectedSquare === null) {
            // 选择棋子
            const result = await api('/api/game/select_square', 'POST', { x, y });
            gameState = result;
            if (!result.error && result.action === 'selected') {
                selectedSquare = [x, y];
                validTargets = result.valid_moves || [];
            }
            updateBoard();
        } else {
            // 尝试走子
            const result = await api('/api/game/select_square', 'POST', { x, y });
            gameState = result;
            if (!result.error && result.action === 'moved' && result.success) {
                selectedSquare = null;
                validTargets = [];
                updateAll();
            } else if (!result.error && result.action === 'selected') {
                // 重新选择
                selectedSquare = [x, y];
                validTargets = result.valid_moves || [];
                updateBoard();
            } else {
                // 无效走子，取消选择
                selectedSquare = null;
                validTargets = [];
                updateBoard();
            }
        }
    } else if (mode === 'pve') {
        // PvE: 直接走子
        if (selectedSquare === null) {
            // 选择己方棋子
            const board = gameState.board;
            const ch = board[y][x];
            if (ch && isWhitePiece(ch)) {
                selectedSquare = [x, y];
                // 过滤合法走子
                validTargets = (gameState.legal_moves || [])
                    .filter(m => m.from[0] === x && m.from[1] === y)
                    .map(m => ({ x: m.to[0], y: m.to[1], is_branching: m.is_branching }));
                updateBoard();
            }
        } else {
            // 尝试走子
            const result = await api('/api/game/move', 'POST', {
                from: selectedSquare, to: [x, y]
            });
            if (result.success) {
                gameState = result;
                selectedSquare = null;
                validTargets = [];
                updateAll();

                // 如果游戏未结束，请求AI走子
                if (gameState.game_state === 'PLAYING' && gameState.turn === 'black') {
                    setTimeout(async () => {
                        document.getElementById('game-info').textContent = 'AI 思考中...';
                        const aiResult = await api('/api/game/ai_move', 'POST');
                        if (aiResult.success) {
                            gameState = aiResult;
                            updateAll();
                        }
                    }, 300);
                }
            } else {
                selectedSquare = null;
                validTargets = [];
                updateBoard();
            }
        }
    }
}

// ============================================================
// Replay 控制
// ============================================================

async function replayAction(action) {
    const result = await api('/api/replay/step', 'POST', { action });
    if (!result.error) {
        gameState = result;
        updateAll();
    }
}

async function replayJump() {
    const idx = parseInt(prompt('跳转到步数:', '0'));
    if (!isNaN(idx)) {
        const result = await api('/api/replay/step', 'POST', { action: 'jump', index: idx });
        if (!result.error) {
            gameState = result;
            updateAll();
        }
    }
}

async function replayLoadFile() {
    const filepath = prompt('输入棋谱文件路径 (.5dpgn):');
    if (filepath) {
        const result = await api('/api/replay/load', 'POST', { filepath });
        if (!result.error) {
            gameState = result;
            updateAll();
        } else {
            alert('加载失败: ' + result.error);
        }
    }
}

async function selectTimeline(tlId) {
    if (mode === 'replay') {
        await api('/api/replay/timeline', 'POST', { timeline_id: tlId });
        await refreshState();
    }
}

// ============================================================
// 界面更新
// ============================================================

function updateAll() {
    updateBoard();
    updateTimelineTree();
    updateControls();
    updateInfo();
    updateMoveHistory();
    updateGameInfo();
    checkGameOver();
}

function updateBoard() {
    const container = document.getElementById('board');
    container.innerHTML = '';

    if (!gameState || !gameState.board) return;

    const board = gameState.board;
    // 获取当前查看的棋盘 (Replay模式下可能不同)
    let displayBoard = board;
    if (mode === 'replay' && gameState.overview) {
        const tlId = String(gameState.selected_timeline_id || gameState.active_timeline_id);
        if (gameState.overview[tlId]) {
            displayBoard = gameState.overview[tlId].board;
        }
    }

    for (let row = 0; row < 8; row++) {
        for (let col = 0; col < 8; col++) {
            const cell = document.createElement('div');
            cell.className = 'cell ' + ((row + col) % 2 === 0 ? 'light' : 'dark');
            cell.dataset.x = col;
            cell.dataset.y = row;
            cell.onclick = () => clickSquare(col, row);

            // 棋子
            const ch = displayBoard[row][col];
            if (ch) {
                const symbol = pieceSymbols[ch] || ch;
                cell.textContent = symbol;
                cell.style.color = ch === ch.toUpperCase() ? '#fff' : '#222';
                cell.style.textShadow = ch === ch.toUpperCase()
                    ? '1px 1px 2px #000' : '1px 1px 2px #fff';
            }

            // 选中高亮
            if (selectedSquare && selectedSquare[0] === col && selectedSquare[1] === row) {
                cell.classList.add('selected');
            }

            // 合法走子目标
            for (const t of validTargets) {
                if (t.x === col && t.y === row) {
                    cell.classList.add('valid-move');
                    if (t.is_branching) cell.classList.add('branching');
                }
            }

            container.appendChild(cell);
        }
    }
}

function updateTimelineTree() {
    const container = document.getElementById('timeline-tree');
    container.innerHTML = '';

    if (!gameState || !gameState.timelines) {
        container.innerHTML = '<span style="color:#999">(无分支)</span>';
        return;
    }

    const timelines = gameState.timelines;
    const activeId = gameState.active_timeline_id;
    const selectedId = gameState.selected_timeline_id || activeId;

    // 按ID排序
    timelines.sort((a, b) => a.id - b.id);

    for (const tl of timelines) {
        const node = document.createElement('span');
        node.className = 'timeline-node';
        if (tl.id === activeId) node.classList.add('active');
        if (tl.id === selectedId) node.classList.add('selected');
        if (!tl.is_active) node.classList.add('inactive');

        // 更清晰的标签：主线 T0，分支 T1←T0
        let label;
        if (tl.parent_id === null) {
            label = `主线 T${tl.id}`;
        } else {
            label = `分支 T${tl.id}←T${tl.parent_id}`;
        }
        label += ` [t=${tl.latest_time}]`;
        node.textContent = label;
        node.title = `时间线 ${tl.id}: ${tl.parent_id === null ? '主线' : '从T' + tl.parent_id + '分支'}, 最新时间点 t=${tl.latest_time}`;

        if (mode === 'replay') {
            node.onclick = () => selectTimeline(tl.id);
            node.style.cursor = 'pointer';
        }
        container.appendChild(node);
    }
}

function updateControls() {
    const container = document.getElementById('controls');
    container.innerHTML = '';

    if (!gameState) return;

    if (mode === 'replay') {
        container.innerHTML = `
            <button class="ctrl-btn" onclick="replayAction('start')">⏮ 开头</button>
            <button class="ctrl-btn" onclick="replayAction('backward')">◀ 后退</button>
            <button class="ctrl-btn" onclick="replayAction('toggle')">▶/⏸ 播放</button>
            <button class="ctrl-btn" onclick="replayAction('forward')">前进 ▶</button>
            <button class="ctrl-btn" onclick="replayAction('end')">末尾 ⏭</button>
            <button class="ctrl-btn" onclick="replayJump()">跳转</button>
            <button class="ctrl-btn" onclick="replayLoadFile()">加载棋谱</button>
        `;
    } else if (mode === 'pvp' || mode === 'pve') {
        container.innerHTML = `
            <button class="ctrl-btn" onclick="backToMenu()">结束游戏</button>
            <button class="ctrl-btn" onclick="refreshState()">刷新</button>
        `;
    }
}

function updateInfo() {
    const panel = document.getElementById('info-panel');
    if (!gameState) { panel.innerHTML = ''; return; }

    const summary = gameState.summary || {};
    const lines = [
        `模式: ${modeLabel(mode)}`,
        `回合: ${gameState.move_counter || 0}`,
        `当前方: ${gameState.turn || '?'}`,
        `时间线: ${summary.total_timelines || 1}`,
        `活跃: ${summary.active_timelines || 1}`,
        `状态: ${gameState.game_state || '?'}`,
        `当前: T${gameState.active_timeline_id}`,
    ];

    if (mode === 'replay') {
        lines.push(`回放: ${gameState.current_index || 0}/${gameState.total_moves || 0}`);
        if (gameState.is_playing) lines.push('▶ 自动播放中');
    }

    panel.innerHTML = lines.join('<br>');
}

function updateGameInfo() {
    const el = document.getElementById('game-info');
    if (!gameState) {
        el.textContent = '';
        return;
    }
    el.textContent = `${modeLabel(mode)} | T${gameState.active_timeline_id} | ${gameState.turn}方走棋 | 第${gameState.move_counter}步`;
}

function updateMoveHistory() {
    const container = document.getElementById('move-history');
    if (!gameState || !gameState.move_history) {
        container.innerHTML = '(无)';
        return;
    }

    const history = gameState.move_history;
    let html = '';
    for (let i = 0; i < history.length; i++) {
        const num = Math.floor(i / 2) + 1;
        if (i % 2 === 0) html += `<span style="color:#888">${num}.</span> `;
        html += `${history[i]}`;
        if (i % 2 === 1) html += '\n';
        else html += ' ';
    }
    container.innerHTML = html || '(无)';
    container.scrollTop = container.scrollHeight;
}

function checkGameOver() {
    if (!gameState) return;
    const state = gameState.game_state;
    if (state === 'CHECKMATE' || state === 'STALEMATE' || state === 'DRAW') {
        const overlay = document.getElementById('game-over-overlay');
        if (!overlay) {
            const div = document.createElement('div');
            div.id = 'game-over-overlay';
            div.className = 'show';
            div.innerHTML = `
                <div id="game-over-dialog">
                    <h2>游戏结束</h2>
                    <p class="result-text">${resultLabel(state)}</p>
                    <button class="ctrl-btn" onclick="backToMenu()">返回菜单</button>
                </div>
            `;
            document.body.appendChild(div);
        } else {
            overlay.classList.add('show');
        }
    }
}

// ============================================================
// 工具函数
// ============================================================

function switchToScreen(id) {
    document.querySelectorAll('.screen').forEach(s => s.classList.remove('active'));
    const el = document.getElementById(id);
    if (el) el.classList.add('active');

    // 移除游戏结束弹窗
    const overlay = document.getElementById('game-over-overlay');
    if (overlay) overlay.remove();
}

function isWhitePiece(ch) {
    return ch && ch === ch.toUpperCase() && ch !== ch.toLowerCase();
}

function modeLabel(m) {
    const labels = { pvp: 'PvP 真人对弈', pve: 'PvE 人机', replay: 'Replay 回放' };
    return labels[m] || m || '?';
}

function resultLabel(state) {
    const labels = {
        CHECKMATE: '将杀！',
        STALEMATE: '逼和',
        DRAW: '和棋',
    };
    return labels[state] || state;
}

// ============================================================
// 键盘快捷键
// ============================================================

document.addEventListener('keydown', (e) => {
    if (mode === 'replay') {
        if (e.key === 'ArrowLeft') replayAction('backward');
        if (e.key === 'ArrowRight') replayAction('forward');
        if (e.key === ' ') { e.preventDefault(); replayAction('toggle'); }
        if (e.key === 'Home') replayAction('start');
        if (e.key === 'End') replayAction('end');
    }
    if (e.key === 'Escape') backToMenu();
    if (e.key === 'r' && e.ctrlKey) { e.preventDefault(); refreshState(); }
});