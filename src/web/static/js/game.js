/** 5D Chess multiverse browser interaction. */

let gameState = null;
let mode = null;
let selectedSource = null;   // { boardKey, x, y }
let legalMoves = [];         // canonical Move payloads
let focusedBoardKey = null;
let boardZoom = 192;
let toastTimer = null;

const pieceSymbols = {
    K: '♔', Q: '♕', R: '♖', B: '♗', N: '♘', P: '♙',
    k: '♚', q: '♛', r: '♜', b: '♝', n: '♞', p: '♟',
};

const SVG_NS = 'http://www.w3.org/2000/svg';

async function api(path, method = 'GET', body = null) {
    const options = { method, headers: { 'Content-Type': 'application/json' } };
    if (body !== null) options.body = JSON.stringify(body);
    try {
        const response = await fetch(path, options);
        const data = await response.json();
        if (!response.ok && !data.error) data.error = `HTTP ${response.status}`;
        return data;
    } catch (error) {
        console.error('API error', error);
        return { error: error.message };
    }
}

// ---------------------------------------------------------------------------
// Session / game flow
// ---------------------------------------------------------------------------

async function startGame(nextMode, difficulty = 'medium') {
    mode = nextMode;
    const result = await api('/api/game/start', 'POST', {
        mode: nextMode,
        difficulty,
        player_color: 'white',
    });
    if (result.error) {
        showToast(`启动失败：${result.error}`, true);
        mode = null;
        return;
    }
    gameState = result;
    clearSelection(false);
    switchToScreen('game-screen');
    updateAll();
    requestAnimationFrame(scrollToCurrent);
}

function backToMenu() {
    gameState = null;
    mode = null;
    clearSelection(false);
    focusedBoardKey = null;
    switchToScreen('menu-screen');
}

async function refreshState() {
    if (!mode) return;
    const result = await api('/api/game/state');
    if (result.error) {
        showToast(result.error, true);
        return;
    }
    gameState = result;
    clearSelection(false);
    updateAll();
}

async function submitAction() {
    if (!gameState || mode === 'replay' || !gameState.action?.can_submit) return;
    const result = await api('/api/game/submit_action', 'POST', {});
    if (result.error) {
        showToast(result.error, true);
        return;
    }
    gameState = result;
    clearSelection(false);
    updateAll();
    showToast('Action 已提交');

    if (mode === 'pve' && shouldRunAI()) {
        setTimeout(runAIAction, 220);
    }
}

function shouldRunAI() {
    return Boolean(
        gameState && mode === 'pve' &&
        gameState.game_state === 'PLAYING' &&
        gameState.player_color &&
        gameState.turn !== gameState.player_color
    );
}

async function runAIAction() {
    if (!shouldRunAI()) return;
    const info = document.getElementById('game-info');
    if (info) info.textContent = 'AI 正在完成 Action…';
    const result = await api('/api/game/ai_move', 'POST', {});
    if (result.error) {
        showToast(`AI：${result.error}`, true);
        await refreshState();
        return;
    }
    gameState = result;
    clearSelection(false);
    updateAll();
}

// ---------------------------------------------------------------------------
// Canonical board interaction
// ---------------------------------------------------------------------------

function findBoard(boardKey) {
    return (gameState?.boards || []).find(board => board.key === boardKey) || null;
}

function pieceColor(ch) {
    if (!ch) return null;
    return ch === ch.toUpperCase() ? 'white' : 'black';
}

function canSelectSource(board, ch) {
    if (!board || !ch || !gameState || gameState.game_state !== 'PLAYING') return false;
    if (mode === 'replay' || !board.is_movable) return false;
    if (pieceColor(ch) !== gameState.turn) return false;
    if (mode === 'pve' && gameState.player_color !== gameState.turn) return false;
    return true;
}

async function handleCellClick(boardKey, x, y) {
    const board = findBoard(boardKey);
    if (!board) return;
    focusBoard(boardKey, false);

    const targetMove = selectedSource
        ? legalMoves.find(move =>
            move.destination.board.key === boardKey &&
            move.destination.x === x && move.destination.y === y
        )
        : null;

    if (targetMove) {
        await executeCanonicalMove(targetMove);
        return;
    }

    const ch = board.board?.[y]?.[x] || '';
    if (canSelectSource(board, ch)) {
        await selectSource(board, x, y);
        return;
    }

    if (selectedSource) {
        clearSelection();
    } else {
        renderInspector();
    }
}

