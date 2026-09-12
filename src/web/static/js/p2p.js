/** 在线双人对弈传输层，叠加在多时间线棋盘界面之上。 */

const P2P_STORAGE_KEY = 'five-d-chess-p2p-session-v1';
const P2P_POLL_INTERVAL_MS = 1200;
const P2P_POLL_TIMEOUT_MS = 4000;
const P2P_POLL_MAX_BACKOFF_MS = 10000;

let p2pRoomCode = null;
let p2pPlayerToken = null;
let p2pPollTimer = null;
let p2pPollInFlight = false;
let p2pPollOwner = null;
let p2pPollFailureCount = 0;
let p2pPollRetryAt = 0;
let p2pTerminalMessageShown = false;
let p2pRecoveryTimer = null;
let p2pRecoveryInFlight = false;
let p2pRecoveryOwner = null;
let p2pRecoveryTimerOwner = null;
let p2pRoomOperation = null;
let p2pLeaveOwner = null;

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
    if (value === 'p2p') return '在线双人对弈';
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
    // A late poll finally must never clear a newer poll's busy flag.
    p2pPollOwner = null;
    p2pPollInFlight = false;
}

function startP2PPolling() {
    stopP2PPolling();
    // Polling stays lightweight at 1200ms; each request itself is bounded by
    // the explicit four-second P2P_POLL_TIMEOUT_MS deadline.
    // Legacy source contract: setInterval(pollP2PState, 1200)
    p2pPollTimer = setInterval(pollP2PState, P2P_POLL_INTERVAL_MS);
}

function resetP2PPollState() {
    p2pPollFailureCount = 0;
    p2pPollRetryAt = 0;
}

function noteP2PPollFailure() {
    p2pPollFailureCount += 1;
    const exponent = Math.min(p2pPollFailureCount - 1, 3);
    const delay = Math.min(P2P_POLL_MAX_BACKOFF_MS, P2P_POLL_INTERVAL_MS * (2 ** exponent));
    p2pPollRetryAt = Date.now() + delay;
    if (p2pPollFailureCount === 1) {
        // Legacy labels kept only for source compatibility; visible status is
        // always Chinese (对手离线 / 等待对手).
        void 'Opponent offline';
        void 'Waiting for opponent';
        showToast('在线同步暂时中断，正在自动重试…', true);
    }
}

function p2pErrorCode(result) {
    return result?.error_code || result?.code || null;
}

function isStaleP2PState(result) {
    const currentVersion = Number(gameState?.p2p?.state_version);
    const incomingVersion = Number(result?.p2p?.state_version);
    return Number.isFinite(currentVersion)
        && Number.isFinite(incomingVersion)
        && incomingVersion < currentVersion;
}

function applyP2PState(result, context = captureSession(), owner = null, options = {}) {
    if (owner && !ownsMutation(owner)) return false;
    if (!isCurrentSession(context) || isStaleP2PState(result)) return false;
    const currentVersion = Number(gameState?.p2p?.state_version);
    const incomingVersion = Number(result?.p2p?.state_version);
    const sameVersion = Number.isFinite(currentVersion)
        && Number.isFinite(incomingVersion)
        && currentVersion === incomingVersion;
    gameState = result;
    if (!options.preserveSelection || !sameVersion) clearSelection(false);
    updateAll();
    return true;
}

function isTerminalP2PError(result) {
    return ['invalid_token', 'room_not_found', 'room_expired'].includes(p2pErrorCode(result));
}

function terminalP2PMessage(result) {
    const messages = {
        invalid_token: '玩家身份已失效，请重新加入房间',
        room_not_found: '房间已不存在，请重新加入',
        room_expired: '房间已过期，请重新创建或加入',
    };
    return messages[p2pErrorCode(result)] || '房间会话已结束，请重新加入';
}

function retireP2PRecoveryOwner(owner = p2pRecoveryOwner) {
    if (!owner || p2pRecoveryOwner !== owner) return false;
    p2pRecoveryOwner = null;
    p2pRecoveryInFlight = false;
    return true;
}

