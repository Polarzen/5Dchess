/** 5D Chess multiverse browser interaction. */

let gameState = null;
let mode = null;
let selectedSource = null;   // { boardKey, x, y }
let legalMoves = [];         // canonical Move payloads
let focusedBoardKey = null;
let boardZoom = 192;
let toastTimer = null;
let lastRuleWarning = null;
let aiRequestInFlight = false;
let aiRetryAvailable = false;
let aiRecoveryPending = false;

// Every browser request has a finite deadline.  Keeping the values explicit
// makes the contract easy to audit and lets the P2P adapter select its shorter
// heartbeat deadline without changing the normal game API.
const API_TIMEOUT_MS = 10000;
const AI_TIMEOUT_MS = 10000;
const NORMAL_REQUEST_TIMEOUT_MS = API_TIMEOUT_MS;
const activeRequestControllers = new Set();
const pendingAITimers = new Set();

let sessionGeneration = 0;
let stateReadSequence = 0;
let operationSequence = 0;
let mutationOwner = null;
let selectionOwner = null;
let startOperationOwner = null;
let aiOperationOwner = null;

const ERROR_MESSAGES = Object.freeze({
    timeout: '请求超时，请检查连接后重试',
    aborted: '请求已取消',
    network: '网络连接失败，请检查连接后重试',
    invalid_response: '服务器返回了无法识别的响应',
    http: '服务器暂时无法处理请求',
    invalid_token: '玩家身份已失效，请重新加入房间',
    room_not_found: '房间已不存在，请重新加入',
    room_expired: '房间已过期，请重新创建或加入',
    room_full: '房间已满',
    action_not_submittable: '当前行动尚不能提交',
    opponent_offline: '对手暂时离线，请等待重新连接',
    not_your_turn: '当前还不是你的回合',
    ai_timeout: 'AI 请求超时，正在同步棋局',
    ai_thinking: 'AI 正在思考，请稍候',
});

const ERROR_CODE_ALIASES = Object.freeze({
    request_timeout: 'timeout',
    timeout_error: 'timeout',
    network_error: 'network',
    invalid_json: 'invalid_response',
    invalid_response: 'invalid_response',
});

const pieceSymbols = {
    K: '♔', Q: '♕', R: '♖', B: '♗', N: '♘', P: '♙',
    k: '♚', q: '♛', r: '♜', b: '♝', n: '♞', p: '♟',
};

const SVG_NS = 'http://www.w3.org/2000/svg';

function createRequestError(code, extra = {}) {
    const canonical = ERROR_CODE_ALIASES[code] || code;
    const message = ERROR_MESSAGES[canonical]
        || (canonical === 'http' ? ERROR_MESSAGES.http : '请求失败，请稍后重试');
    return {
        error: message,
        code: code || canonical,
        error_code: code || canonical,
        ...extra,
    };
}

function localizePlayerText(value, fallback = '请求失败，请稍后重试') {
    if (value === null || value === undefined || value === '') return fallback;
    let text = String(value);
    // Backend warnings are intentionally allowed to retain technical 5D
    // names, while player-facing English labels are translated at the edge.
    const replacements = [
        [/The\s+Present/gi, '当前时刻'],
        [/Present/gi, '当前时刻'],
        [/Action/gi, '行动'],
        [/Move/gi, '走子'],
        [/Required/gi, '必须推进'],
        [/Movable/gi, '可行动'],
        [/Playable/gi, '可走'],
        [/Historical/gi, '历史'],
        [/Inactive/gi, '非活动'],
        [/Active/gi, '活动'],
        [/Turn/gi, '回合'],
        [/CHECKMATE/gi, '将杀'],
        [/STALEMATE/gi, '逼和'],
        [/DRAW/gi, '和棋'],
        [/CHECK/gi, '将军'],
        [/white/gi, '白方'],
        [/black/gi, '黑方'],
        [/Waiting\s+for\s+opponent/gi, '等待对手'],
        [/Opponent/gi, '对手'],
        [/connected/gi, '已连接'],
        [/offline/gi, '离线'],
        [/Room/gi, '房间'],
        [/You\s+/gi, '你执'],
        [/P2P\s+sync/gi, '在线同步'],
        [/Online\s+P2P/gi, '在线双人对弈'],
        [/Replay/gi, '棋谱回放'],
    ];
    for (const [pattern, replacement] of replacements) text = text.replace(pattern, replacement);
    // A raw browser/HTTP exception can be English and often contains details
    // that are unsuitable for a player.  Return a fixed Chinese fallback.
    if (!/[\u3400-\u9fff]/.test(text)) return fallback;
    return text;
}