async function selectSource(board, x, y) {
    const result = await api('/api/game/legal_moves_5d', 'POST', {
        board: board.coord,
        x,
        y,
    });
    if (result.error) {
        showToast(result.error, true);
        return;
    }
    if (!result.moves?.length) {
        showToast('该棋子在当前 Action 中没有合法走子');
        clearSelection();
        return;
    }

    selectedSource = { boardKey: board.key, x, y };
    legalMoves = result.moves;
    focusedBoardKey = board.key;
    renderMultiverse();
    renderInspector();
}

async function executeCanonicalMove(move) {
    const result = await api('/api/game/move_5d', 'POST', {
        source: move.source,
        destination: move.destination,
        promotion: move.promotion,
    });
    if (result.error) {
        showToast(result.error, true);
        await refreshState();
        return;
    }

    gameState = result;
    focusedBoardKey = move.destination.board.key;
    clearSelection(false);
    updateAll();
    showToast(move.notation || '走子完成');

    if (shouldRunAI()) setTimeout(runAIAction, 220);
}

function clearSelection(render = true) {
    selectedSource = null;
    legalMoves = [];
    if (render && gameState) {
        renderMultiverse();
        renderInspector();
    }
}

function focusBoard(boardKey, scroll = true) {
    focusedBoardKey = boardKey;
    document.querySelectorAll('.board-card.focused').forEach(el => el.classList.remove('focused'));
    const target = document.querySelector(`.board-card[data-board-key="${cssEscape(boardKey)}"]`);
    if (target) {
        target.classList.add('focused');
        if (scroll) target.scrollIntoView({ behavior: 'smooth', block: 'center', inline: 'center' });
    }
    renderInspector();
}

// ---------------------------------------------------------------------------
// Replay
// ---------------------------------------------------------------------------

async function replayAction(action) {
    if (mode !== 'replay') return;
    const result = await api('/api/replay/step', 'POST', { action });
    if (result.error) return showToast(result.error, true);
    gameState = result;
    clearSelection(false);
    updateAll();
}

async function replayJump() {
    const raw = prompt('跳转到步数：', String(gameState?.current_index || 0));
    if (raw === null) return;
    const index = Number.parseInt(raw, 10);
    if (Number.isNaN(index)) return;
    const result = await api('/api/replay/step', 'POST', { action: 'jump', index });
    if (result.error) return showToast(result.error, true);
    gameState = result;
    updateAll();
}

async function replayLoadFile() {
    const filepath = prompt('输入 .5dpgn 文件路径：');
    if (!filepath) return;
    const result = await api('/api/replay/load', 'POST', { filepath });
    if (result.error) return showToast(result.error, true);
    gameState = result;
    updateAll();
    requestAnimationFrame(scrollToCurrent);
}

// ---------------------------------------------------------------------------
// Rendering
// ---------------------------------------------------------------------------

function updateAll() {
    if (!gameState) return;
    renderTopStatus();
    renderMultiverse();
    renderActionPanel();
    renderInspector();
    renderHistory();
    renderReplayPanel();
    checkGameOver();
}

function renderTopStatus() {
    const info = document.getElementById('game-info');
    const present = gameState.present;
    info.textContent = `${modeLabel(mode)} · 第 ${gameState.move_counter || 0} 个 Move`;

    const status = document.getElementById('top-status');
    status.innerHTML = '';
    const pills = [
        { text: `Turn ${gameState.turn}`, cls: 'emphasis' },
        { text: present ? `Present t${present.time_point} · ${present.side}` : 'Present —', cls: '' },
        { text: `${gameState.summary?.active_timelines ?? 0} active / ${gameState.summary?.total_timelines ?? 0} lanes`, cls: '' },
        { text: gameState.game_state, cls: gameState.game_state === 'PLAYING' ? '' : 'danger' },
    ];
    if (gameState.in_check) pills.push({ text: 'CHECK', cls: 'danger' });
    for (const item of pills) {
        const pill = document.createElement('span');
        pill.className = `status-pill ${item.cls}`.trim();
        pill.textContent = item.text;
        status.appendChild(pill);
    }
}

