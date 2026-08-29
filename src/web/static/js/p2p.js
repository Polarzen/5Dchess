/** Online two-player adapter layered over the existing multiverse UI. */

const P2P_STORAGE_KEY = 'five-d-chess-p2p-session-v1';
let p2pRoomCode = null;
let p2pPlayerToken = null;
let p2pPollTimer = null;
let p2pPollInFlight = false;
let p2pRecoveryTimer = null;
let p2pRecoveryInFlight = false;

const baseRefreshState = refreshState;
const baseSubmitAction = submitAction;
const baseSelectSource = selectSource;
const baseExecuteCanonicalMove = executeCanonicalMove;
const baseCanSelectSource = canSelectSource;
const baseRenderTopStatus = renderTopStatus;
const baseRenderActionPanel = renderActionPanel;
const baseBackToMenu = backToMenu;
const baseModeLabel = modeLabel;

modeLabel = function(value) {
    if (value === 'p2p') return 'P2P';
    return baseModeLabel(value);
};

function p2pCredentials(extra = {}) {
    return {
        room_code: p2pRoomCode,
        player_token: p2pPlayerToken,
        ...extra,
    };
}

function readStoredP2PSession(roomCode = null) {
    try {
        const raw = window.localStorage.getItem(P2P_STORAGE_KEY);
        if (!raw) return null;
        const saved = JSON.parse(raw);
        if (!saved?.room_code || !saved?.player_token) return null;
        if (roomCode && saved.room_code !== roomCode) return null;
        return saved;
    } catch (error) {
        console.warn('Failed to read stored P2P session', error);
        return null;
    }
}

function storeP2PSession() {
    if (!p2pRoomCode || !p2pPlayerToken) return;
    window.localStorage.setItem(P2P_STORAGE_KEY, JSON.stringify({
        room_code: p2pRoomCode,
        player_token: p2pPlayerToken,
    }));
}

function clearStoredP2PSession() {
    window.localStorage.removeItem(P2P_STORAGE_KEY);
}

function stopP2PPolling() {
    if (p2pPollTimer !== null) {
        clearInterval(p2pPollTimer);
        p2pPollTimer = null;
    }
}

function startP2PPolling() {
    stopP2PPolling();
    p2pPollTimer = setInterval(pollP2PState, 1200);
}

function p2pErrorCode(result) {
    return result?.code || result?.error || null;
}

function isStaleP2PState(result) {
    const currentVersion = gameState?.p2p?.state_version;
    const incomingVersion = result?.p2p?.state_version;
    return Number.isFinite(currentVersion)
        && Number.isFinite(incomingVersion)
        && incomingVersion < currentVersion;
}

function applyP2PState(result) {
    if (isStaleP2PState(result)) return false;
    gameState = result;
    clearSelection(false);
    updateAll();
    return true;
}

function isTerminalP2PError(result) {
    return ['invalid_token', 'room_not_found', 'room_expired'].includes(p2pErrorCode(result));
}

function terminateP2PSession() {
    stopP2PPolling();
    if (p2pRecoveryTimer !== null) {
        clearTimeout(p2pRecoveryTimer);
        p2pRecoveryTimer = null;
    }
    clearStoredP2PSession();
    p2pRoomCode = null;
    p2pPlayerToken = null;
    if (mode === 'p2p') baseBackToMenu();
}

async function recoverStoredP2PSession() {
    if (mode === 'p2p' || p2pRecoveryInFlight) return;
    const saved = readStoredP2PSession();
    if (!saved) return;
    p2pRecoveryInFlight = true;
    try {
        const result = await api('/api/p2p/join', 'POST', {
            room_code: saved.room_code,
            player_token: saved.player_token,
        });
        if (!result.error) {
            enterP2PGame(result);
            showToast(`已恢复房间 ${saved.room_code}`);
        } else if (isTerminalP2PError(result)) {
            terminateP2PSession();
        } else if (p2pRecoveryTimer === null) {
            console.warn('P2P recovery failed; retrying', p2pErrorCode(result));
            p2pRecoveryTimer = setTimeout(() => {
                p2pRecoveryTimer = null;
                recoverStoredP2PSession();
            }, 1200);
        }
    } finally {
        p2pRecoveryInFlight = false;
    }
}