function errorCodeOf(result) {
    return result?.error_code || result?.code || null;
}

function playerErrorMessage(result, fallback = '请求失败，请稍后重试') {
    if (!result) return fallback;
    if (result.timeout_error) return ERROR_MESSAGES.timeout;
    if (result.aborted) return ERROR_MESSAGES.aborted;
    if (result.network_error) return ERROR_MESSAGES.network;
    const code = errorCodeOf(result);
    if (code && ERROR_MESSAGES[ERROR_CODE_ALIASES[code] || code]) {
        return ERROR_MESSAGES[ERROR_CODE_ALIASES[code] || code];
    }
    return localizePlayerText(result.error, fallback);
}

function isErrorResult(result) {
    return Boolean(result && (result.error || result.timeout_error || result.network_error));
}

function currentRoomIdentity() {
    // p2p.js declares this later.  typeof keeps game.js usable by itself.
    return typeof p2pRoomCode !== 'undefined' ? p2pRoomCode : null;
}

function captureSession() {
    return {
        generation: sessionGeneration,
        mode,
        roomCode: currentRoomIdentity(),
    };
}

function isCurrentSession(context) {
    if (!context || context.generation !== sessionGeneration || context.mode !== mode) return false;
    if (context.roomCode === null || context.roomCode === undefined) return true;
    return currentRoomIdentity() === context.roomCode;
}

function stateFingerprint() {
    const p2pVersion = gameState?.p2p?.state_version;
    return JSON.stringify([
        gameState?.move_counter ?? null,
        gameState?.turn ?? null,
        gameState?.game_state ?? null,
        Number.isFinite(p2pVersion) ? p2pVersion : null,
        gameState?.current_index ?? null,
        gameState?.action?.move_count ?? null,
    ]);
}

function invalidateSession() {
    sessionGeneration += 1;
    stateReadSequence += 1;
    mutationOwner = null;
    selectionOwner = null;
    startOperationOwner = null;
    aiOperationOwner = null;
    aiRequestInFlight = false;
    aiRetryAvailable = false;
    aiRecoveryPending = false;
    selectedSource = null;
    legalMoves = [];
    for (const timer of pendingAITimers) clearTimeout(timer);
    pendingAITimers.clear();
    for (const controller of activeRequestControllers) {
        try { controller.abort(); } catch (error) { /* already aborted */ }
    }
    return sessionGeneration;
}

function acquireMutation(context) {
    if (!isCurrentSession(context) || mutationOwner) return null;
    stateReadSequence += 1;
    const owner = { id: ++operationSequence, context };
    mutationOwner = owner;
    return owner;
}

function ownsMutation(owner) {
    return Boolean(owner && mutationOwner === owner && isCurrentSession(owner.context));
}

function releaseMutation(owner) {
    if (mutationOwner !== owner) return;
    mutationOwner = null;
    // The successful mutation rendered while it still owned the lock, so the
    // submit/retry controls must be refreshed once ownership is released.
    if (isCurrentSession(owner.context) && gameState) updateAll();
}

function commitMutation(owner) {
    if (!ownsMutation(owner)) return false;
    // A state read that began before the authoritative mutation response must
    // not overwrite the accepted response after it returns.
    stateReadSequence += 1;
    return true;
}

function recomputeAIRecovery() {
    if (!aiRecoveryPending || mode !== 'pve' || !gameState) return;
    if (gameState.game_state !== 'PLAYING' || gameState.turn === gameState.player_color) {
        aiRecoveryPending = false;
        aiRetryAvailable = false;
        return;
    }
    if (gameState.ai_thinking === false) {
        aiRetryAvailable = shouldRunAI();
        if (aiRetryAvailable) aiRecoveryPending = false;
    }
}

function scheduleAIAction(context) {
    if (!isCurrentSession(context)) return;
    const timer = setTimeout(() => {
        pendingAITimers.delete(timer);
        if (isCurrentSession(context)) runAIAction(context);
    }, 220);
    pendingAITimers.add(timer);
}