function renderMultiverse() {
    const container = document.getElementById('timeline-lanes');
    const viewport = document.getElementById('multiverse-viewport');
    const savedLeft = viewport.scrollLeft;
    const savedTop = viewport.scrollTop;
    container.innerHTML = '';

    const boards = gameState.boards || [];
    const timelines = [...(gameState.timelines || [])].sort((a, b) => b.id - a.id);
    if (!boards.length || !timelines.length) {
        container.innerHTML = '<div class="muted">当前没有可显示的棋盘。</div>';
        return;
    }

    const times = boards.map(board => board.coord.time_point);
    const minTime = Math.min(...times);
    const maxTime = Math.max(...times);
    const columnCount = Math.max(1, maxTime - minTime + 1);
    const targetBoardKeys = new Set(legalMoves.map(move => move.destination.board.key));

    for (const timeline of timelines) {
        const lane = document.createElement('section');
        lane.className = `timeline-lane ${timeline.is_active ? 'active' : 'inactive'}`;
        lane.dataset.timelineId = timeline.id;

        const label = document.createElement('div');
        label.className = 'lane-label';
        label.innerHTML = `<strong>${escapeHtml(timeline.name)}</strong><small>${timeline.is_active ? 'ACTIVE' : 'INACTIVE'}${timeline.owner ? ` · ${escapeHtml(timeline.owner)}` : ''}</small>`;
        lane.appendChild(label);

        const track = document.createElement('div');
        track.className = 'lane-track';
        track.style.gridTemplateColumns = `repeat(${columnCount}, var(--board-size))`;

        const laneBoards = boards
            .filter(board => board.coord.timeline === timeline.id)
            .sort((a, b) => a.coord.time_point - b.coord.time_point);
        for (const board of laneBoards) {
            const card = createBoardCard(board, targetBoardKeys);
            card.style.gridColumn = String(board.coord.time_point - minTime + 1);
            track.appendChild(card);
        }

        lane.appendChild(track);
        container.appendChild(lane);
    }

    viewport.scrollLeft = savedLeft;
    viewport.scrollTop = savedTop;
    requestAnimationFrame(drawLinks);
}

function createBoardCard(board, targetBoardKeys) {
    const card = document.createElement('article');
    const classes = ['board-card', board.role];
    if (!board.timeline_active) classes.push('inactive');
    if (board.is_present) classes.push('present');
    if (board.is_required) classes.push('required');
    if (board.is_movable) classes.push('movable');
    if (focusedBoardKey === board.key) classes.push('focused');
    if (targetBoardKeys.has(board.key)) classes.push('target-board');
    card.className = classes.join(' ');
    card.dataset.boardKey = board.key;

    const header = document.createElement('header');
    header.className = 'board-card-header';
    header.onclick = event => {
        event.stopPropagation();
        focusBoard(board.key);
    };
    const laneName = board.coord.timeline === 0 ? 'L0' : `L${board.coord.timeline > 0 ? '+' : ''}${board.coord.timeline}`;
    header.innerHTML = `<span class="board-coord-label">${laneName} · T${board.coord.turn} · ${escapeHtml(board.coord.side)}</span>`;

    const badges = document.createElement('span');
    badges.className = 'board-badges';
    if (board.is_present) badges.appendChild(makeBadge('PRESENT', 'present'));
    if (board.is_required) badges.appendChild(makeBadge('REQ', 'required'));
    if (board.playable && !board.is_required) badges.appendChild(makeBadge('PLAY', 'playable'));
    if (!board.timeline_active) badges.appendChild(makeBadge('OFF', 'inactive'));
    header.appendChild(badges);
    card.appendChild(header);

    const grid = document.createElement('div');
    grid.className = 'mini-board';
    for (let y = 0; y < 8; y++) {
        for (let x = 0; x < 8; x++) {
            const cell = document.createElement('div');
            const ch = board.board?.[y]?.[x] || '';
            cell.className = `mini-cell ${(x + y) % 2 === 0 ? 'light' : 'dark'}`;
            if (ch) {
                cell.textContent = pieceSymbols[ch] || ch;
                cell.classList.add(pieceColor(ch) === 'white' ? 'white-piece' : 'black-piece', 'has-piece');
            }

            if (selectedSource && selectedSource.boardKey === board.key && selectedSource.x === x && selectedSource.y === y) {
                cell.classList.add('source-selected');
            }

            const target = legalMoves.find(move =>
                move.destination.board.key === board.key &&
                move.destination.x === x && move.destination.y === y
            );
            if (target) {
                cell.classList.add('valid-target');
                if (target.is_branching) cell.classList.add('branch-target');
            }

            const last = gameState.last_move;
            if (last?.source?.board?.key === board.key && last.source.x === x && last.source.y === y) {
                cell.classList.add('last-source');
            }
            if (last?.destination?.board?.key === board.key && last.destination.x === x && last.destination.y === y) {
                cell.classList.add('last-target');
            }

            cell.onclick = event => {
                event.stopPropagation();
                handleCellClick(board.key, x, y);
            };
            grid.appendChild(cell);
        }
    }
    card.appendChild(grid);
    return card;
}

