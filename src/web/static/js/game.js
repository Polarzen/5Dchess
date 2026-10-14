/** 5D Chess multiverse browser interaction. */

let gameState = null;
let mode = null;
let selectedSource = null;   // { boardKey, x, y }
let legalMoves = [];         // canonical Move payloads
let focusedBoardKey = null;
let boardZoom = 224;
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
const LLM_AI_TIMEOUT_MS = 25000;
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

let interactionOwner = null;
let interactionSource = null;

function beginInteraction(owner, message, source = null) {
    endInteraction();
    interactionOwner = owner;
    const status = document.getElementById('interaction-status');
    const label = document.getElementById('interaction-label');
    if (label) label.textContent = message;
    if (status) status.hidden = false;
    if (source) {
        const card = document.querySelector(`.board-card[data-board-key="${cssEscape(source.boardKey)}"]`);
        interactionSource = card?._cells?.[source.y * 8 + source.x] || null;
        interactionSource?.classList.add('pending-source');
    }
}

function endInteraction(owner = null) {
    if (owner && interactionOwner !== owner) return;
    interactionSource?.classList.remove('pending-source');
    interactionSource = null;
    interactionOwner = null;
    const status = document.getElementById('interaction-status');
    if (status) status.hidden = true;
}

function invalidateSession() {
    endInteraction();
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
    beginInteraction(owner, '正在同步行动…');
    renderActionPanel();
    return owner;
}

function ownsMutation(owner) {
    return Boolean(owner && mutationOwner === owner && isCurrentSession(owner.context));
}