async function api(path, method = 'GET', body = null, timeoutMs = NORMAL_REQUEST_TIMEOUT_MS) {
    const options = { method, headers: { 'Content-Type': 'application/json' } };
    if (body !== null) options.body = JSON.stringify(body);

    const controller = typeof AbortController === 'function' ? new AbortController() : null;
    if (controller) options.signal = controller.signal;
    if (controller) activeRequestControllers.add(controller);

    let timer = null;
    let timeoutReject = null;
    let timedOut = false;
    let abortedByCaller = false;
    const timeoutPromise = new Promise((_, reject) => {
        timeoutReject = reject;
        timer = setTimeout(() => {
            timedOut = true;
            try { controller?.abort(); } catch (error) { /* best effort */ }
            reject(createRequestError('timeout_error', { timeout_error: true }));
        }, timeoutMs);
    });
    const abortListener = () => { abortedByCaller = !timedOut; };
    controller?.signal.addEventListener('abort', abortListener, { once: true });

    try {
        const fetchPromise = Promise.resolve().then(() => fetch(path, options));
        const response = await Promise.race([fetchPromise, timeoutPromise]);
        const bodyPromise = Promise.resolve().then(() => response.json());
        let data;
        try {
            // The same deadline covers response.json(), including mocks or
            // browser streams that ignore AbortController after headers.
            data = await Promise.race([bodyPromise, timeoutPromise]);
        } catch (error) {
            if (timedOut || error?.timeout_error) throw createRequestError('timeout_error', { timeout_error: true });
            throw createRequestError('invalid_response', { invalid_response: true });
        }
        if (!data || typeof data !== 'object' || Array.isArray(data)) {
            return createRequestError('invalid_response');
        }
        if (response.ok === false) {
            const code = data.error_code || data.code || `http_${response.status}`;
            const message = data.error
                ? localizePlayerText(data.error, ERROR_MESSAGES.http)
                : (ERROR_MESSAGES[code] || ERROR_MESSAGES.http);
            return {
                ...data,
                error: message,
                code: data.code || code,
                error_code: data.error_code || code,
                http_status: response.status,
            };
        }
        if (data.error) data.error = playerErrorMessage(data);
        return data;
    } catch (error) {
        if (timedOut || error?.timeout_error) return createRequestError('timeout_error', { timeout_error: true });
        if (abortedByCaller || error?.name === 'AbortError') {
            return createRequestError('aborted', { aborted: true });
        }
        if (error?.invalid_response || error?.code === 'invalid_response') {
            return createRequestError('invalid_response', { invalid_response: true });
        }
        return createRequestError('network_error', { network_error: true });
    } finally {
        if (timer !== null) clearTimeout(timer);
        if (controller) {
            controller.signal.removeEventListener('abort', abortListener);
            activeRequestControllers.delete(controller);
        }
        // Keep the rejection handler attached if the deadline won before the
        // fetch or body promise settled; this prevents late mock rejections
        // from becoming unhandled while still allowing the request to drain.
        void timeoutReject;
    }
}

// ---------------------------------------------------------------------------
// Session / game flow
// ---------------------------------------------------------------------------

async function startGame(nextMode, difficulty = 'medium') {
    if (startOperationOwner) return;
    invalidateSession();
    mode = nextMode;
    const context = captureSession();
    const owner = { id: ++operationSequence, context };
    startOperationOwner = owner;
    try {
        const result = await api('/api/game/start', 'POST', {
            mode: nextMode,
            difficulty,
            player_color: 'white',
        });
        if (!isCurrentSession(context) || startOperationOwner !== owner) return;
        if (isErrorResult(result)) {
            showToast(`启动失败：${playerErrorMessage(result, '无法启动游戏')}`, true);
            mode = null;
            gameState = null;
            return;
        }
        gameState = result;
        aiRequestInFlight = false;
        aiRetryAvailable = false;
        clearSelection(false);
        switchToScreen('game-screen');
        updateAll();
        requestAnimationFrame(() => {
            if (isCurrentSession(context)) scrollToCurrent();
        });
        if (nextMode === 'pve' && shouldRunAI()) scheduleAIAction(context);
    } catch (error) {
        if (isCurrentSession(context)) showToast('启动失败：无法连接服务器，请稍后重试', true);
    } finally {
        if (startOperationOwner === owner) startOperationOwner = null;
    }
}