function makeBadge(text, cls) {
    const badge = document.createElement('span');
    badge.className = `board-badge ${cls}`;
    badge.textContent = text;
    return badge;
}

function drawLinks() {
    const svg = document.getElementById('timeline-links');
    const canvas = document.getElementById('timeline-canvas');
    if (!svg || !canvas || !gameState) return;

    const width = Math.max(canvas.scrollWidth, canvas.clientWidth);
    const height = Math.max(canvas.scrollHeight, canvas.clientHeight);
    svg.setAttribute('viewBox', `0 0 ${width} ${height}`);
    svg.style.width = `${width}px`;
    svg.style.height = `${height}px`;
    svg.innerHTML = '';

    const defs = document.createElementNS(SVG_NS, 'defs');
    defs.appendChild(makeArrowMarker('branch-arrow', '#76548f'));
    defs.appendChild(makeArrowMarker('move-arrow', '#6d6af0'));
    defs.appendChild(makeArrowMarker('candidate-arrow', '#3d6ee8'));
    svg.appendChild(defs);

    for (const timeline of gameState.timelines || []) {
        if (timeline.branch_from?.key && timeline.branch_to?.key) {
            appendCurve(svg, timeline.branch_from.key, timeline.branch_to.key, 'branch-link', 'branch-arrow');
        }
    }

    const last = gameState.last_move;
    if (last?.source?.board?.key && last?.destination?.board?.key &&
        last.source.board.key !== last.destination.board.key) {
        appendCurve(svg, last.source.board.key, last.destination.board.key, 'last-move-link', 'move-arrow');
    }

    if (selectedSource) {
        const uniqueTargets = [...new Set(
            legalMoves
                .map(move => move.destination.board.key)
                .filter(key => key !== selectedSource.boardKey)
        )];
        for (const targetKey of uniqueTargets) {
            appendCurve(svg, selectedSource.boardKey, targetKey, 'candidate-link', 'candidate-arrow');
        }
    }
}

function makeArrowMarker(id, color) {
    const marker = document.createElementNS(SVG_NS, 'marker');
    marker.setAttribute('id', id);
    marker.setAttribute('markerWidth', '10');
    marker.setAttribute('markerHeight', '10');
    marker.setAttribute('refX', '8');
    marker.setAttribute('refY', '5');
    marker.setAttribute('orient', 'auto');
    marker.setAttribute('markerUnits', 'strokeWidth');
    const path = document.createElementNS(SVG_NS, 'path');
    path.setAttribute('d', 'M 0 0 L 10 5 L 0 10 z');
    path.setAttribute('fill', color);
    marker.appendChild(path);
    return marker;
}

function appendCurve(svg, fromKey, toKey, className, markerId) {
    const from = document.querySelector(`.board-card[data-board-key="${cssEscape(fromKey)}"]`);
    const to = document.querySelector(`.board-card[data-board-key="${cssEscape(toKey)}"]`);
    const canvas = document.getElementById('timeline-canvas');
    if (!from || !to || !canvas) return;

    const canvasRect = canvas.getBoundingClientRect();
    const a = from.getBoundingClientRect();
    const b = to.getBoundingClientRect();
    const x1 = a.left - canvasRect.left + a.width * 0.72;
    const y1 = a.top - canvasRect.top + a.height * 0.55;
    const x2 = b.left - canvasRect.left + b.width * 0.28;
    const y2 = b.top - canvasRect.top + b.height * 0.45;
    const bend = Math.max(70, Math.abs(x2 - x1) * 0.42);
    const direction = x2 >= x1 ? 1 : -1;

    const path = document.createElementNS(SVG_NS, 'path');
    path.setAttribute('d', `M ${x1} ${y1} C ${x1 + bend * direction} ${y1}, ${x2 - bend * direction} ${y2}, ${x2} ${y2}`);
    path.setAttribute('class', className);
    path.setAttribute('marker-end', `url(#${markerId})`);
    svg.appendChild(path);
}