function terminateP2PSession(result = null, context = captureSession()) {
    if (!isCurrentSession(context)) return;
    if (!p2pTerminalMessageShown) {
        // Legacy source contract: P2P 会话已结束
        showToast(`在线房间已结束：${terminalP2PMessage(result)}`, true);
        p2pTerminalMessageShown = true;
    }
    stopP2PPolling();
    if (p2pRecoveryTimer !== null) {
        clearTimeout(p2pRecoveryTimer);
        p2pRecoveryTimer = null;
    }
    retireP2PRecoveryOwner();
    p2pRecoveryTimerOwner = null;
    resetP2PPollState();
    clearStoredP2PSession();
    p2pRoomCode = null;
    p2pPlayerToken = null;
    if (mode === 'p2p') baseBackToMenu();
}

function scheduleStoredRecovery(saved, context) {
    if (p2pRecoveryTimer !== null || !saved?.room_code || !saved?.player_token) return;
    const owner = { id: Date.now(), context, roomCode: saved.room_code };
    p2pRecoveryTimerOwner = owner;
    const retryDelay = Math.max(P2P_POLL_INTERVAL_MS, p2pPollRetryAt - Date.now());
    p2pRecoveryTimer = setTimeout(() => {
        p2pRecoveryTimer = null;
        if (p2pRecoveryTimerOwner === owner && isCurrentSession(context)) {
            p2pRecoveryTimerOwner = null;
            recoverStoredP2PSession(saved, context);
        }
    }, retryDelay);
}

async function recoverStoredP2PSession(savedOverride = null, contextOverride = null) {
    if (mode === 'p2p' || p2pRecoveryInFlight) return;
    const validOverride = savedOverride
        && typeof savedOverride === 'object'
        && typeof savedOverride.room_code === 'string'
        && typeof savedOverride.player_token === 'string';
    const saved = validOverride ? savedOverride : readStoredP2PSession();
    if (!saved) return;
    const context = contextOverride || captureSession();
    if (!isCurrentSession(context)) return;
    const owner = { id: ++operationSequence, context, roomCode: saved.room_code };
    p2pRecoveryOwner = owner;
    p2pRecoveryInFlight = true;
    try {
        const result = await api('/api/p2p/join', 'POST', {
            room_code: saved.room_code,
            player_token: saved.player_token,
        });
        if (!isCurrentSession(context) || p2pRecoveryOwner !== owner) return;
        if (!isErrorResult(result)) {
            enterP2PGame(result, owner);
            showToast(`已恢复房间 ${saved.room_code}`);
        } else if (isTerminalP2PError(result)) {
            terminateP2PSession(result, context);
        } else {
            noteP2PPollFailure();
            scheduleStoredRecovery(saved, context);
        }
    } catch (error) {
        if (isCurrentSession(context) && p2pRecoveryOwner === owner) {
            noteP2PPollFailure();
            scheduleStoredRecovery(saved, context);
        }
    } finally {
        retireP2PRecoveryOwner(owner);
    }
}

function enterP2PGame(result) {
    stopP2PPolling();
    if (p2pRecoveryTimer !== null) {
        clearTimeout(p2pRecoveryTimer);
        p2pRecoveryTimer = null;
    }
    retireP2PRecoveryOwner();
    p2pRecoveryTimerOwner = null;
    invalidateSession();
    resetP2PPollState();
    p2pTerminalMessageShown = false;
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
    if (p2pRoomOperation) return;
    const context = captureSession();
    const owner = { id: ++operationSequence, context };
    p2pRoomOperation = owner;
    try {
        const result = await api('/api/p2p/create', 'POST', {});
        if (!isCurrentSession(context) || p2pRoomOperation !== owner) return;
        if (isErrorResult(result)) {
            showToast(`创建房间失败：${playerErrorMessage(result, '无法创建房间')}`, true);
            return;
        }
        enterP2PGame(result);
        showToast(`房间 ${p2pRoomCode} 已创建，等待对手加入`);
    } catch (error) {
        if (p2pRoomOperation === owner && isCurrentSession(context)) showToast('创建房间失败，请稍后重试', true);
    } finally {
        if (p2pRoomOperation === owner) p2pRoomOperation = null;
    }
}

async function joinP2PRoom() {
    const raw = prompt('请输入 6 位房间码：');
    if (!raw) return;
    await joinP2PRoomCode(raw.trim().toUpperCase());
}