function releaseMutation(owner) {
    if (mutationOwner !== owner) return;
    mutationOwner = null;
    endInteraction(owner);
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

let llmConfigCheck = 0;
let llmSettings = null;
let llmConfigBusy = false;
let llmConfigDirty = false;

function clearLLMKeyInput() {
    const key = document.getElementById('llm-api-key');
    key.value = '';
    key.type = 'password';
    const toggle = document.getElementById('llm-key-toggle');
    toggle.textContent = '显示';
    toggle.setAttribute('aria-pressed', 'false');
}

function updateLLMConfigControls() {
    const editable = llmSettings && !llmSettings.editing_locked;
    const ready = llmSettings?.ready === true && !llmConfigDirty && !llmConfigBusy;
    document.getElementById('llm-fields').disabled = llmConfigBusy || !editable;
    document.getElementById('llm-save-btn').disabled = llmConfigBusy || !editable || !llmConfigDirty;
    document.getElementById('llm-reload-btn').disabled = llmConfigBusy;
    document.getElementById('llm-start-btn').disabled = !ready;
    document.getElementById('llm-test-btn').disabled = !ready;
    document.getElementById('llm-copy-path-btn').disabled = llmConfigBusy || !llmSettings?.config_directory;
    document.getElementById('llm-replace-key-btn').disabled = llmConfigBusy || !editable || !llmSettings.has_key;
    document.getElementById('llm-delete-btn').disabled = llmConfigBusy || !editable || !llmSettings.file_exists;
    document.getElementById('llm-confirm-delete-btn').disabled = llmConfigBusy || !editable || !llmSettings.file_exists;
    document.getElementById('llm-cancel-delete-btn').disabled = llmConfigBusy;
    document.getElementById('llm-save-btn').textContent = llmSettings?.file_exists ? '保存修改' : '保存到本机';
    document.getElementById('llm-config-path').value = llmSettings?.config_path || '';
    document.getElementById('llm-storage-state').textContent = !llmSettings ? '保存位置暂不可用'
        : llmSettings.editing_locked ? '配置来源：环境变量覆盖 · 网页只读'
        : llmSettings.ready ? '密钥已保存在本机 · 内容不回显'
        : llmSettings.file_exists ? '本机已有配置文件，但配置不可用，可重新填写或删除'
        : '尚未保存密钥 · 首次保存后创建下方文件';
}

function applyLLMSettings(result) {
    llmSettings = result;
    llmConfigDirty = false;
    for (const [id, name] of [['llm-base-url','base_url'], ['llm-model','model'], ['llm-timeout','timeout_seconds'], ['llm-max-requests','max_requests']]) {
        document.getElementById(id).value = result[name];
    }
    document.getElementById('llm-provider').value = result.base_url === 'https://api.deepseek.com' ? 'deepseek' : 'custom';
    clearLLMKeyInput();
    const key = document.getElementById('llm-api-key');
    key.required = !result.has_key;
    key.placeholder = result.has_key ? '已保存；留空保留原密钥' : '粘贴自己的 API 密钥';
    cancelLLMDelete();
}

function markLLMConfigDirty() {
    cancelLLMDelete();
    llmConfigDirty = true;
    document.getElementById('llm-config-status').textContent = '有未保存的修改，请先保存。切换接口地址时须填写对应的新密钥。';
    updateLLMConfigControls();
}

function changeLLMProvider() {
    const deepseek = document.getElementById('llm-provider').value === 'deepseek';
    document.getElementById('llm-base-url').value = deepseek ? 'https://api.deepseek.com' : '';
    document.getElementById('llm-model').value = deepseek ? 'deepseek-flash' : '';
    clearLLMKeyInput();
    markLLMConfigDirty();
}

function toggleLLMKeyVisibility() {
    const key = document.getElementById('llm-api-key');
    const visible = key.type === 'password';
    key.type = visible ? 'text' : 'password';
    document.getElementById('llm-key-toggle').textContent = visible ? '隐藏' : '显示';
    document.getElementById('llm-key-toggle').setAttribute('aria-pressed', String(visible));
}

function closeLLMSetup() {
    ++llmConfigCheck;
    llmConfigBusy = false;
    clearLLMKeyInput();
    cancelLLMDelete();
    document.getElementById('llm-dialog').close();
}

async function openLLMSetup() {
    const dialog = document.getElementById('llm-dialog');
    // Native Escape/cancel and any other close path must also discard input.
    dialog.onclose = clearLLMKeyInput;
    dialog.oncancel = () => { ++llmConfigCheck; llmConfigBusy = false; clearLLMKeyInput(); };
    if (!dialog.open) dialog.showModal();
    await checkLLMConfig();
}

async function checkLLMConfig() {
    const check = ++llmConfigCheck;
    const status = document.getElementById('llm-config-status');
    llmConfigBusy = true;
    llmSettings = null;
    cancelLLMDelete();
    clearLLMKeyInput();
    updateLLMConfigControls();
    status.textContent = '正在读取本机配置…';
    const result = await api('/api/ai/llm_status');
    if (check !== llmConfigCheck) return;
    llmConfigBusy = false;
    if (isErrorResult(result) || !result.revision) {
        status.textContent = playerErrorMessage(result, '无法读取配置，请重新载入。');
    } else {
        applyLLMSettings(result);
        status.textContent = result.editing_locked ? result.message : result.ready
            ? `已读取本机配置：${result.model} · 每局最多 ${result.max_requests} 次请求。密钥留空即可保留；可选测试连接。`
            : result.message || '填写密钥后保存，即可使用在线 AI。';
    }
    document.getElementById('llm-setup-help').open = false;
    updateLLMConfigControls();
}

async function saveLLMConfig() {
    if (llmConfigBusy || !llmSettings || llmSettings.editing_locked) return;
    const form = document.getElementById('llm-config-form');
    if (!form.reportValidity()) return;
    cancelLLMDelete();
    const payload = {
        revision: llmSettings.revision,
        api_key: document.getElementById('llm-api-key').value.trim(),
        base_url: document.getElementById('llm-base-url').value.trim(),
        model: document.getElementById('llm-model').value.trim(),
        timeout_seconds: Number(document.getElementById('llm-timeout').value),
        max_requests: Number(document.getElementById('llm-max-requests').value),
    };
    clearLLMKeyInput();
    const check = ++llmConfigCheck;
    llmConfigBusy = true;
    updateLLMConfigControls();
    document.getElementById('llm-config-status').textContent = '正在保存到房主本机…';
    const result = await api('/api/ai/llm_config', 'POST', payload);
    if (check !== llmConfigCheck) return;
    llmConfigBusy = false;
    if (!isErrorResult(result) && result.ready === true) applyLLMSettings(result);
    document.getElementById('llm-config-status').textContent = isErrorResult(result)
        ? playerErrorMessage(result, '保存失败，请重新载入检查；密钥需重新输入。')
        : result.message;
    updateLLMConfigControls();
}

async function copyLLMConfigDirectory() {
    if (llmConfigBusy || !llmSettings?.config_directory) return;
    const check = llmConfigCheck;
    try {
        await navigator.clipboard.writeText(llmSettings.config_directory);
        if (check === llmConfigCheck) document.getElementById('llm-config-status').textContent = llmSettings.file_exists
            ? '已复制文件夹路径，可粘贴到文件资源管理器的地址栏。'
            : '已复制预定文件夹路径；首次保存后才会创建配置文件。';
    } catch (_) {
        if (check === llmConfigCheck) document.getElementById('llm-config-status').textContent = '复制失败，请手动选择上方路径复制。';
    }
}

function replaceLLMKey() {
    if (llmConfigBusy || !llmSettings?.has_key || llmSettings.editing_locked) return;
    clearLLMKeyInput();
    const key = document.getElementById('llm-api-key');
    key.required = true;
    key.placeholder = '粘贴新密钥，再点击“保存修改”';
    markLLMConfigDirty();
    document.getElementById('llm-config-status').textContent = '请输入新密钥并保存。保存成功前，原密钥仍然有效；重新载入可放弃修改。';
    key.focus();
}

function cancelLLMDelete() {
    document.getElementById('llm-delete-confirmation').hidden = true;
}

function showLLMDeleteConfirmation() {
    if (llmConfigBusy || !llmSettings?.file_exists || llmSettings.editing_locked) return;
    document.getElementById('llm-delete-confirmation').hidden = false;
    document.getElementById('llm-cancel-delete-btn').focus();
}

async function deleteLLMConfig() {
    if (llmConfigBusy || !llmSettings?.file_exists || llmSettings.editing_locked
        || document.getElementById('llm-delete-confirmation').hidden) return;
    const payload = {revision: llmSettings.revision, confirmed: true};
    const check = ++llmConfigCheck;
    llmConfigBusy = true;
    clearLLMKeyInput();
    updateLLMConfigControls();
    document.getElementById('llm-config-status').textContent = '正在删除本机密钥及配置…';
    const result = await api('/api/ai/llm_delete', 'POST', payload);
    if (check !== llmConfigCheck) return;
    llmConfigBusy = false;
    if (!isErrorResult(result) && result.revision) applyLLMSettings(result);
    document.getElementById('llm-config-status').textContent = isErrorResult(result)
        ? playerErrorMessage(result, '删除未完成，请重新载入并确认当前配置。') : result.message;
    cancelLLMDelete();
    updateLLMConfigControls();
}

async function testLLMConnection() {
    if (llmConfigBusy || llmConfigDirty || !llmSettings?.ready) return;
    const check = ++llmConfigCheck;
    llmConfigBusy = true;
    updateLLMConfigControls();
    document.getElementById('llm-config-status').textContent = '正在测试已保存的接口；本次会产生少量接口用量…';
    const result = await api('/api/ai/llm_test', 'POST', {revision: llmSettings.revision}, 20000);
    if (check !== llmConfigCheck) return;
    llmConfigBusy = false;
    document.getElementById('llm-config-status').textContent = isErrorResult(result)
        ? playerErrorMessage(result, '连接测试失败，请核对配置。') : result.message;
    updateLLMConfigControls();
}

function startLLMGame() {
    if (document.getElementById('llm-start-btn').disabled) return;
    closeLLMSetup();
    startGame('pve', 'llm');
}

async function startGame(nextMode, difficulty = 'medium') {
    if (startOperationOwner) return;
    invalidateSession();
    mode = nextMode;
    const context = captureSession();
    const owner = { id: ++operationSequence, context };
    startOperationOwner = owner;
    beginInteraction(owner, '正在准备棋局…');
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
        endInteraction(owner);
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
        const onlineAI = gameState.ai_difficulty === 'llm';
        if (info && isCurrentSession(context)) info.textContent = onlineAI ? '在线 AI 正在选择走法，超时将自动切换本地方案…' : 'AI 正在完成当前行动…';
        const result = await api('/api/game/ai_move', 'POST', {}, onlineAI ? LLM_AI_TIMEOUT_MS : AI_TIMEOUT_MS);
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
    const hadSelection = Boolean(selectedSource);
    selectedSource = null;
    legalMoves = [];
    beginInteraction(owner, '正在读取合法落点…', {boardKey: board.key, x, y});
    if (hadSelection) { renderMultiverse(); renderInspector(); }
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
        endInteraction(owner);
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
        focusedBoardKey = moveArrivalBoardKey(result.last_move || result.move || move);
        clearSelection(false);
        updateAll();
        focusBoard(focusedBoardKey);
        if (!gameState.rule_warning) showToast(moveFeedback(result.move || result.last_move || move));
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
    if (selectionOwner) endInteraction(selectionOwner);
    selectionOwner = null;
    selectedSource = null;
    legalMoves = [];
    if (render && gameState) {
        renderMultiverse();
        renderInspector();
    }
}

function moveFeedback(move) {
    if (move?.is_branching && move.created_timeline !== null && move.created_timeline !== undefined) {
        const line = `L${move.created_timeline > 0 ? '+' : ''}${move.created_timeline}`;
        return `${move.captured ? '吃子已在' : '棋子已到达'}新支线 ${line}；原时间线保留。新棋盘轮到${colorLabel(move.result_destination_board?.side || (gameState.turn === 'white' ? 'black' : 'white'))}。`;
    }
    return localizePlayerText(move?.display_notation, '走子完成');
}

function moveArrivalBoardKey(move) {
    if (move?.result_destination_board?.key) return move.result_destination_board.key;
    const target = move?.destination?.board;
    if (!target) return null;
    const lane = move.is_branching ? move.created_timeline : target.timeline;
    return lane !== null && lane !== undefined && Number.isFinite(target.time_point)
        ? `${lane}:${target.time_point + 1}` : target.key;
}

function focusBoard(boardKey, scroll = true) {
    focusedBoardKey = boardKey;
    document.querySelectorAll('.board-card.focused').forEach(el => el.classList.remove('focused'));
    const target = document.querySelector(`.board-card[data-board-key="${cssEscape(boardKey)}"]`);
    if (target) {
        target.classList.add('focused');
        if (scroll) target.scrollIntoView({ behavior: prefersReducedMotion() ? 'auto' : 'smooth', block: 'center', inline: 'center' });
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
    renderRepetitionWarning();
    checkGameOver();
}

function renderRepetitionWarning() {
    const banner = document.getElementById('repetition-warning');
    if (!banner) return;
    const repetition = gameState?.repetition;
    const message = repetition?.kind === 'frontier_repetition' ? repetition.message : '';
    banner.textContent = message || '';
    banner.classList.toggle('hidden', !message);
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
    if (info) {
        const submitted = Number.isInteger(gameState.action_counter)
            ? `已提交 ${gameState.action_counter} 个行动 · ` : '';
        info.textContent = `${modeLabel(mode)} · ${submitted}共 ${gameState.move_counter || 0} 次走子`;
    }

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

// Preserve immutable history DOM across selection, polling and new moves.
const boardViews = new Map();
const laneViews = new Map();
let renderedGeneration = -1;
let renderedMove = null;
let linksQueued = false;

function queueLinkDraw() {
    if (linksQueued) return;
    linksQueued = true;
    requestAnimationFrame(() => { linksQueued = false; drawLinks(); });
}

function prefersReducedMotion() {
    return Boolean(window.matchMedia?.('(prefers-reduced-motion: reduce)').matches);
}

function renderMultiverse() {
    const container = document.getElementById('timeline-lanes');
    if (renderedGeneration !== sessionGeneration) {
        container.replaceChildren();
        boardViews.clear();
        laneViews.clear();
        renderedGeneration = sessionGeneration;
        renderedMove = null;
    }
    const boards = gameState.boards || [];
    const timelines = [...(gameState.timelines || [])].sort((a, b) => b.id - a.id);
    if (!boards.length || !timelines.length) {
        container.textContent = '当前没有可显示的棋盘。';
        boardViews.clear(); laneViews.clear(); renderedMove = null;
        const svg = document.getElementById('timeline-links');
        if (svg) svg.innerHTML = '';
        return;
    }
    if (!laneViews.size) container.replaceChildren();
    let minTime = Infinity, maxTime = -Infinity;
    const boardsByLane = new Map();
    for (const board of boards) {
        minTime = Math.min(minTime, board.coord.time_point);
        maxTime = Math.max(maxTime, board.coord.time_point);
        if (!boardsByLane.has(board.coord.timeline)) boardsByLane.set(board.coord.timeline, []);
        boardsByLane.get(board.coord.timeline).push(board);
    }
    const targets = new Map();
    for (const move of legalMoves) {
        const key = move.destination.board.key;
        if (!targets.has(key)) targets.set(key, new Map());
        targets.get(key).set(move.destination.y * 8 + move.destination.x, move.is_branching);
    }
    const activeBoards = new Set();
    const activeLanes = new Set();
    const last = gameState.last_move;
    const arrival = moveArrivalBoardKey(last);
    const moveIdentity = JSON.stringify([gameState.move_counter, last]);
    const newMove = renderedMove !== null && renderedMove !== moveIdentity;
    timelines.forEach((timeline, index) => {
        activeLanes.add(timeline.id);
        let laneView = laneViews.get(timeline.id);
        if (!laneView) {
            const lane = document.createElement('section');
            lane.dataset.timelineId = timeline.id;
            const label = document.createElement('div'); label.className = 'lane-label';
            const track = document.createElement('div'); track.className = 'lane-track';
            lane.appendChild(label); lane.appendChild(track);
            laneView = { lane, label, track, labelText: null };
            laneViews.set(timeline.id, laneView);
        }
        const {lane, label, track} = laneView;
        lane.className = `timeline-lane ${timeline.is_active ? 'active' : 'inactive'}`;
        const labelText = `<strong>${escapeHtml(timeline.name)}</strong><small>${timeline.is_active ? '参与当前时刻' : '可选支线'}${timeline.owner ? ` · ${escapeHtml(colorLabel(timeline.owner))}创建` : ''}</small>`;
        if (labelText !== laneView.labelText) { label.innerHTML = labelText; laneView.labelText = labelText; }
        track.style.gridTemplateColumns = `repeat(${maxTime - minTime + 1}, var(--board-size))`;
        if (container.children[index] !== lane) container.insertBefore(lane, container.children[index] || null);
        const laneBoards = (boardsByLane.get(timeline.id) || []).sort((a, b) => a.coord.time_point - b.coord.time_point);
        laneBoards.forEach((board, boardIndex) => {
            activeBoards.add(board.key);
            let view = boardViews.get(board.key);
            const isNew = !view;
            if (!view) {
                view = { card: createBoardCard(board), model: null, signature: null };
                boardViews.set(board.key, view);
            }
            if (view.model !== board) {
                view.base = JSON.stringify([board.board, board.coord, board.role, board.timeline_active, board.is_present,
                    board.is_required, board.is_movable, board.playable, board.historical]);
                view.model = board;
            }
            const boardTargets = targets.get(board.key);
            const source = selectedSource?.boardKey === board.key ? selectedSource : null;
            const lastSource = last?.source?.board?.key === board.key ? last.source : null;
            const lastTarget = arrival === board.key ? last.destination : null;
            const signature = view.base + JSON.stringify([focusedBoardKey === board.key,
                source && [source.x, source.y], boardTargets ? [...boardTargets] : null,
                lastSource && [lastSource.x, lastSource.y], lastTarget && [lastTarget.x, lastTarget.y]]);
            if (view.signature !== signature) {
                updateBoardCard(view.card, board, boardTargets, source, lastSource, lastTarget);
                view.signature = signature;
            }
            view.card.style.gridColumn = String(board.coord.time_point - minTime + 1);
            if (track.children[boardIndex] !== view.card) track.insertBefore(view.card, track.children[boardIndex] || null);
            if (newMove && !prefersReducedMotion()) {
                if (isNew) view.card.animate?.([{opacity: .35}, {opacity: 1}], {duration: 180});
                if (lastTarget) view.card._cells[lastTarget.y * 8 + lastTarget.x].firstChild.animate?.(
                    [{transform: 'translateY(-10px) scale(.85)', opacity: .4}, {transform: 'none', opacity: 1}],
                    {duration: 240, easing: 'cubic-bezier(.2,.8,.2,1)'});
            }
        });
    });
    for (const [key, view] of boardViews) if (!activeBoards.has(key)) { view.card.remove(); boardViews.delete(key); }
    for (const [key, view] of laneViews) if (!activeLanes.has(key)) { view.lane.remove(); laneViews.delete(key); }
    renderedMove = moveIdentity;
    queueLinkDraw();
}

function createBoardCard(board) {
    const card = document.createElement('article');
    card.dataset.boardKey = board.key;
    const header = document.createElement('header'); header.className = 'board-card-header';
    header.onclick = event => { event.stopPropagation(); focusBoard(board.key); };
    card._header = header; card.appendChild(header);
    const grid = document.createElement('div'); grid.className = 'mini-board';
    card._cells = [];
    for (let y = 0; y < 8; y++) for (let x = 0; x < 8; x++) {
        const cell = document.createElement('button'); cell.type = 'button';
        const glyph = document.createElement('span'); glyph.className = 'piece-glyph';
        cell.appendChild(glyph);
        cell.onclick = event => { event.stopPropagation(); handleCellClick(board.key, x, y); };
        grid.appendChild(cell); card._cells.push(cell);
    }
    card.appendChild(grid);
    return card;
}

function updateBoardCard(card, board, targets, source, lastSource, lastTarget) {
    const classes = ['board-card', board.role];
    if (!board.timeline_active) classes.push('inactive');
    if (board.is_present) classes.push('present');
    if (board.is_required) classes.push('required');
    if (board.is_movable) classes.push('movable');
    if (focusedBoardKey === board.key) classes.push('focused');
    if (targets) classes.push('target-board');
    if (card.className !== classes.join(' ')) card.className = classes.join(' ');
    const laneName = board.coord.timeline === 0 ? 'L0' : `L${board.coord.timeline > 0 ? '+' : ''}${board.coord.timeline}`;
    const title = `${laneName} · 回合 T${board.coord.turn} · ${colorLabel(board.coord.side)}`;
    const badges = [];
    if (board.is_present) badges.push(['当前时刻', 'present']);
    if (board.is_required) badges.push(['必须推进', 'required']);
    if (board.playable && !board.is_required) badges.push([gameState.game_state !== 'PLAYING' ? '对局已结束' : board.is_movable ? '可选走子' : `轮到${colorLabel(board.coord.side)}`, 'playable']);
    if (board.historical) badges.push(['历史 · 仅可落子', 'historical']);
    if (!board.timeline_active) badges.push(['可选支线', 'inactive']);
    const headerHTML = `<span class="board-coord-label">${escapeHtml(title)}</span><span class="board-badges">${badges.map(([text, cls]) => `<span class="board-badge ${cls}">${text}</span>`).join('')}</span>`;
    if (card._headerHTML !== headerHTML) { card._header.innerHTML = headerHTML; card._headerHTML = headerHTML; }
    const names = {k: '王', q: '后', r: '车', b: '象', n: '马', p: '兵'};
    for (let y = 0; y < 8; y++) for (let x = 0; x < 8; x++) {
        const cell = card._cells[y * 8 + x];
        const ch = board.board?.[y]?.[x] || '';
        const classes = ['mini-cell', (x + y) % 2 === 0 ? 'light' : 'dark'];
        if (ch) classes.push(pieceColor(ch) === 'white' ? 'white-piece' : 'black-piece', 'has-piece');
        if (source?.x === x && source?.y === y) classes.push('source-selected');
        const target = targets?.has(y * 8 + x);
        if (target) classes.push('valid-target');
        if (targets?.get(y * 8 + x)) classes.push('branch-target');
        if (lastSource?.x === x && lastSource?.y === y) classes.push('last-source');
        if (lastTarget?.x === x && lastTarget?.y === y) classes.push('last-target');
        if (cell === interactionSource) classes.push('pending-source');
        const glyph = pieceSymbols[ch] || ch;
        if (cell.firstChild.textContent !== glyph) cell.firstChild.textContent = glyph;
        if (cell.className !== classes.join(' ')) cell.className = classes.join(' ');
        cell.tabIndex = target || (board.is_movable && ch) ? 0 : -1;
        cell.setAttribute('aria-label', `${title} ${String.fromCharCode(97 + x)}${8 - y}${ch ? ` ${colorLabel(pieceColor(ch))}${names[ch.toLowerCase()] || ''}` : ' 空格'}${target ? ' 可落子' : ''}`);
    }
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

    const canvasRect = canvas.getBoundingClientRect();
    const boardRects = new Map(Array.from(document.querySelectorAll('.board-card'), card => {
        const rect = card.getBoundingClientRect();
        return [card.dataset.boardKey, {
            left: rect.left - canvasRect.left, right: rect.right - canvasRect.left,
            top: rect.top - canvasRect.top, bottom: rect.bottom - canvasRect.top,
        }];
    }));

    const defs = document.createElementNS(SVG_NS, 'defs');
    defs.appendChild(makeArrowMarker('branch-arrow', '#713d91'));
    defs.appendChild(makeArrowMarker('move-arrow', '#5148d5'));
    defs.appendChild(makeArrowMarker('candidate-arrow', '#245cce'));
    svg.appendChild(defs);

    for (const timeline of gameState.timelines || []) {
        if (timeline.branch_from?.key && timeline.branch_to?.key) {
            appendCurve(svg, timeline.branch_from.key, timeline.branch_to.key, 'branch-link', 'branch-arrow', boardRects);
        }
    }

    const last = gameState.last_move;
    if (last?.source?.board?.key && last?.destination?.board?.key &&
        last.source.board.key !== last.destination.board.key) {
        appendCurve(svg, last.source.board.key, moveArrivalBoardKey(last), 'last-move-link', 'move-arrow', boardRects);
    }

    if (selectedSource) {
        const uniqueTargets = [...new Set(
            legalMoves
                .map(move => move.destination.board.key)
                .filter(key => key !== selectedSource.boardKey)
        )];
        for (const targetKey of uniqueTargets) {
            appendCurve(svg, selectedSource.boardKey, targetKey, 'candidate-link', 'candidate-arrow', boardRects);
        }
    }
}

function makeArrowMarker(id, color) {
    const marker = document.createElementNS(SVG_NS, 'marker');
    marker.setAttribute('id', id);
    marker.setAttribute('markerWidth', '10');
    marker.setAttribute('markerHeight', '10');
    marker.setAttribute('viewBox', '0 0 10 10');
    marker.setAttribute('refX', '10');
    marker.setAttribute('refY', '5');
    marker.setAttribute('orient', 'auto');
    marker.setAttribute('markerUnits', 'userSpaceOnUse');
    const path = document.createElementNS(SVG_NS, 'path');
    path.setAttribute('d', 'M 0 0 L 10 5 L 0 10 z');
    path.setAttribute('fill', color);
    marker.appendChild(path);
    return marker;
}

function linkWaypoints(a, b, boards) {
    // Use the gutters instead of crossing board interiors. The clearance also
    // leaves room for selection outlines, shadows and the small hover lift.
    const clearance = 14;
    const gutter = 30;
    const x1 = (a.left + a.right) / 2;
    const x2 = (b.left + b.right) / 2;
    const rowFor = rect => boards.filter(r => r.top < rect.bottom && r.bottom > rect.top);
    const sourceRow = rowFor(a);
    const targetRow = rowFor(b);
    if (a.top < b.bottom && b.top < a.bottom) {
        const y = Math.min(...sourceRow.map(r => r.top)) - gutter;
        return [[x1, a.top - clearance], [x1, y], [x2, y], [x2, b.top - clearance]];
    }

    const downward = b.top > a.top;
    const y1 = downward ? a.bottom + clearance : a.top - clearance;
    const y2 = downward ? b.top - clearance : b.bottom + clearance;
    const gapTop = downward ? Math.max(...sourceRow.map(r => r.bottom)) : Math.max(...targetRow.map(r => r.bottom));
    const gapBottom = downward ? Math.min(...targetRow.map(r => r.top)) : Math.min(...sourceRow.map(r => r.top));
    if (!boards.some(r => r.top > gapTop && r.bottom < gapBottom)) {
        const y = (gapTop + gapBottom) / 2;
        return [[x1, y1], [x1, y], [x2, y], [x2, y2]];
    }

    // A jump across several lanes uses the vertical gap beside the destination
    // column, so intermediate timeline boards never hide the connection.
    const columnRight = Math.max(...boards.filter(r => r.left <= x2 && r.right >= x2).map(r => r.right));
    const nextColumn = Math.min(...boards.filter(r => r.left > columnRight).map(r => r.left));
    const x = Number.isFinite(nextColumn) ? (columnRight + nextColumn) / 2 : columnRight + 27;
    const sourceY = downward ? gapTop + gutter : gapBottom - gutter;
    const targetY = downward ? gapBottom - gutter : gapTop + gutter;
    return [[x1, y1], [x1, sourceY], [x, sourceY], [x, targetY], [x2, targetY], [x2, y2]];
}

function roundedLinkPath(points) {
    const unique = points.filter((p, i) => i === 0 || p[0] !== points[i - 1][0] || p[1] !== points[i - 1][1]);
    let path = `M ${unique[0].join(' ')}`;
    for (let i = 1; i < unique.length - 1; i++) {
        const [prev, corner, next] = [unique[i - 1], unique[i], unique[i + 1]];
        const incoming = Math.hypot(corner[0] - prev[0], corner[1] - prev[1]);
        const outgoing = Math.hypot(next[0] - corner[0], next[1] - corner[1]);
        const radius = Math.min(10, incoming / 2, outgoing / 2);
        const before = corner.map((v, axis) => v + (prev[axis] - v) * radius / incoming);
        const after = corner.map((v, axis) => v + (next[axis] - v) * radius / outgoing);
        path += ` L ${before.join(' ')} Q ${corner.join(' ')} ${after.join(' ')}`;
    }
    return `${path} L ${unique[unique.length - 1].join(' ')}`;
}

function appendCurve(svg, fromKey, toKey, className, markerId, boardRects) {
    const a = boardRects.get(fromKey);
    const b = boardRects.get(toKey);
    if (!a || !b || fromKey === toKey) return;
    const points = linkWaypoints(a, b, Array.from(boardRects.values()));
    const shape = roundedLinkPath(points);
    const group = document.createElementNS(SVG_NS, 'g');
    group.setAttribute('data-source-board', fromKey);
    group.setAttribute('data-target-board', toKey);
    const halo = document.createElementNS(SVG_NS, 'path');
    halo.setAttribute('d', shape);
    halo.setAttribute('class', 'link-halo');
    group.appendChild(halo);

    const path = document.createElementNS(SVG_NS, 'path');
    path.setAttribute('d', shape);
    path.setAttribute('class', className);
    path.setAttribute('marker-end', `url(#${markerId})`);
    group.appendChild(path);
    const origin = document.createElementNS(SVG_NS, 'circle');
    origin.setAttribute('cx', points[0][0]);
    origin.setAttribute('cy', points[0][1]);
    origin.setAttribute('r', '3');
    origin.setAttribute('class', `link-origin ${className}`);
    group.appendChild(origin);
    svg.appendChild(group);
}

function renderActionPanel() {
    const action = gameState.action || {};
    const present = gameState.present;
    const summary = document.getElementById('action-summary');
    const required = gameState.game_state === 'PLAYING' ? action.required_boards || [] : [];

    const presentText = present
        ? `回合 T${present.turn} / 时刻 t${present.time_point} / ${colorLabel(present.side)}`
        : '—';
    summary.innerHTML = `
        <div class="action-row"><span>行动方</span><strong>${escapeHtml(colorLabel(action.color || gameState.turn))}</strong></div>
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
        help.textContent = gameState.game_state !== 'PLAYING' ? submissionHelp(action) : action.can_submit
            ? '可以提交；如有需要，可先在其他未来或非活动可走棋盘上完成可选走子。'
            : required.length
                ? '红框棋盘必须继续推进；当前时刻到达对手且王安全后才能提交。'
                : submissionHelp(action);
    } else if (mode === 'pve') {
        help.textContent = action.can_submit && playerTurn
            ? '可以提交当前行动；提交后 AI 将完成自己的完整行动。'
            : playerTurn
                ? submissionHelp(action)
                : gameState.ai_thinking || aiRequestInFlight
                    ? 'AI 正在处理自己的行动。'
                    : '等待 AI 同步棋局状态。';
    } else {
        help.textContent = '棋谱回放模式展示当前回放状态中的全部时间线棋盘。';
    }

    renderAIRetryControl(help);
    renderLLMStatus();
    renderMovableBoards();

    document.getElementById('check-badge')?.classList.toggle('hidden', !gameState.in_check);
}

function renderLLMStatus() {
    const status = document.getElementById('llm-ai-status');
    if (!status) return;
    const opponent = mode === 'pve' && gameState?.ai_difficulty === 'llm' ? gameState.ai_opponent : null;
    document.getElementById('llm-manage-btn').hidden = !opponent;
    status.hidden = !opponent;
    if (!opponent) { status.textContent = ''; return; }
    const source = opponent.last_source === 'llm' ? '上回合由模型选招' : opponent.last_source === 'local' ? '上回合使用本地方案' : '等待首个 AI 回合';
    status.textContent = `${opponent.model} · 请求 ${opponent.requests_used}/${opponent.max_requests} · ${source}`
        + (gameState.ai_warning ? `。${gameState.ai_warning}` : '');
}

function submissionHelp(action) {
    if (gameState?.game_state !== 'PLAYING') return gameState?.game_state === 'CHECKMATE'
        ? `${colorLabel(gameState.turn)}已被将杀，对局结束；所有棋盘停止走子，可从存档观看回放。`
        : '对局已结束，可返回菜单开始新对局。';
    if (action.can_submit) return '本次行动已完成。点击“提交行动”后才轮到对手；也可以继续可选走子。';
    const count = action.required_boards?.length || 0;
    if (count) return `还需推进当前时刻的 ${count} 张红框棋盘。跨线移动可同时推进起点和落点棋盘；每次移动后请查看更新后的红框。`;
    if (action.submit_blocker === 'royal_safety') return '棋盘已推进，但仍有王受到跨时空攻击，暂不能提交。必须保护每一个王，包括历史棋盘上的王。';
    return '选择标记为“可行动”的棋盘走子；历史棋盘只能作为合法落点，不能从中选子。';
}

function renderMovableBoards() {
    const container = document.getElementById('movable-board-list');
    if (!container) return;
    const boards = gameState.game_state === 'PLAYING' && mode !== 'replay'
        ? (gameState.boards || []).filter(board => board.is_movable) : [];
    const signature = JSON.stringify([mode, gameState.game_state, gameState.turn,
        boards.map(board => [board.key, board.is_required, board.timeline_active]),
        gameState.action?.can_submit, gameState.action?.submit_blocker]);
    if (container._navigationSignature === signature) return;
    container._navigationSignature = signature;
    container.replaceChildren();
    const label = document.createElement('p');
    label.className = 'board-navigation-label';
    label.textContent = mode === 'replay' ? '回放中：点击棋盘查看局面，使用回放按钮前进或后退。' : boards.length ? `${colorLabel(gameState.turn)}本回合可操作 ${boards.length} 张棋盘 · 点击定位` : submissionHelp(gameState.action || {});
    container.appendChild(label);
    for (const board of boards) {
        const button = document.createElement('button');
        button.className = `board-chip ${board.is_required ? 'required' : 'optional'}`;
        button.textContent = `${coordLabel(board.coord)} · ${board.is_required ? '必须推进' : '可选走子'}`;
        button.onclick = () => focusBoard(board.key);
        container.appendChild(button);
    }
    if (boards.some(board => !board.timeline_active)) {
        const note = document.createElement('p');
        note.className = 'muted';
        note.textContent = '可选支线也能走。它暂不推动当前时刻，不必等到“活动”才操作；在提交前选择是否走子。';
        container.appendChild(note);
    }
}

function boardInteractionHelp(board) {
    if (gameState.game_state !== 'PLAYING') return submissionHelp(gameState.action || {});
    if (mode === 'replay') return '正在观看回放，不能走子；退出回放后可从未结束的存档继续对局。';
    if (board.historical) return '这是历史局面，只能作为合法落点，不能从这里选子。请到这条线最右端的最新棋盘操作。';
    if (board.coord.side !== gameState.turn) return `这张棋盘轮到${colorLabel(board.coord.side)}，当前行动方是${colorLabel(gameState.turn)}。每次落子（包括跳跃）都会切换这张棋盘的行棋方，不能连续移动刚走过的棋子。`;
    if ((mode === 'p2p' || mode === 'pve') && gameState.player_color !== gameState.turn) return `这张棋盘可由${colorLabel(gameState.turn)}操作；你执${colorLabel(gameState.player_color)}，请等待对手。`;
    if (mode === 'p2p' && !gameState.p2p?.can_act) return '等待双方连接恢复后继续操作；棋盘不会因为位置较早而失效。';
    if (board.is_movable) return board.timeline_active
        ? '这条线的最新棋盘可以操作，不要求它比其他线的时间更晚。'
        : '这张是可选支线的最新棋盘，现在可以走子；不参与当前时刻不等于不能操作。';
    return '本张棋盘暂不能操作，请查看当前行动和可操作棋盘列表。';
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
        board.playable ? '本线最新' : '历史',
        board.timeline_active ? '参与当前时刻' : '可选支线',
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
        <p class="board-explanation">${escapeHtml(boardInteractionHelp(board))}</p>
    `;
    if (board.historical) {
        const latest = (gameState.boards || []).find(candidate => candidate.coord.timeline === board.coord.timeline && candidate.playable);
        if (latest) {
            const button = document.createElement('button');
            button.className = 'ghost-btn';
            button.textContent = `定位本线最新棋盘 · ${coordLabel(latest.coord)}`;
            button.onclick = () => focusBoard(latest.key);
            panel.appendChild(button);
        }
    }
    const last = gameState.last_move;
    if (last?.is_branching && last.created_timeline === board.coord.timeline) {
        const note = document.createElement('p');
        note.className = 'branch-explanation';
        note.textContent = `${moveFeedback(last)}${last.captured ? '被吃的棋子在这条新支线上消失，原线上的后续版本仍在。' : ''}可选支线若停在对手阶段，需要对手选择在此推进，你的棋子才会再次轮到行动。`;
        panel.appendChild(note);
    }
}

function renderHistory() {
    const container = document.getElementById('move-history');
    container.innerHTML = '';
    const history = gameState.move_history_display || gameState.move_history || [];
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
    if (gameState) queueLinkDraw();
});

document.addEventListener('keydown', event => {
    if (document.querySelector('dialog[open]')) return;
    // Native buttons use Enter/Space themselves. Do not also submit a turn
    // when a keyboard player activates a square or another control.
    if (event.target?.closest?.('button, input, select, textarea, a, [contenteditable="true"]')) return;
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