function renderActionPanel() {
    const action = gameState.action || {};
    const present = gameState.present;
    const summary = document.getElementById('action-summary');
    const required = action.required_boards || [];

    const presentText = present
        ? `T${present.turn} / t${present.time_point} / ${present.side}`
        : '—';
    summary.innerHTML = `
        <div class="action-row"><span>玩家</span><strong>${escapeHtml(action.color || gameState.turn || '?')}</strong></div>
        <div class="action-row"><span>The Present</span><strong>${escapeHtml(presentText)}</strong></div>
        <div class="action-row"><span>Action Moves</span><strong>${action.move_count || 0}</strong></div>
        <div class="action-row"><span>Required</span><strong>${required.length}</strong></div>
        <div class="board-chip-list" id="required-board-chips"></div>
    `;

    const chips = document.getElementById('required-board-chips');
    if (required.length) {
        for (const coord of required) {
            const chip = document.createElement('button');
            chip.className = 'board-chip required';
            chip.textContent = coordLabel(coord);
            chip.onclick = () => focusBoard(coord.key);
            chips.appendChild(chip);
        }
    } else {
        const empty = document.createElement('span');
        empty.className = 'muted';
        empty.textContent = action.can_submit ? 'Present 已推进完成' : '无 required board';
        chips.appendChild(empty);
    }

    const submit = document.getElementById('submit-action-btn');
    submit.disabled = mode !== 'pvp' || !action.can_submit || gameState.game_state !== 'PLAYING';
    submit.classList.toggle('hidden', mode === 'replay');

    const help = document.getElementById('action-help');
    if (mode === 'pvp') {
        help.textContent = action.can_submit
            ? '可以提交。若需要，你仍可先在其他 future / inactive playable board 上走可选 Move。'
            : required.length
                ? '红框棋盘必须继续推进；只有 The Present 到达对手且 RoyalRules 安全时才能提交。'
                : '选择橙色可行动棋盘上的棋子。';
    } else if (mode === 'pve') {
        help.textContent = 'PvE 暂沿用现有 AI 兼容路径；本地训练与 Action 级 AI 将在独立分支继续。';
    } else {
        help.textContent = 'Replay 模式展示当前回放状态中的全部时间线棋盘。';
    }

    document.getElementById('check-badge').classList.toggle('hidden', !gameState.in_check);
}

function renderInspector() {
    const panel = document.getElementById('board-inspector');
    const board = focusedBoardKey ? findBoard(focusedBoardKey) : null;
    if (!board) {
        panel.className = 'inspector muted';
        panel.textContent = '点击任意棋盘可查看 BoardCoord；点击可行动棋盘上的棋子开始走子。';
        return;
    }

    panel.className = 'inspector';
    const flags = [
        board.playable ? 'PLAYABLE' : 'HISTORICAL',
        board.timeline_active ? 'ACTIVE' : 'INACTIVE',
        board.is_present ? 'PRESENT' : null,
        board.is_required ? 'REQUIRED' : null,
        board.is_movable ? 'MOVABLE' : null,
    ].filter(Boolean).join(' · ');
    let extra = '';
    if (selectedSource?.boardKey === board.key) {
        extra = `<br><strong>已选棋子：</strong>(${selectedSource.x}, ${selectedSource.y}) · ${legalMoves.length} 个合法目标`;
    } else if (legalMoves.some(move => move.destination.board.key === board.key)) {
        const count = legalMoves.filter(move => move.destination.board.key === board.key).length;
        extra = `<br><strong>5D 目标：</strong>${count} 个`;
    }

    panel.innerHTML = `
        <strong>${coordLabel(board.coord)}</strong><br>
        Canonical turn: T${board.coord.turn} · side: ${escapeHtml(board.coord.side)}<br>
        Legacy time: t${board.coord.time_point}<br>
        ${escapeHtml(flags)}${extra}
    `;
}