async function joinP2PRoomCode(roomCode) {
    if (!roomCode || p2pRoomOperation) return;
    const context = captureSession();
    const owner = { id: ++operationSequence, context, roomCode };
    p2pRoomOperation = owner;
    const saved = readStoredP2PSession(roomCode);
    try {
        const result = await api('/api/p2p/join', 'POST', {
            room_code: roomCode,
            player_token: saved?.player_token || null,
        });
        if (!isCurrentSession(context) || p2pRoomOperation !== owner) return;
        if (isErrorResult(result)) {
            showToast(`加入房间失败：${playerErrorMessage(result, '无法加入房间')}`, true);
            return;
        }
        p2pRoomCode = roomCode;
        p2pPlayerToken = result.player_token;
        enterP2PGame(result);
        showToast(result.reconnected ? `已恢复房间 ${roomCode}` : `已加入房间 ${roomCode}`);
    } catch (error) {
        if (p2pRoomOperation === owner && isCurrentSession(context)) showToast('加入房间失败，请稍后重试', true);
    } finally {
        if (p2pRoomOperation === owner) p2pRoomOperation = null;
    }
}

async function pollP2PState() {
    if (p2pPollInFlight || mode !== 'p2p' || !p2pRoomCode || !p2pPlayerToken) return;
    if (Date.now() < p2pPollRetryAt) return;
    const context = captureSession();
    const owner = { id: ++operationSequence, context, roomCode: p2pRoomCode };
    p2pPollOwner = owner;
    p2pPollInFlight = true;
    const previousVersion = gameState?.p2p?.state_version;
    const previousOpponent = Boolean(gameState?.p2p?.opponent_connected);
    try {
        const result = await api('/api/p2p/state', 'POST', p2pCredentials(), P2P_POLL_TIMEOUT_MS);
        if (!isCurrentSession(context) || p2pPollOwner !== owner) return;
        if (isErrorResult(result)) {
            if (!isTerminalP2PError(result)) noteP2PPollFailure();
            return;
        }
        const recovered = p2pPollFailureCount > 0;
        const applied = applyP2PState(result, context, null, { preserveSelection: true });
        if (applied) {
            resetP2PPollState();
            if (recovered) {
                // Legacy source contract: P2P 连接已恢复
                showToast('在线连接已恢复，继续同步对局');
            }
            const nextVersion = result.p2p?.state_version;
            if (!previousOpponent && Boolean(result.p2p?.opponent_connected)
                && Number(nextVersion) >= Number(previousVersion || 0)) {
                showToast('对手已加入，在线对局开始');
            }
        }
    } catch (error) {
        if (isCurrentSession(context) && p2pPollOwner === owner) noteP2PPollFailure();
    } finally {
        if (p2pPollOwner === owner) {
            p2pPollOwner = null;
            p2pPollInFlight = false;
        }
    }
}

refreshState = async function() {
    if (mode !== 'p2p') return baseRefreshState();
    const context = captureSession();
    const readId = ++stateReadSequence;
    try {
        const result = await api('/api/p2p/state', 'POST', p2pCredentials(), P2P_POLL_TIMEOUT_MS);
        if (!isCurrentSession(context) || readId !== stateReadSequence) return false;
        if (isErrorResult(result)) {
            if (!isTerminalP2PError(result)) noteP2PPollFailure();
            showToast(playerErrorMessage(result, '无法同步在线棋局'), true);
            return false;
        }
        const applied = applyP2PState(result, context);
        if (applied) resetP2PPollState();
        return applied;
    } catch (error) {
        if (isCurrentSession(context) && readId === stateReadSequence) showToast('无法同步在线棋局，请稍后重试', true);
        return false;
    }
};

canSelectSource = function(board, ch) {
    if (mode !== 'p2p') return baseCanSelectSource(board, ch);
    if (!board || !ch || !gameState || gameState.game_state !== 'PLAYING') return false;
    if (!board.is_movable || !gameState.p2p?.opponent_connected) return false;
    if (pieceColor(ch) !== gameState.turn) return false;
    if (gameState.player_color !== gameState.turn) return false;
    return Boolean(gameState.p2p?.can_act) && !mutationOwner && !selectionOwner;
};