function enterP2PGame(result) {
    if (p2pRecoveryTimer !== null) {
        clearTimeout(p2pRecoveryTimer);
        p2pRecoveryTimer = null;
    }
    mode = 'p2p';
    gameState = result;
    p2pRoomCode = result.room_code || result.p2p?.room_code || p2pRoomCode;
    p2pPlayerToken = result.player_token || p2pPlayerToken;
    storeP2PSession();
    clearSelection(false);
    switchToScreen('game-screen');
    updateAll();
    startP2PPolling();
    requestAnimationFrame(scrollToCurrent);
}

async function createP2PRoom() {
    const result = await api('/api/p2p/create', 'POST', {});
    if (result.error) {
        showToast(`创建房间失败：${result.error}`, true);
        return;
    }
    enterP2PGame(result);
    showToast(`房间 ${p2pRoomCode} 已创建，等待对手加入`);
}

async function joinP2PRoom() {
    const raw = prompt('输入 6 位房间码：');
    if (!raw) return;
    const roomCode = raw.trim().toUpperCase();
    const saved = readStoredP2PSession(roomCode);
    const result = await api('/api/p2p/join', 'POST', {
        room_code: roomCode,
        player_token: saved?.player_token || null,
    });
    if (result.error) {
        showToast(`加入房间失败：${result.error}`, true);
        return;
    }
    p2pRoomCode = roomCode;
    p2pPlayerToken = result.player_token;
    enterP2PGame(result);
    showToast(result.reconnected ? `已恢复房间 ${roomCode}` : `已加入房间 ${roomCode}`);
}

async function pollP2PState() {
    if (mode !== 'p2p' || !p2pRoomCode || !p2pPlayerToken) return;
    const previousVersion = gameState?.p2p?.state_version;
    const previousOpponent = Boolean(gameState?.p2p?.opponent_connected);
    const previousWarning = gameState?.rule_warning || null;

    const result = await api('/api/p2p/state', 'POST', p2pCredentials());
    if (result.error) {
        stopP2PPolling();
        showToast(`P2P同步中断：${result.error}`, true);
        return;
    }

    const nextVersion = result.p2p?.state_version;
    const nextOpponent = Boolean(result.p2p?.opponent_connected);
    const warningChanged = (result.rule_warning || null) !== previousWarning;
    if (nextVersion !== previousVersion || warningChanged) {
        gameState = result;
        clearSelection(false);
        updateAll();
    }
    if (!previousOpponent && nextOpponent) {
        showToast('对手已加入，在线对局开始');
    }
}

refreshState = async function() {
    if (mode !== 'p2p') return baseRefreshState();
    const result = await api('/api/p2p/state', 'POST', p2pCredentials());
    if (result.error) {
        showToast(result.error, true);
        return;
    }
    applyP2PState(result);
};

canSelectSource = function(board, ch) {
    if (mode !== 'p2p') return baseCanSelectSource(board, ch);
    if (!board || !ch || !gameState || gameState.game_state !== 'PLAYING') return false;
    if (!board.is_movable || !gameState.p2p?.opponent_connected) return false;
    if (pieceColor(ch) !== gameState.turn) return false;
    if (gameState.player_color !== gameState.turn) return false;
    return Boolean(gameState.p2p?.can_act);
};

selectSource = async function(board, x, y) {
    if (mode !== 'p2p') return baseSelectSource(board, x, y);
    const result = await api('/api/p2p/legal_moves', 'POST', p2pCredentials({
        board: board.coord,
        x,
        y,
    }));
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
};

executeCanonicalMove = async function(move) {
    if (mode !== 'p2p') return baseExecuteCanonicalMove(move);
    const result = await api('/api/p2p/move', 'POST', p2pCredentials({
        source: move.source,
        destination: move.destination,
        promotion: move.promotion,
    }));
    if (result.error) {
        showToast(result.error, true);
        await refreshState();
        return;
    }

    if (isStaleP2PState(result)) return;
    focusedBoardKey = move.destination.board.key;
    applyP2PState(result);
    if (!gameState.rule_warning) showToast(move.notation || '走子完成');
};

submitAction = async function() {
    if (mode !== 'p2p') return baseSubmitAction();
    if (!gameState?.action?.can_submit || !gameState?.p2p?.can_act) return;
    const result = await api('/api/p2p/submit', 'POST', p2pCredentials());
    if (result.error) {
        showToast(result.error, true);
        return;
    }
    if (!applyP2PState(result)) return;
    if (!gameState.rule_warning) showToast('Action 已提交，等待对手');
};

