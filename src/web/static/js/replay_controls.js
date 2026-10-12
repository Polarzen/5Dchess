/** File replay controls; playback requests remain owned by one UI session. */
let replayTickTimer = null;
const baseReplayRenderPanel = renderReplayPanel;
const baseReplayGameOver = checkGameOver;

checkGameOver = function() {
    if (mode !== 'replay') return baseReplayGameOver();
    // Finished games must still allow stepping backward or choosing a frame.
    document.getElementById('game-over-overlay')?.remove();
};

renderReplayPanel = function() {
    baseReplayRenderPanel();
    clearTimeout(replayTickTimer);
    replayTickTimer = null;
    if (mode !== 'replay' || !gameState) return;
    const current = gameState.current_index || 0;
    const total = gameState.total_moves || 0;
    document.getElementById('replay-position').textContent =
        `第 ${current} / ${total} 手 · ${gameStateLabel(gameState.game_state)}`;
    document.getElementById('replay-toggle').textContent = gameState.is_playing ? '暂停' : '播放';
    const jumpInput = document.getElementById('replay-jump-index');
    jumpInput.max = total;
    jumpInput.disabled = Boolean(mutationOwner) || total === 0;
    for (const button of document.querySelectorAll('[data-replay-action]')) {
        const action = button.dataset.replayAction;
        button.disabled = Boolean(mutationOwner) || total === 0
            || (['start', 'backward'].includes(action) && current === 0)
            || (['end', 'forward', 'toggle'].includes(action) && current >= total);
    }
    if (!gameState.is_playing || mutationOwner || current >= total) return;
    const context = captureSession();
    replayTickTimer = setTimeout(() => {
        replayTickTimer = null;
        if (isCurrentSession(context) && mode === 'replay' && gameState?.is_playing) replayAction('tick');
    }, 1000);
};

replayJump = function() {
    const raw = document.getElementById('replay-jump-index').value;
    const index = Number(raw);
    if (!raw.trim() || !Number.isInteger(index) || index < 0 || index > (gameState?.total_moves || 0)) {
        showToast(`请输入 0 到 ${gameState?.total_moves || 0} 之间的整数步数`, true);
        return;
    }
    return replayAction('jump', index);
};

replayAction = async function(action, index) {
    if (mode !== 'replay' || !gameState || (action === 'tick' && !gameState.is_playing)) return;
    const context = captureSession();
    const owner = acquireMutation(context);
    if (!owner) return;
    try {
        const payload = {action};
        if (action === 'tick') payload.expected_index = gameState.current_index;
        if (action === 'jump') payload.index = index;
        const result = await api('/api/replay/step', 'POST', payload);
        if (!ownsMutation(owner)) return;
        if (isErrorResult(result)) {
            gameState.is_playing = false;
            showToast(playerErrorMessage(result, '播放已暂停，请重新同步后继续'), true);
            return;
        }
        if (!commitMutation(owner)) return;
        gameState = result;
        clearSelection(false);
        updateAll();
    } catch (error) {
        if (ownsMutation(owner)) {
            gameState.is_playing = false;
            showToast('播放已暂停，请重新同步后继续', true);
        }
    } finally {
        releaseMutation(owner);
    }
};