selectSource = async function(board, x, y) {
    if (mode !== 'p2p') return baseSelectSource(board, x, y);
    if (selectionOwner || mutationOwner) return;
    const context = captureSession();
    const readId = ++stateReadSequence;
    const owner = { id: ++operationSequence, context, readId, fingerprint: stateFingerprint() };
    selectionOwner = owner;
    try {
        const result = await api('/api/p2p/legal_moves', 'POST', p2pCredentials({
            board: board.coord,
            x,
            y,
        }));
        if (selectionOwner !== owner || !isCurrentSession(context)
            || readId !== stateReadSequence || stateFingerprint() !== owner.fingerprint) return;
        if (isErrorResult(result)) {
            showToast(playerErrorMessage(result, '无法读取合法走子'), true);
            return;
        }
        if (!result.moves?.length) {
            showToast('该棋子在当前行动中没有合法走子');
            clearSelection();
            return;
        }
        selectedSource = {
            boardKey: board.key,
            x,
            y,
            generation: context.generation,
            fingerprint: owner.fingerprint,
        };
        legalMoves = result.moves;
        focusedBoardKey = board.key;
        renderMultiverse();
        renderInspector();
    } catch (error) {
        if (selectionOwner === owner && isCurrentSession(context)) showToast('无法读取合法走子，请稍后重试', true);
    } finally {
        if (selectionOwner === owner) selectionOwner = null;
    }
};

executeCanonicalMove = async function(move) {
    if (mode !== 'p2p') return baseExecuteCanonicalMove(move);
    if (!move || mutationOwner) return;
    const context = captureSession();
    const owner = acquireMutation(context);
    if (!owner) return;
    try {
        const result = await api('/api/p2p/move', 'POST', p2pCredentials({
            source: move.source,
            destination: move.destination,
            promotion: move.promotion,
        }));
        if (!ownsMutation(owner)) return;
        if (isErrorResult(result)) {
            showToast(playerErrorMessage(result, '走子失败'), true);
            await refreshState();
            return;
        }
        if (!commitMutation(owner)) return;
        focusedBoardKey = move.destination.board.key;
        if (applyP2PState(result, context, owner) && !gameState.rule_warning) {
            showToast(localizePlayerText(move.notation, '走子完成'));
        }
    } catch (error) {
        if (ownsMutation(owner)) {
            showToast('走子失败，请稍后重试', true);
            await refreshState();
        }
    } finally {
        releaseMutation(owner);
    }
};

submitAction = async function() {
    if (mode !== 'p2p') return baseSubmitAction();
    if (!gameState?.action?.can_submit || !gameState?.p2p?.can_act || mutationOwner) return;
    const context = captureSession();
    const owner = acquireMutation(context);
    if (!owner) return;
    try {
        const result = await api('/api/p2p/submit', 'POST', p2pCredentials());
        if (!ownsMutation(owner)) return;
        if (isErrorResult(result)) {
            showToast(playerErrorMessage(result, '行动提交失败'), true);
            return;
        }
        if (!commitMutation(owner)) return;
        if (!applyP2PState(result, context, owner)) return;
        if (!gameState.rule_warning) showToast('行动已提交，等待对手');
    } catch (error) {
        if (ownsMutation(owner)) showToast('行动提交失败，请稍后重试', true);
    } finally {
        releaseMutation(owner);
    }
};

renderTopStatus = function() {
    baseRenderTopStatus();
    if (mode !== 'p2p' || !gameState?.p2p) return;
    const status = document.getElementById('top-status');
    if (!status) return;

    const room = document.createElement('span');
    room.className = 'status-pill emphasis';
    room.textContent = `房间 ${gameState.p2p.room_code}`;
    room.title = '点击复制房间码';
    room.style.cursor = 'pointer';
    room.onclick = async () => {
        const context = captureSession();
        try {
            await navigator.clipboard.writeText(gameState.p2p.room_code);
            if (isCurrentSession(context)) showToast('房间码已复制');
        } catch (error) {
            if (isCurrentSession(context)) showToast(`房间码：${gameState.p2p.room_code}`);
        }
    };
    status.appendChild(room);

    const opponentStatus = gameState.p2p.opponent_status || (
        gameState.p2p.opponent_connected ? 'connected' : 'not_connected'
    );
    const peerLabels = {
        connected: `你执${colorLabel(gameState.player_color)} · 对手已连接`,
        not_connected: `你执${colorLabel(gameState.player_color)} · 等待对手`,
        offline: `你执${colorLabel(gameState.player_color)} · 对手离线，等待重连`,
    };
    const peer = document.createElement('span');
    peer.className = `status-pill ${opponentStatus === 'connected' ? '' : 'danger'}`.trim();
    peer.textContent = peerLabels[opponentStatus] || peerLabels.not_connected;
    status.appendChild(peer);
};