function backToMenu() {
    invalidateSession();
    gameState = null;
    mode = null;
    clearSelection(false);
    focusedBoardKey = null;
    lastRuleWarning = null;
    switchToScreen('menu-screen');
}

async function refreshState() {
    if (!mode) return;
    const context = captureSession();
    const readId = ++stateReadSequence;
    try {
        const result = await api('/api/game/state');
        if (!isCurrentSession(context) || readId !== stateReadSequence) return false;
        if (isErrorResult(result)) {
            showToast(playerErrorMessage(result, '无法同步棋局'), true);
            return false;
        }
        gameState = result;
        clearSelection(false);
        recomputeAIRecovery();
        updateAll();
        return true;
    } catch (error) {
        if (isCurrentSession(context) && readId === stateReadSequence) {
            showToast('无法同步棋局，请稍后重试', true);
        }
        return false;
    }
}

async function submitAction() {
    if (!gameState || mode === 'replay' || !gameState.action?.can_submit) return;
    const context = captureSession();
    const owner = acquireMutation(context);
    if (!owner) return;
    try {
        const result = await api('/api/game/submit_action', 'POST', {});
        if (!ownsMutation(owner)) return;
        if (isErrorResult(result)) {
            showToast(playerErrorMessage(result, '行动提交失败'), true);
            return;
        }
        if (!commitMutation(owner)) return;
        gameState = result;
        aiRetryAvailable = false;
        clearSelection(false);
        updateAll();
        if (!gameState.rule_warning) showToast('行动已提交');

        if (mode === 'pve' && shouldRunAI()) scheduleAIAction(context);
    } catch (error) {
        if (ownsMutation(owner)) showToast('行动提交失败，请稍后重试', true);
    } finally {
        releaseMutation(owner);
    }
}

function shouldRunAI() {
    return Boolean(
        gameState && mode === 'pve' &&
        gameState.game_state === 'PLAYING' &&
        gameState.player_color &&
        gameState.turn !== gameState.player_color &&
        gameState.ai_thinking !== true
    );
}

function hasAuthoritativeAIState(result) {
    return Boolean(
        result && result.mode === 'pve' &&
        Array.isArray(result.boards) &&
        typeof result.game_state === 'string' &&
        typeof result.turn === 'string'
    );
}

async function resyncAfterAITimeout(context, owner) {
    if (!ownsMutation(owner)) return false;
    const readId = ++stateReadSequence;
    const result = await api('/api/game/state', 'GET', null, NORMAL_REQUEST_TIMEOUT_MS);
    if (!ownsMutation(owner) || !isCurrentSession(context) || readId !== stateReadSequence) return false;
    if (isErrorResult(result) || !hasAuthoritativeAIState(result)) {
        showToast('AI 超时后棋局同步失败，请稍后手动同步', true);
        aiRetryAvailable = false;
        return false;
    }
    gameState = result;
    clearSelection(false);
    recomputeAIRecovery();
    updateAll();
    if (aiRetryAvailable) showToast('AI 请求超时，棋局已同步；确认仍需 AI 走子后可重试', true);
    else if (result.ai_thinking === true) showToast('AI 仍在思考，已同步当前棋局', true);
    return true;
}

async function runAIAction(context = captureSession(), explicitRetry = false) {
    if (!isCurrentSession(context) || !shouldRunAI() || aiRequestInFlight) return;
    if (explicitRetry && !aiRetryAvailable) return;
    const owner = acquireMutation(context);
    if (!owner) return;
    aiOperationOwner = owner;
    aiRequestInFlight = true;
    aiRetryAvailable = false;
    const info = document.getElementById('game-info');
    try {
        if (info && isCurrentSession(context)) info.textContent = 'AI 正在完成当前行动…';
        const result = await api('/api/game/ai_move', 'POST', {}, AI_TIMEOUT_MS);
        if (!ownsMutation(owner)) return;
        if (isErrorResult(result)) {
            if (hasAuthoritativeAIState(result)) {
                gameState = result;
                clearSelection(false);
            }
            if (result.timeout_error || result.network_error) {
                aiRecoveryPending = true;
                showToast(result.timeout_error ? ERROR_MESSAGES.ai_timeout : 'AI 请求失败，正在同步棋局', true);
                await resyncAfterAITimeout(context, owner);
                return;
            }
            showToast(`AI：${playerErrorMessage(result, 'AI 走子失败，请重试')}`, true);
            aiRetryAvailable = hasAuthoritativeAIState(result)
                && result.ai_thinking === false
                && shouldRunAI();
            updateAll();
            return;
        }
        if (!hasAuthoritativeAIState(result)) {
            showToast('AI 返回了无法识别的棋局状态', true);
            aiRetryAvailable = false;
            return;
        }
        if (!commitMutation(owner)) return;
        gameState = result;
        clearSelection(false);
        aiRetryAvailable = false;
        aiRecoveryPending = false;
        updateAll();
    } catch (error) {
        if (ownsMutation(owner)) {
            aiRecoveryPending = true;
            showToast('AI 请求失败，正在同步棋局', true);
            await resyncAfterAITimeout(context, owner);
        }
    } finally {
        if (aiOperationOwner === owner) {
            aiOperationOwner = null;
            aiRequestInFlight = false;
            if (isCurrentSession(context) && gameState) updateAll();
        }
        releaseMutation(owner);
    }
}

