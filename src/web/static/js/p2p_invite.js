/** Safe room-code-only invite links layered over the existing P2P adapter. */

(function(root, factory) {
    const helpers = factory();
    if (typeof module !== 'undefined' && module.exports) {
        module.exports = helpers;
    }
    if (root) {
        root.P2PInviteHelpers = helpers;
    }
})(typeof globalThis !== 'undefined' ? globalThis : this, function() {
    const ROOM_CODE_PATTERN = /^[A-Z0-9]{6}$/;

    function normalizeRoomCode(value) {
        if (typeof value !== 'string') return null;
        const normalized = value.trim().toUpperCase();
        return ROOM_CODE_PATTERN.test(normalized) ? normalized : null;
    }

    function roomCodeFromSearch(search) {
        try {
            const params = new URLSearchParams(search || '');
            return normalizeRoomCode(params.get('room'));
        } catch (error) {
            return null;
        }
    }

    function buildInviteURL(origin, roomCode) {
        const normalized = normalizeRoomCode(roomCode);
        if (!normalized || typeof origin !== 'string' || !origin) return null;
        const safeOrigin = origin.replace(/\/+$/, '');
        return `${safeOrigin}/?room=${encodeURIComponent(normalized)}`;
    }

    return Object.freeze({
        normalizeRoomCode,
        roomCodeFromSearch,
        buildInviteURL,
    });
});

if (typeof window !== 'undefined') {
    const {
        normalizeRoomCode,
        roomCodeFromSearch,
        buildInviteURL,
    } = window.P2PInviteHelpers;

    function roomCodeFromLocation(locationLike = window.location) {
        return roomCodeFromSearch(locationLike?.search || '');
    }

    function buildP2PInviteURL(roomCode, locationLike = window.location) {
        return buildInviteURL(locationLike?.origin || '', roomCode);
    }

    function updateP2PInviteMenu() {
        const roomCode = roomCodeFromLocation();
        const label = document.getElementById('p2p-join-label');
        const detail = document.getElementById('p2p-join-detail');
        if (!label || !detail) return;

        if (roomCode) {
            label.textContent = `加入在线房间 ${roomCode}`;
            detail.textContent = `Online P2P · 检测到邀请房间 ${roomCode}`;
        } else {
            label.textContent = '加入在线房间';
            detail.textContent = 'Online P2P · 输入 6 位房间码远程对弈';
        }
    }

    async function copyP2PInviteLink() {
        const roomCode = normalizeRoomCode(gameState?.p2p?.room_code || p2pRoomCode);
        const inviteURL = buildP2PInviteURL(roomCode);
        if (!inviteURL) {
            showToast('当前房间无法生成邀请链接', true);
            return;
        }

        try {
            if (!navigator.clipboard?.writeText) throw new Error('clipboard unavailable');
            await navigator.clipboard.writeText(inviteURL);
            showToast('邀请链接已复制');
        } catch (error) {
            showToast(`邀请链接：${inviteURL}`);
        }
    }

    const p2pInviteBaseJoin = joinP2PRoom;
    const p2pInviteBaseRenderTopStatus = renderTopStatus;
    const p2pInviteBaseRenderActionPanel = renderActionPanel;
    const p2pInviteBaseRecover = recoverStoredP2PSession;

    // p2p.js normally recovers any stored session on load.  A valid invite
    // URL narrows automatic recovery to that same room, so merely opening a
    // new invite never occupies a seat without either a stored token or an
    // explicit Join click.
    window.removeEventListener('load', p2pInviteBaseRecover);

    joinP2PRoom = async function(roomCodeOverride = null) {
        const roomCode = normalizeRoomCode(roomCodeOverride) || roomCodeFromLocation();
        if (!roomCode) return p2pInviteBaseJoin();

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
    };

    renderTopStatus = function() {
        p2pInviteBaseRenderTopStatus();
        if (
            mode !== 'p2p'
            || gameState?.player_color !== 'white'
            || !normalizeRoomCode(gameState?.p2p?.room_code)
        ) return;

        const status = document.getElementById('top-status');
        if (!status) return;
        const invite = document.createElement('span');
        invite.className = 'status-pill emphasis';
        invite.textContent = '复制邀请链接';
        invite.title = '复制只包含房间码的在线邀请链接';
        invite.style.cursor = 'pointer';
        invite.onclick = copyP2PInviteLink;
        status.appendChild(invite);
    };

    renderActionPanel = function() {
        p2pInviteBaseRenderActionPanel();
        if (
            mode !== 'p2p'
            || gameState?.player_color !== 'white'
            || gameState?.p2p?.opponent_status !== 'not_connected'
        ) return;
        const help = document.getElementById('action-help');
        if (help) {
            help.textContent = `房间 ${gameState.p2p.room_code} 正在等待第二位玩家；点击顶部“复制邀请链接”发送给对手。`;
        }
    };

    async function recoverP2PSessionRespectingInvite() {
        const invitedRoom = roomCodeFromLocation();
        if (invitedRoom && !readStoredP2PSession(invitedRoom)) return;
        await p2pInviteBaseRecover();
    }

    window.addEventListener('load', () => {
        updateP2PInviteMenu();
        recoverP2PSessionRespectingInvite();
    });

    // Expose only non-secret invite helpers for lightweight browser debugging.
    window.normalizeP2PRoomCode = normalizeRoomCode;
    window.roomCodeFromLocation = roomCodeFromLocation;
    window.buildP2PInviteURL = buildP2PInviteURL;
}