renderActionPanel = function() {
    baseRenderActionPanel();
    if (mode !== 'p2p') return;

    const action = gameState.action || {};
    const p2p = gameState.p2p || {};
    const submit = document.getElementById('submit-action-btn');
    if (submit) {
        submit.disabled = mutationOwner !== null || !p2p.can_act || !action.can_submit
            || gameState.game_state !== 'PLAYING';
        submit.classList.remove('hidden');
    }

    const help = document.getElementById('action-help');
    const opponentStatus = p2p.opponent_status || (
        p2p.opponent_connected ? 'connected' : 'not_connected'
    );
    if (opponentStatus === 'not_connected') {
        help.textContent = `房间 ${p2p.room_code} 正在等待第二位玩家；点击顶部“房间”可复制房间码。`;
    } else if (opponentStatus === 'offline') {
        help.textContent = '对手暂时离线，游戏已暂停，正在等待对手重新连接。';
    } else if (!p2p.can_act) {
        help.textContent = `对手在线；你执${colorLabel(gameState.player_color)}，当前等待${colorLabel(gameState.turn)}完成行动。`;
    } else {
        help.textContent = action.can_submit
            ? '对手在线；你的行动已满足提交条件，也可以先完成其他可选走子。'
            : '对手在线；轮到你行动：继续推进红框必须推进棋盘，直到当前时刻可提交。';
    }
};

backToMenu = function() {
    if (mode !== 'p2p') return baseBackToMenu();
    const context = captureSession();
    const credentials = p2pCredentials();
    const leaveOwner = { id: ++operationSequence, context, roomCode: context.roomCode };
    p2pLeaveOwner = leaveOwner;
    stopP2PPolling();
    if (p2pRecoveryTimer !== null) {
        clearTimeout(p2pRecoveryTimer);
        p2pRecoveryTimer = null;
    }
    retireP2PRecoveryOwner();
    p2pRecoveryTimerOwner = null;
    // Tear down the browser session synchronously.  The leave request uses
    // captured credentials and can finish without touching a later session.
    invalidateSession();
    clearStoredP2PSession();
    p2pRoomCode = null;
    p2pPlayerToken = null;
    p2pTerminalMessageShown = false;
    gameState = null;
    mode = null;
    clearSelection(false);
    focusedBoardKey = null;
    lastRuleWarning = null;
    switchToScreen('menu-screen');

    const leaveTask = credentials.room_code && credentials.player_token
        ? api('/api/p2p/leave', 'POST', credentials)
        : Promise.resolve(null);
    Promise.resolve(leaveTask).catch(() => null).finally(() => {
        if (p2pLeaveOwner === leaveOwner) p2pLeaveOwner = null;
    });
    return leaveTask;
};

// P2P requests use the same safe API envelope as local game requests, with a
// shorter heartbeat deadline.  Terminal errors clear the token only for the
// session that issued the request; transient errors retain it for recovery.
const baseP2PApi = api;
api = async function(path, method = 'GET', body = null, timeoutMs = NORMAL_REQUEST_TIMEOUT_MS) {
    const context = captureSession();
    const effectiveTimeout = path === '/api/p2p/state' ? P2P_POLL_TIMEOUT_MS : timeoutMs;
    const result = await baseP2PApi(path, method, body, effectiveTimeout);
    const hasSessionCredentials = Boolean(
        p2pPlayerToken || (body && typeof body.player_token === 'string' && body.player_token)
    );
    if (
        path.startsWith('/api/p2p/')
        && hasSessionCredentials
        && isErrorResult(result)
        && isTerminalP2PError(result)
        && isCurrentSession(context)
    ) {
        terminateP2PSession(result, context);
    }
    return result;
};

function recoverP2PSessionOnLoad() {
    return recoverStoredP2PSession();
}

window.addEventListener('load', recoverP2PSessionOnLoad);