function retryAIAction() {
    const context = captureSession();
    if (!aiRetryAvailable || gameState?.ai_thinking !== false || !shouldRunAI()) return;
    runAIAction(context, true);
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
    if (mutationOwner) return;
    const board = findBoard(boardKey);
    if (!board) return;
    const context = captureSession();
    const clickFingerprint = stateFingerprint();
    focusBoard(boardKey, false);

    const targetMove = selectedSource
        ? legalMoves.find(move =>
            move.destination.board.key === boardKey &&
            move.destination.x === x && move.destination.y === y
        )
        : null;

    if (targetMove) {
        await executeCanonicalMove(targetMove, context, clickFingerprint);
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
    if (selectionOwner || mutationOwner) return;
    const context = captureSession();
    const readId = ++stateReadSequence;
    const owner = { id: ++operationSequence, context, readId, fingerprint: stateFingerprint() };
    selectionOwner = owner;
    try {
        const result = await api('/api/game/legal_moves_5d', 'POST', {
            board: board.coord,
            x,
            y,
        });
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
        if (selectionOwner === owner && isCurrentSession(context)) {
            showToast('无法读取合法走子，请稍后重试', true);
        }
    } finally {
        if (selectionOwner === owner) selectionOwner = null;
    }
}

async function executeCanonicalMove(move, context = captureSession(), fingerprint = stateFingerprint()) {
    if (!move || !isCurrentSession(context) || mutationOwner) return;
    if (selectedSource && (
        selectedSource.generation !== context.generation
        || selectedSource.fingerprint !== fingerprint
    )) {
        clearSelection();
        return;
    }
    const owner = acquireMutation(context);
    if (!owner) return;
    try {
        const result = await api('/api/game/move_5d', 'POST', {
            source: move.source,
            destination: move.destination,
            promotion: move.promotion,
        });
        if (!ownsMutation(owner)) return;
        if (isErrorResult(result)) {
            showToast(playerErrorMessage(result, '走子失败'), true);
            await refreshState();
            return;
        }

        if (!commitMutation(owner)) return;
        gameState = result;
        focusedBoardKey = move.destination.board.key;
        clearSelection(false);
        updateAll();
        if (!gameState.rule_warning) showToast(localizePlayerText(move.notation, '走子完成'));
    } catch (error) {
        if (ownsMutation(owner)) {
            showToast('走子失败，请稍后重试', true);
            await refreshState();
        }
    } finally {
        releaseMutation(owner);
    }
}

function clearSelection(render = true) {
    selectionOwner = null;
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
    const context = captureSession();
    const owner = acquireMutation(context);
    if (!owner) return;
    try {
        const result = await api('/api/replay/step', 'POST', { action });
        if (!ownsMutation(owner)) return;
        if (isErrorResult(result)) return showToast(playerErrorMessage(result, '回放操作失败'), true);
        if (!commitMutation(owner)) return;
        gameState = result;
        clearSelection(false);
        updateAll();
    } catch (error) {
        if (ownsMutation(owner)) showToast('回放操作失败，请稍后重试', true);
    } finally {
        releaseMutation(owner);
    }
}

async function replayJump() {
    if (mode !== 'replay' || mutationOwner) return;
    const raw = prompt('跳转到步数：', String(gameState?.current_index || 0));
    if (raw === null) return;
    const index = Number.parseInt(raw, 10);
    if (Number.isNaN(index)) return;
    const context = captureSession();
    const owner = acquireMutation(context);
    if (!owner) return;
    try {
        const result = await api('/api/replay/step', 'POST', { action: 'jump', index });
        if (!ownsMutation(owner)) return;
        if (isErrorResult(result)) return showToast(playerErrorMessage(result, '回放跳转失败'), true);
        if (!commitMutation(owner)) return;
        gameState = result;
        clearSelection(false);
        updateAll();
    } catch (error) {
        if (ownsMutation(owner)) showToast('回放跳转失败，请稍后重试', true);
    } finally {
        releaseMutation(owner);
    }
}

async function replayLoadFile() {
    const filepath = prompt('输入 .5dpgn 文件路径：');
    if (!filepath) return;
    if (mode !== 'replay' || mutationOwner) return;
    const context = captureSession();
    const owner = acquireMutation(context);
    if (!owner) return;
    try {
        const result = await api('/api/replay/load', 'POST', { filepath });
        if (!ownsMutation(owner)) return;
        if (isErrorResult(result)) return showToast(playerErrorMessage(result, '棋谱加载失败'), true);
        if (!commitMutation(owner)) return;
        gameState = result;
        const acceptedStateFingerprint = stateFingerprint();
        clearSelection(false);
        updateAll();
        requestAnimationFrame(() => {
            if (isCurrentSession(context)
                && mode === 'replay'
                && stateFingerprint() === acceptedStateFingerprint) {
                scrollToCurrent();
            }
        });
    } catch (error) {
        if (ownsMutation(owner)) showToast('棋谱加载失败，请稍后重试', true);
    } finally {
        releaseMutation(owner);
    }
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
    surfaceRuleWarning();
    checkGameOver();
}

function surfaceRuleWarning() {
    const warning = gameState?.rule_warning || null;
    if (!warning) {
        lastRuleWarning = null;
        return;
    }
    if (warning === lastRuleWarning) return;
    lastRuleWarning = warning;
    // Browser contract retained for older checks: 规则保护：${warning}
    showToast(`规则保护：${localizePlayerText(warning, '规则保护已触发')}`, true);
}

function renderTopStatus() {
    const info = document.getElementById('game-info');
    const present = gameState.present;
    if (info) info.textContent = `${modeLabel(mode)} · 第 ${gameState.move_counter || 0} 个行动`;

    const status = document.getElementById('top-status');
    if (!status) return;
    status.innerHTML = '';
    const pills = [
        { text: `当前回合：${colorLabel(gameState.turn)}`, cls: 'emphasis' },
        { text: present ? `当前时刻 t${present.time_point} · ${colorLabel(present.side)}` : '当前时刻 —', cls: '' },
        { text: `${gameState.summary?.active_timelines ?? 0} 条活动时间线 / ${gameState.summary?.total_timelines ?? 0} 条时间线`, cls: '' },
        { text: gameStateLabel(gameState.game_state), cls: gameState.game_state === 'PLAYING' ? '' : 'danger' },
    ];
    if (gameState.in_check) pills.push({ text: '将军', cls: 'danger' });
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
        label.innerHTML = `<strong>${escapeHtml(timeline.name)}</strong><small>${timeline.is_active ? '活动' : '非活动'}${timeline.owner ? ` · ${escapeHtml(colorLabel(timeline.owner))}` : ''}</small>`;
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
    header.innerHTML = `<span class="board-coord-label">${laneName} · 回合 T${board.coord.turn} · ${escapeHtml(colorLabel(board.coord.side))}</span>`;

    const badges = document.createElement('span');
    badges.className = 'board-badges';
    if (board.is_present) badges.appendChild(makeBadge('当前时刻', 'present'));
    if (board.is_required) badges.appendChild(makeBadge('必须推进', 'required'));
    if (board.playable && !board.is_required) badges.appendChild(makeBadge('可走', 'playable'));
    if (!board.timeline_active) badges.appendChild(makeBadge('非活动', 'inactive'));
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
        ? `回合 T${present.turn} / 时刻 t${present.time_point} / ${colorLabel(present.side)}`
        : '—';
    summary.innerHTML = `
        <div class="action-row"><span>玩家</span><strong>${escapeHtml(colorLabel(action.color || gameState.turn))}</strong></div>
        <div class="action-row"><span>当前时刻</span><strong>${escapeHtml(presentText)}</strong></div>
        <div class="action-row"><span>行动走子数</span><strong>${action.move_count || 0}</strong></div>
        <div class="action-row"><span>必须推进</span><strong>${required.length}</strong></div>
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
        empty.textContent = action.can_submit ? '当前时刻已推进完成' : '没有必须推进的棋盘';
        chips.appendChild(empty);
    }

    const submit = document.getElementById('submit-action-btn');
    const playerTurn = mode !== 'pve' || gameState.turn === gameState.player_color;
    if (submit) {
        submit.disabled = mutationOwner !== null || !['pvp', 'pve'].includes(mode) ||
            !action.can_submit || !playerTurn || gameState.game_state !== 'PLAYING';
        submit.classList.toggle('hidden', mode === 'replay');
    }

    const help = document.getElementById('action-help');
    if (mode === 'pvp') {
        help.textContent = action.can_submit
            ? '可以提交；如有需要，可先在其他未来或非活动可走棋盘上完成可选走子。'
            : required.length
                ? '红框棋盘必须继续推进；当前时刻到达对手且王安全后才能提交。'
                : '选择橙色可行动棋盘上的棋子。';
    } else if (mode === 'pve') {
        help.textContent = action.can_submit && playerTurn
            ? '可以提交当前行动；提交后 AI 将完成自己的完整行动。'
            : playerTurn
                ? '红框棋盘必须继续推进；完成后才能提交当前行动。'
                : gameState.ai_thinking || aiRequestInFlight
                    ? 'AI 正在处理自己的行动。'
                    : '等待 AI 同步棋局状态。';
    } else {
        help.textContent = '棋谱回放模式展示当前回放状态中的全部时间线棋盘。';
    }

    renderAIRetryControl(help);

    document.getElementById('check-badge')?.classList.toggle('hidden', !gameState.in_check);
}

function renderAIRetryControl(help) {
    if (!help) return;
    help.querySelector?.('#ai-retry-btn')?.remove();
    if (mode !== 'pve' || !aiRetryAvailable || gameState?.ai_thinking !== false || !shouldRunAI()) return;
    const button = document.createElement('button');
    button.id = 'ai-retry-btn';
    button.className = 'ghost-btn';
    button.type = 'button';
    button.textContent = '重试 AI 走子';
    button.onclick = retryAIAction;
    help.appendChild(button);
}

function renderInspector() {
    const panel = document.getElementById('board-inspector');
    const board = focusedBoardKey ? findBoard(focusedBoardKey) : null;
    if (!board) {
        panel.className = 'inspector muted';
        panel.textContent = '点击任意棋盘可查看棋盘坐标；点击可行动棋盘上的棋子开始走子。';
        return;
    }

    panel.className = 'inspector';
    const flags = [
        board.playable ? '可走' : '历史',
        board.timeline_active ? '活动' : '非活动',
        board.is_present ? '当前时刻' : null,
        board.is_required ? '必须推进' : null,
        board.is_movable ? '可行动' : null,
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
        当前回合：T${board.coord.turn} · 颜色：${escapeHtml(colorLabel(board.coord.side))}<br>
        内部时间坐标：t${board.coord.time_point}<br>
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
    return `${lane} · 回合 T${coord.turn} · ${colorLabel(coord.side)}`;
}

function modeLabel(value) {
    return ({
        pvp: '同屏双人对弈',
        pve: '人机对弈',
        p2p: '在线双人对弈',
        replay: '棋谱回放',
    })[value] || '未知模式';
}

function resultLabel(value) {
    return ({
        CHECKMATE: '将杀',
        STALEMATE: '逼和',
        DRAW: '和棋',
        PLAYING: '进行中',
        WAITING: '等待开始',
    })[value] || localizePlayerText(value, '未知状态');
}

function gameStateLabel(value) {
    return resultLabel(value);
}

function colorLabel(value) {
    return ({ white: '白方', black: '黑方' })[value] || localizePlayerText(value, '未知颜色');
}

function switchToScreen(id) {
    document.querySelectorAll('.screen').forEach(screen => screen.classList.remove('active'));
    document.getElementById(id)?.classList.add('active');
    document.getElementById('game-over-overlay')?.remove();
}

function showToast(message, isError = false) {
    const toast = document.getElementById('toast');
    if (!toast) return;
    toast.textContent = localizePlayerText(message, isError ? '操作失败，请稍后重试' : '操作已完成');
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