renderTopStatus = function() {
    baseRenderTopStatus();
    if (mode !== 'p2p' || !gameState?.p2p) return;
    const status = document.getElementById('top-status');

    const room = document.createElement('span');
    room.className = 'status-pill emphasis';
    room.textContent = `Room ${gameState.p2p.room_code}`;
    room.title = '点击复制房间码';
    room.style.cursor = 'pointer';
    room.onclick = async () => {
        try {
            await navigator.clipboard.writeText(gameState.p2p.room_code);
            showToast('房间码已复制');
        } catch (error) {
            showToast(`房间码：${gameState.p2p.room_code}`);
        }
    };
    status.appendChild(room);

    const peer = document.createElement('span');
    peer.className = `status-pill ${gameState.p2p.opponent_connected ? '' : 'danger'}`.trim();
    peer.textContent = gameState.p2p.opponent_connected
        ? `You ${gameState.player_color} · Peer online`
        : `You ${gameState.player_color} · Waiting peer`;
    status.appendChild(peer);
};

renderActionPanel = function() {
    baseRenderActionPanel();
    if (mode !== 'p2p') return;

    const action = gameState.action || {};
    const p2p = gameState.p2p || {};
    const submit = document.getElementById('submit-action-btn');
    submit.disabled = !p2p.can_act || !action.can_submit || gameState.game_state !== 'PLAYING';
    submit.classList.remove('hidden');

    const help = document.getElementById('action-help');
    if (!p2p.opponent_connected) {
        help.textContent = `房间 ${p2p.room_code} 正在等待第二位玩家；点击顶部 Room 可复制房间码。`;
    } else if (!p2p.can_act) {
        help.textContent = `你执 ${gameState.player_color}，当前等待 ${gameState.turn} 完成 Action。`;
    } else {
        help.textContent = action.can_submit
            ? '你的 Action 已满足提交条件；也可以先完成其他可选 Move。'
            : '轮到你行动：继续推进红框 Required 棋盘，直到 The Present 可提交。';
    }
};

backToMenu = async function() {
    if (mode !== 'p2p') return baseBackToMenu();
    stopP2PPolling();
    const credentials = p2pCredentials();
    if (credentials.room_code && credentials.player_token) {
        const result = await api('/api/p2p/leave', 'POST', credentials);
        if (result.error) console.warn('P2P leave failed', result.error);
    }
    clearStoredP2PSession();
    p2pRoomCode = null;
    p2pPlayerToken = null;
    baseBackToMenu();
};

// Keep P2P transport failures recoverable.  The original API helper remains
// the source of network/JSON behavior; this wrapper only handles terminal
// session errors consistently across every P2P action.
const baseP2PApi = api;
api = async function(path, method = 'GET', body = null) {
    const result = await baseP2PApi(path, method, body);
    if (path.startsWith('/api/p2p/') && result.error && isTerminalP2PError(result)) {
        terminateP2PSession();
    }
    return result;
};

// Override the polling routine after the legacy adapter is loaded so one
// slow request cannot overlap the next interval and transient failures retry.
pollP2PState = async function() {
    if (p2pPollInFlight || mode !== 'p2p' || !p2pRoomCode || !p2pPlayerToken) return;
    p2pPollInFlight = true;
    const previousVersion = gameState?.p2p?.state_version;
    const previousOpponent = Boolean(gameState?.p2p?.opponent_connected);
    const previousWarning = gameState?.rule_warning || null;
    try {
        const result = await api('/api/p2p/state', 'POST', p2pCredentials());
        if (result.error) {
            if (!isTerminalP2PError(result)) console.warn('P2P poll failed; retrying');
            return;
        }
        const nextVersion = result.p2p?.state_version;
        const versionAdvanced = !isStaleP2PState(result);
        const warningChanged = (result.rule_warning || null) !== previousWarning;
        if (versionAdvanced && (nextVersion !== previousVersion || warningChanged)) {
            applyP2PState(result);
        }
        if (!previousOpponent && Boolean(result.p2p?.opponent_connected) && versionAdvanced) {
            showToast('Opponent connected');
        }
    } finally {
        p2pPollInFlight = false;
    }
};

window.addEventListener('load', recoverStoredP2PSession);