function renderHistory() {
    const container = document.getElementById('move-history');
    container.innerHTML = '';
    const history = gameState.move_history || [];
    if (!history.length) {
        container.textContent = '(无)';
        return;
    }
    history.forEach((notation, index) => {
        const row = document.createElement('div');
        row.className = 'history-entry';
        row.textContent = `${index + 1}. ${notation}`;
        container.appendChild(row);
    });
    container.scrollTop = container.scrollHeight;
}

function renderReplayPanel() {
    document.getElementById('replay-panel').classList.toggle('hidden', mode !== 'replay');
}

function scrollToCurrent() {
    if (!gameState) return;
    const key = gameState.action?.required_boards?.[0]?.key
        || gameState.present?.boards?.[0]?.key
        || gameState.action?.movable_boards?.[0]?.key
        || gameState.boards?.find(board => board.playable)?.key;
    if (key) focusBoard(key, true);
}

function zoomBoards(delta) {
    boardZoom = Math.max(128, Math.min(272, boardZoom + delta));
    document.documentElement.style.setProperty('--board-size', `${boardZoom}px`);
    setTimeout(drawLinks, 40);
}

function checkGameOver() {
    const terminal = ['CHECKMATE', 'STALEMATE', 'DRAW'].includes(gameState.game_state);
    let overlay = document.getElementById('game-over-overlay');
    if (!terminal) {
        if (overlay) overlay.remove();
        return;
    }
    if (overlay) return;

    overlay = document.createElement('div');
    overlay.id = 'game-over-overlay';
    overlay.innerHTML = `
        <div id="game-over-dialog">
            <h2>游戏结束</h2>
            <p>${escapeHtml(resultLabel(gameState.game_state))}</p>
            <button class="submit-btn" onclick="backToMenu()">返回菜单</button>
        </div>
    `;
    document.body.appendChild(overlay);
}

// ---------------------------------------------------------------------------
// Utilities
// ---------------------------------------------------------------------------

function coordLabel(coord) {
    if (!coord) return '—';
    const lane = coord.timeline === 0 ? 'L0' : `L${coord.timeline > 0 ? '+' : ''}${coord.timeline}`;
    return `${lane} · T${coord.turn} · ${coord.side}`;
}

function modeLabel(value) {
    return ({ pvp: 'PvP', pve: 'PvE', replay: 'Replay' })[value] || value || '?';
}

function resultLabel(value) {
    return ({
        CHECKMATE: 'Checkmate · 将杀',
        STALEMATE: 'Stalemate · 逼和',
        DRAW: 'Draw · 和棋',
    })[value] || value;
}

function switchToScreen(id) {
    document.querySelectorAll('.screen').forEach(screen => screen.classList.remove('active'));
    document.getElementById(id)?.classList.add('active');
    document.getElementById('game-over-overlay')?.remove();
}

function showToast(message, isError = false) {
    const toast = document.getElementById('toast');
    toast.textContent = message;
    toast.classList.toggle('error', isError);
    toast.classList.add('show');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => toast.classList.remove('show'), 2200);
}

function escapeHtml(value) {
    return String(value ?? '')
        .replaceAll('&', '&amp;')
        .replaceAll('<', '&lt;')
        .replaceAll('>', '&gt;')
        .replaceAll('"', '&quot;')
        .replaceAll("'", '&#039;');
}

function cssEscape(value) {
    if (window.CSS?.escape) return CSS.escape(String(value));
    return String(value).replace(/([:])/g, '\\$1');
}

window.addEventListener('resize', () => {
    if (gameState) requestAnimationFrame(drawLinks);
});

document.addEventListener('keydown', event => {
    if (!gameState) return;
    if (event.key === 'Escape') clearSelection();
    if (event.key === 'Enter' && mode === 'pvp' && gameState.action?.can_submit) submitAction();
    if (event.key === '+' || event.key === '=') zoomBoards(16);
    if (event.key === '-') zoomBoards(-16);

    if (mode === 'replay') {
        if (event.key === 'ArrowLeft') replayAction('backward');
        if (event.key === 'ArrowRight') replayAction('forward');
        if (event.key === ' ') {
            event.preventDefault();
            replayAction('toggle');
        }
        if (event.key === 'Home') replayAction('start');
        if (event.key === 'End') replayAction('end');
    }
});
