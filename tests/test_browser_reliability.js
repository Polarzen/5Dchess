'use strict';

/*
 * Small VM-level browser contract tests.  They deliberately avoid a DOM
 * package: the production client only needs the handful of elements mocked
 * below, while request deadlines and generation/ownership rules are tested
 * with real Promise scheduling.
 */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

function element() {
    return {
        textContent: '',
        innerHTML: '',
        classList: { add() {}, remove() {}, toggle() {} },
        style: {},
        appendChild() {},
        replaceChildren() {},
        setAttribute() {},
        reportValidity() { return true; },
        showModal() { this.open = true; },
        close() { this.open = false; },
        remove() {},
        querySelector() { return null; },
        querySelectorAll() { return []; },
    };
}

function loadClient(includeP2P = false) {
    const elements = new Map();
    const document = {
        listeners: new Map(),
        getElementById(id) {
            if (!elements.has(id)) elements.set(id, element());
            return elements.get(id);
        },
        querySelector() { return null; },
        querySelectorAll() { return []; },
        addEventListener(name, callback) { this.listeners.set(name, callback); },
        createElement() { return element(); },
        createElementNS() { return element(); },
        body: { appendChild() {} },
    };
    const listeners = new Map();
    const window = {
        CSS: { escape(value) { return String(value); } },
        localStorage: {
            values: new Map(),
            getItem(key) { return this.values.get(key) || null; },
            setItem(key, value) { this.values.set(key, String(value)); },
            removeItem(key) { this.values.delete(key); },
        },
        addEventListener(name, callback) { listeners.set(name, callback); },
        removeEventListener(name, callback) {
            if (listeners.get(name) === callback) listeners.delete(name);
        },
    };
    const context = {
        window,
        document,
        fetch: async () => ({ ok: true, status: 200, json: async () => ({}) }),
        AbortController,
        URLSearchParams,
        CSS: window.CSS,
        navigator: { clipboard: { async writeText() {} } },
        requestAnimationFrame(callback) { callback(); },
        prompt() { return null; },
        console: { warn() {}, error() {} },
        setTimeout,
        clearTimeout,
        setInterval() { return { interval: true }; },
        clearInterval() {},
        Date,
        Promise,
        JSON,
        Number,
        String,
        Boolean,
        Array,
        Math,
    };
    context.globalThis = context;
    vm.createContext(context);
    vm.runInContext(fs.readFileSync('src/web/static/js/game.js', 'utf8'), context, {
        filename: 'game.js',
    });
    if (includeP2P) {
        vm.runInContext(fs.readFileSync('src/web/static/js/p2p.js', 'utf8'), context, {
            filename: 'p2p.js',
        });
    }
    vm.runInContext(fs.readFileSync('src/web/static/js/replay_controls.js', 'utf8'), context, {
        filename: 'replay_controls.js',
    });
    return context;
}

async function testRequestDeadline() {
    const context = loadClient();
    let signal;
    context.fetch = (_path, options) => {
        signal = options.signal;
        return new Promise(() => {});
    };
    const result = await vm.runInContext('api("/never", "GET", null, 15)', context);
    assert.equal(result.timeout_error, true);
    assert.equal(result.network_error, undefined);
    assert.equal(signal.aborted, true);
}

async function testAbortAwareAndBodyDeadlines() {
    const context = loadClient();
    context.fetch = (_path, options) => new Promise((_resolve, reject) => {
        options.signal.addEventListener('abort', () => {
            const error = new Error('AbortError');
            error.name = 'AbortError';
            reject(error);
        }, { once: true });
    });
    const abortedAware = await vm.runInContext('api("/abort-aware", "GET", null, 15)', context);
    assert.equal(abortedAware.timeout_error, true);

    context.fetch = async () => ({ ok: true, status: 200, json: () => new Promise(() => {}) });
    const hangingBody = await vm.runInContext('api("/hanging-body", "GET", null, 15)', context);
    assert.equal(hangingBody.timeout_error, true);

    context.fetch = async () => ({ ok: true, status: 200, json: async () => { throw new Error('bad json'); } });
    const invalidJson = await vm.runInContext('api("/bad-json", "GET", null, 100)', context);
    assert.equal(invalidJson.error_code, 'invalid_response');
    assert.equal(invalidJson.network_error, undefined);
}

async function testHTTPAndNetworkEnvelopes() {
    const context = loadClient();
    context.fetch = async () => ({
        ok: false,
        status: 503,
        json: async () => ({ error: 'HTTP Service Unavailable' }),
    });
    const http = await vm.runInContext('api("/http", "GET", null, 100)', context);
    assert.equal(http.http_status, 503);
    assert.match(http.error, /服务器|请求/);
    assert.doesNotMatch(http.error, /Service|Unavailable|HTTP/);

    context.fetch = async () => { throw new Error('socket exploded'); };
    const network = await vm.runInContext('api("/network", "GET", null, 100)', context);
    assert.equal(network.network_error, true);
    assert.match(network.error, /网络/);
    assert.doesNotMatch(network.error, /socket|exploded/);
}

async function testAITimeoutOnlyResyncsOnce() {
    const context = loadClient();
    vm.runInContext(`
        __calls = [];
        mode = 'pve';
        gameState = {
            mode: 'pve', game_state: 'PLAYING', turn: 'black', player_color: 'white',
            ai_thinking: false, boards: [], action: {}, p2p: null,
        };
        updateAll = () => {};
        clearSelection = () => {};
        showToast = () => {};
        api = async (path) => {
            __calls.push(path);
            if (path === '/api/game/ai_move') return { error: '超时', timeout_error: true };
            return {
                mode: 'pve', game_state: 'PLAYING', turn: 'black', player_color: 'white',
                ai_thinking: false, boards: [], action: {},
            };
        };
    `, context, { filename: 'ai-fixture.js' });
    await vm.runInContext('runAIAction(captureSession())', context);
    assert.deepEqual(Array.from(vm.runInContext('__calls', context)), ['/api/game/ai_move', '/api/game/state']);
    assert.equal(vm.runInContext('aiRequestInFlight', context), false);
    assert.equal(vm.runInContext('aiRetryAvailable', context), true);
}

async function testP2PTimeoutKeepsTokenAndRejectsStaleState() {
    const context = loadClient(true);
    vm.runInContext(`
        mode = 'p2p';
        p2pRoomCode = 'ABC123';
        p2pPlayerToken = 'token';
        gameState = { mode: 'p2p', game_state: 'PLAYING', turn: 'white', boards: [],
            action: {}, p2p: { state_version: 5, opponent_connected: true } };
        updateAll = () => {};
        clearSelection = () => {};
        showToast = () => {};
        api = async () => ({ error: '超时', timeout_error: true });
    `, context);
    await vm.runInContext('pollP2PState()', context);
    assert.equal(vm.runInContext('p2pPollInFlight', context), false);
    assert.equal(vm.runInContext('p2pRoomCode', context), 'ABC123');
    assert.equal(vm.runInContext('p2pPollFailureCount', context), 1);

    vm.runInContext(`api = async () => ({ mode: 'p2p', game_state: 'PLAYING', turn: 'white', boards: [],
        action: {}, p2p: { state_version: 4, opponent_connected: true } });`, context);
    await vm.runInContext('p2pPollRetryAt = 0; pollP2PState()', context);
    assert.equal(vm.runInContext('gameState.p2p.state_version', context), 5);

    vm.runInContext('terminateP2PSession({ code: "invalid_token" }, captureSession())', context);
    assert.equal(vm.runInContext('p2pPlayerToken', context), null);
    assert.equal(vm.runInContext('window.localStorage.getItem(P2P_STORAGE_KEY)', context), null);
}

async function testP2PPollIntervalAndRequestDeadlineAreSeparate() {
    const context = loadClient(true);
    assert.equal(vm.runInContext('P2P_POLL_INTERVAL_MS', context), 1200);
    assert.equal(vm.runInContext('P2P_POLL_TIMEOUT_MS', context), 4000);
    assert.equal(vm.runInContext('P2P_POLL_MAX_BACKOFF_MS', context), 10000);
}

async function testMutationReleaseRerendersControls() {
    const context = loadClient();
    vm.runInContext(`
        mode = 'pvp';
        gameState = { mode: 'pvp', game_state: 'PLAYING', turn: 'white', boards: [], action: {} };
        __renders = 0;
        updateAll = () => { __renders += 1; };
        mutationOwner = { id: 1, context: captureSession() };
        __owner = mutationOwner;
    `, context);
    vm.runInContext('releaseMutation(__owner)', context);
    assert.equal(vm.runInContext('mutationOwner', context), null);
    assert.equal(vm.runInContext('__renders', context), 1);
}

async function testP2PLoadWrapperIgnoresEventOverride() {
    const context = loadClient(true);
    vm.runInContext(`
        window.localStorage.setItem(P2P_STORAGE_KEY, JSON.stringify({ room_code: 'ABC123', player_token: 'saved' }));
        __calls = [];
        api = async (path) => {
            __calls.push(path);
            return { mode: 'p2p', room_code: 'ABC123', player_token: 'saved', player_color: 'white',
                game_state: 'PLAYING', turn: 'white', boards: [], action: {},
                p2p: { room_code: 'ABC123', state_version: 1, opponent_connected: false } };
        };
    `, context);
    await vm.runInContext('recoverP2PSessionOnLoad({ type: "load" })', context);
    assert.deepEqual(Array.from(vm.runInContext('__calls', context)), ['/api/p2p/join']);
    assert.equal(vm.runInContext('p2pRoomCode', context), 'ABC123');
    assert.equal(vm.runInContext('p2pRecoveryInFlight', context), false);
}

async function testSameVersionPollPreservesSelection() {
    const context = loadClient(true);
    vm.runInContext(`
        mode = 'p2p';
        p2pRoomCode = 'ABC123';
        p2pPlayerToken = 'token';
        gameState = { mode: 'p2p', game_state: 'PLAYING', turn: 'white', boards: [], action: {},
            p2p: { state_version: 5, opponent_connected: true } };
        selectedSource = { boardKey: '0:0', x: 4, y: 6, generation: 0, fingerprint: 'x' };
        legalMoves = [{ destination: { board: { key: '0:0' }, x: 4, y: 4 } }];
        __clears = 0;
        clearSelection = () => { __clears += 1; };
        __redraws = 0;
        updateAll = () => { __redraws += 1; };
        api = async () => ({ mode: 'p2p', game_state: 'PLAYING', turn: 'white', boards: [], action: {},
            p2p: { state_version: 5, opponent_connected: true } });
        p2pPollRetryAt = 0;
    `, context);
    await vm.runInContext('pollP2PState()', context);
    assert.equal(vm.runInContext('__clears', context), 0);
    assert.equal(vm.runInContext('selectedSource.boardKey', context), '0:0');
    assert.equal(vm.runInContext('legalMoves.length', context), 1);
    assert.equal(vm.runInContext('__redraws', context), 0);
}

async function testP2PLegalPrefetchReusesRequestAndInvalidates() {
    const context = loadClient(true);
    vm.runInContext(`
        mode = 'p2p'; p2pRoomCode = 'ABC123'; p2pPlayerToken = 'token';
        __board = {key: '0:0', coord: {key: '0:0'}, is_movable: true, is_required: true};
        gameState = {mode: 'p2p', game_state: 'PLAYING', turn: 'white', player_color: 'white',
            boards: [__board], action: {}, p2p: {state_version: 1, can_act: true, opponent_connected: true}};
        __calls = 0;
        api = () => { __calls++; return new Promise(resolve => { __resolveMoves = resolve; }); };
        prefetchP2PLegalMoves(); prefetchP2PLegalMoves();
        __selection = p2pMovesForSelection(__board, 4, 6);
    `, context);
    assert.equal(vm.runInContext('__calls', context), 1, 'click joins background request');
    vm.runInContext(`__resolveMoves({state_version: 1, moves: [
        {source: {board: {key: '0:0'}, x: 4, y: 6}},
        {source: {board: {key: '0:0'}, x: 1, y: 7}}
    ]});`, context);
    const first = await vm.runInContext('__selection', context);
    assert.equal(first.moves.length, 1);
    const nextPiece = await vm.runInContext('p2pMovesForSelection(__board, 1, 7)', context);
    assert.equal(nextPiece.moves.length, 1);
    assert.equal(vm.runInContext('__calls', context), 1, 'another piece uses the cached board');

    vm.runInContext(`gameState.p2p.state_version = 2; prefetchP2PLegalMoves();
        __selection = p2pMovesForSelection(__board, 4, 6);
        __resolveMoves({state_version: 3, moves: []});`, context);
    assert.equal(vm.runInContext('__calls', context), 2);
    assert.match((await vm.runInContext('__selection', context)).error, /棋局已更新/);
    assert.equal(vm.runInContext('currentP2PLegalCache().size', context), 0, 'wrong version not cached');

    // Legacy servers omit state_version; targeted fallback remains compatible.
    vm.runInContext(`__selection = p2pMovesForSelection(__board, 4, 6);
        __resolveMoves({moves: [{source: {board: {key: '0:0'}, x: 4, y: 6}}]});`, context);
    assert.equal((await vm.runInContext('__selection', context)).moves.length, 1);
    assert.equal(vm.runInContext('__calls', context), 3);
    await vm.runInContext('p2pMovesForSelection(__board, 4, 6)', context);
    assert.equal(vm.runInContext('__calls', context), 3, 'same-square fallback cached');
}

async function testP2PLegalPrefetchCannotCrossRoomOrRetainFailure() {
    const context = loadClient(true);
    vm.runInContext(`
        mode = 'p2p'; p2pRoomCode = 'ABC123'; p2pPlayerToken = 'old-token';
        gameState = {game_state: 'PLAYING', turn: 'white', p2p: {state_version: 1}};
        __board = {key: '0:0', coord: {key: '0:0'}};
        api = () => new Promise(resolve => { __oldResolve = resolve; });
        __oldRequest = requestP2PLegalMoves(__board);
        invalidateSession(); p2pRoomCode = 'DEF456';
        api = async () => ({moves: [], state_version: 1});
        __newRequest = requestP2PLegalMoves(__board);
    `, context);
    await vm.runInContext('__newRequest', context);
    vm.runInContext('__oldResolve({moves: [], state_version: 1});', context);
    assert.ok((await vm.runInContext('__oldRequest', context)).error);
    assert.equal(vm.runInContext('currentP2PLegalCache().size', context), 1, 'late old-room reply cannot clear new cache');
    vm.runInContext(`gameState.p2p.state_version = 2; api = async () => ({error:'timeout'});`, context);
    assert.ok((await vm.runInContext('requestP2PLegalMoves(__board)', context)).error);
    assert.equal(vm.runInContext('currentP2PLegalCache().size', context), 0);
}

async function testMutationCommitRejectsOlderRefresh() {
    const context = loadClient();
    vm.runInContext(`
        mode = 'pvp';
        gameState = { mode: 'pvp', game_state: 'PLAYING', turn: 'white', move_counter: 0,
            boards: [], action: {} };
        updateAll = () => {};
        clearSelection = () => {};
        __resolveMove = null;
        __resolveRefresh = null;
        api = async (path) => {
            if (path === '/api/game/move_5d') return new Promise(resolve => { __resolveMove = resolve; });
            if (path === '/api/game/state') return new Promise(resolve => { __resolveRefresh = resolve; });
            return {};
        };
        __move = { source: { board: { key: '0:0' }, x: 4, y: 6 },
            destination: { board: { key: '0:0' }, x: 4, y: 4 }, promotion: null };
    `, context);
    const move = vm.runInContext('executeCanonicalMove(__move)', context);
    await new Promise(resolve => setImmediate(resolve));
    const refresh = vm.runInContext('refreshState()', context);
    await new Promise(resolve => setImmediate(resolve));
    vm.runInContext('__resolveMove({ mode: "pvp", game_state: "PLAYING", turn: "white", move_counter: 1, boards: [], action: {} })', context);
    await move;
    vm.runInContext('__resolveRefresh({ mode: "pvp", game_state: "PLAYING", turn: "white", move_counter: 0, boards: [], action: {} })', context);
    await refresh;
    assert.equal(vm.runInContext('gameState.move_counter', context), 1);
}

async function testManualRefreshCompletesPendingAIRetry() {
    const context = loadClient();
    vm.runInContext(`
        mode = 'pve';
        aiRecoveryPending = true;
        aiRetryAvailable = false;
        gameState = { mode: 'pve', game_state: 'PLAYING', turn: 'black', player_color: 'white',
            ai_thinking: true, boards: [], action: {} };
        updateAll = () => {};
        clearSelection = () => {};
        api = async () => ({ mode: 'pve', game_state: 'PLAYING', turn: 'black', player_color: 'white',
            ai_thinking: false, boards: [], action: {} });
    `, context);
    await vm.runInContext('refreshState()', context);
    assert.equal(vm.runInContext('aiRetryAvailable', context), true);
    assert.equal(vm.runInContext('aiRecoveryPending', context), false);
}

async function testRecoveryRetirementCannotClearNewOwner() {
    const context = loadClient(true);
    vm.runInContext(`
        __oldRecovery = { id: 1 };
        __newRecovery = { id: 2 };
        p2pRecoveryOwner = __oldRecovery;
        p2pRecoveryInFlight = true;
        retireP2PRecoveryOwner(__oldRecovery);
        p2pRecoveryOwner = __newRecovery;
        p2pRecoveryInFlight = true;
    `, context);
    vm.runInContext('retireP2PRecoveryOwner(__oldRecovery)', context);
    assert.equal(vm.runInContext('p2pRecoveryOwner', context), vm.runInContext('__newRecovery', context));
    assert.equal(vm.runInContext('p2pRecoveryInFlight', context), true);
}

async function testP2PMenuExitIsSynchronousAndLeaveIsSingleShot() {
    const context = loadClient(true);
    vm.runInContext(`
        mode = 'p2p';
        p2pRoomCode = 'ABC123';
        p2pPlayerToken = 'token';
        gameState = { mode: 'p2p', game_state: 'PLAYING', boards: [], action: {}, p2p: {} };
        __leaveCalls = 0;
        api = async (path) => {
            if (path === '/api/p2p/leave') { __leaveCalls += 1; return new Promise(() => {}); }
            return {};
        };
    `, context);
    vm.runInContext('backToMenu()', context);
    vm.runInContext('backToMenu()', context);
    assert.equal(vm.runInContext('mode', context), null);
    assert.equal(vm.runInContext('p2pRoomCode', context), null);
    assert.equal(vm.runInContext('gameState', context), null);
    assert.equal(vm.runInContext('__leaveCalls', context), 1);
}

async function testReplayFrameUsesAcceptedStateIdentity() {
    const context = loadClient();
    vm.runInContext(`
        mode = 'replay';
        gameState = { mode: 'replay', game_state: 'PLAYING', turn: 'white', move_counter: 0, boards: [], action: {} };
        __frames = [];
        __scrolls = 0;
        prompt = () => 'fixture.5dpgn';
        requestAnimationFrame = callback => { __frames.push(callback); };
        scrollToCurrent = () => { __scrolls += 1; };
        updateAll = () => {};
        clearSelection = () => {};
        api = async () => ({ mode: 'replay', game_state: 'PLAYING', turn: 'white', move_counter: 1,
            boards: [], action: {} });
    `, context);
    await vm.runInContext('replayLoadFile()', context);
    assert.equal(vm.runInContext('__frames.length', context), 1);
    assert.equal(vm.runInContext('__scrolls', context), 0);
    vm.runInContext('__frames[0]()', context);
    assert.equal(vm.runInContext('__scrolls', context), 1);
}

async function testLateLocalResponseCannotCrossMenuOrMode() {
    const context = loadClient();
    vm.runInContext(`
        mode = 'pvp';
        gameState = { mode: 'pvp', game_state: 'PLAYING', turn: 'white', move_counter: 1,
            boards: [], action: {} };
        __resolve = null;
        updateAll = () => {};
        clearSelection = () => {};
        api = async path => path === '/api/game/state'
            ? new Promise(resolve => { __resolve = resolve; })
            : {};
    `, context);
    const pending = vm.runInContext('refreshState()', context);
    await new Promise(resolve => setImmediate(resolve));
    vm.runInContext('backToMenu()', context);
    vm.runInContext(`
        mode = 'pve';
        gameState = { mode: 'pve', game_state: 'PLAYING', turn: 'white', move_counter: 9,
            boards: [], action: {} };
        __resolve({ mode: 'pvp', game_state: 'PLAYING', turn: 'black', move_counter: 2,
            boards: [], action: {} });
    `, context);
    await pending;
    assert.equal(vm.runInContext('mode', context), 'pve');
    assert.equal(vm.runInContext('gameState.move_counter', context), 9);
}

async function testLateP2PResponseCannotCrossRoomOrMode() {
    const context = loadClient(true);
    vm.runInContext(`
        mode = 'p2p';
        p2pRoomCode = 'ABC123';
        p2pPlayerToken = 'token';
        gameState = { mode: 'p2p', game_state: 'PLAYING', turn: 'white', move_counter: 1,
            boards: [], action: {}, p2p: { room_code: 'ABC123', state_version: 1, opponent_connected: true } };
        __resolve = null;
        updateAll = () => {};
        clearSelection = () => {};
        api = async path => {
            if (path === '/api/p2p/state') return new Promise(resolve => { __resolve = resolve; });
            if (path === '/api/p2p/leave') return {};
            return {};
        };
    `, context);
    const pending = vm.runInContext('refreshState()', context);
    await new Promise(resolve => setImmediate(resolve));
    vm.runInContext('backToMenu()', context);
    vm.runInContext(`
        mode = 'pvp';
        gameState = { mode: 'pvp', game_state: 'PLAYING', turn: 'black', move_counter: 8,
            boards: [], action: {} };
        __resolve({ mode: 'p2p', game_state: 'PLAYING', turn: 'white', move_counter: 2,
            boards: [], action: {}, p2p: { room_code: 'ABC123', state_version: 2, opponent_connected: true } });
    `, context);
    await pending;
    assert.equal(vm.runInContext('mode', context), 'pvp');
    assert.equal(vm.runInContext('gameState.move_counter', context), 8);
    assert.equal(vm.runInContext('p2pRoomCode', context), null);
}

async function testDuplicateMoveAndSubmitUseOneMutationPost() {
    const context = loadClient();
    vm.runInContext(`
        mode = 'pvp';
        gameState = { mode: 'pvp', game_state: 'PLAYING', turn: 'white', move_counter: 0,
            boards: [], action: { can_submit: true, move_count: 0 }, rule_warning: null };
        __moveCalls = 0;
        __submitCalls = 0;
        __resolveMove = null;
        __resolveSubmit = null;
        updateAll = () => {};
        clearSelection = () => {};
        api = async path => {
            if (path === '/api/game/move_5d') {
                __moveCalls += 1;
                return new Promise(resolve => { __resolveMove = resolve; });
            }
            if (path === '/api/game/submit_action') {
                __submitCalls += 1;
                return new Promise(resolve => { __resolveSubmit = resolve; });
            }
            return {};
        };
        __move = { source: { board: { key: '0:0' }, x: 4, y: 6 },
            destination: { board: { key: '0:0' }, x: 4, y: 4 }, promotion: null };
    `, context);
    const moveOne = vm.runInContext('executeCanonicalMove(__move)', context);
    const moveTwo = vm.runInContext('executeCanonicalMove(__move)', context);
    assert.equal(vm.runInContext('__moveCalls', context), 1);
    vm.runInContext(`__resolveMove({ mode: "pvp", game_state: "PLAYING", turn: "white", move_counter: 0,
        boards: [], action: { can_submit: true, move_count: 1 } })`, context);
    await Promise.all([moveOne, moveTwo]);

    const submitOne = vm.runInContext('submitAction()', context);
    const submitTwo = vm.runInContext('submitAction()', context);
    assert.equal(vm.runInContext('__submitCalls', context), 1);
    vm.runInContext(`__resolveSubmit({ mode: "pvp", game_state: "PLAYING", turn: "black", move_counter: 1,
        boards: [], action: { can_submit: false, move_count: 0 } })`, context);
    await Promise.all([submitOne, submitTwo]);
}

async function testSuccessfulMoveRerendersAndEnablesSubmitButton() {
    const context = loadClient();
    vm.runInContext(`
        mode = 'pvp';
        gameState = { mode: 'pvp', game_state: 'PLAYING', turn: 'white', move_counter: 0,
            boards: [], timelines: [], move_history: [], present: null, in_check: false,
            summary: { active_timelines: 0, total_timelines: 0 },
            action: { color: 'white', can_submit: false, move_count: 0,
                required_boards: [], movable_boards: [] } };
        showToast = () => {};
        api = async () => ({ mode: 'pvp', game_state: 'PLAYING', turn: 'white', move_counter: 0,
            boards: [], timelines: [], move_history: [], present: null, in_check: false,
            summary: { active_timelines: 0, total_timelines: 0 },
            action: { color: 'white', can_submit: true, move_count: 1,
                required_boards: [], movable_boards: [] } });
        __move = { source: { board: { key: '0:0' }, x: 4, y: 6 },
            destination: { board: { key: '0:0' }, x: 4, y: 4 }, promotion: null };
    `, context);
    await vm.runInContext('executeCanonicalMove(__move)', context);
    assert.equal(context.document.getElementById('submit-action-btn').disabled, false);
}

function testArrivalUsesCreatedBranchAndExplainsUnsafeSubmission() {
    const context = loadClient();
    assert.equal(vm.runInContext(`moveArrivalBoardKey({is_branching: true, created_timeline: 3,
        destination: {board: {key: '0:2', timeline: 0, time_point: 2}}})`, context), '3:3');
    assert.equal(vm.runInContext(`moveArrivalBoardKey({is_branching: false,
        destination: {board: {key: '-1:4', timeline: -1, time_point: 4}}})`, context), '-1:5');
    vm.runInContext("gameState = {game_state: 'PLAYING'}", context);
    assert.match(vm.runInContext("submissionHelp({required_boards: [], can_submit: false, submit_blocker: 'royal_safety'})", context), /王.*跨时空攻击/);
    assert.match(vm.runInContext("submissionHelp({required_boards: [{}, {}], can_submit: false})", context), /2 张红框棋盘/);
}

function testRepetitionBannerShowsAndClearsWithoutChangingGame() {
    const context = loadClient(true);
    const banner = context.document.getElementById('repetition-warning');
    let hidden;
    banner.classList.toggle = (name, value) => { assert.equal(name, 'hidden'); hidden = value; };
    vm.runInContext(`gameState = {game_state: 'PLAYING', repetition: {
        kind: 'frontier_repetition', message: '检测到往返走棋；这不是自动和棋。'}};
        renderRepetitionWarning();`, context);
    assert.equal(hidden, false);
    assert.match(banner.textContent, /不是自动和棋/);
    assert.equal(vm.runInContext('gameState.game_state', context), 'PLAYING');
    vm.runInContext('gameState.repetition = null; renderRepetitionWarning();', context);
    assert.equal(hidden, true);
    assert.equal(banner.textContent, '');
}

function testActionAndMoveCountersRemainDistinct() {
    const context = loadClient(true);
    const info = context.document.getElementById('game-info');
    vm.runInContext(`mode = 'pvp'; gameState = {game_state: 'PLAYING', turn: 'white',
        move_counter: 2, action_counter: 0}; renderTopStatus();`, context);
    assert.match(info.textContent, /已提交 0 个行动.*共 2 次走子/);
    vm.runInContext('gameState.action_counter = 1; renderTopStatus();', context);
    assert.match(info.textContent, /已提交 1 个行动.*共 2 次走子/);
    vm.runInContext('delete gameState.action_counter; renderTopStatus();', context);
    assert.match(info.textContent, /共 2 次走子/);
    assert.doesNotMatch(info.textContent, /行动/);
}

function testHistoryUsesBoardCoordinatesWithLegacyFallback() {
    const context = loadClient(true);
    const rows = [];
    context.document.getElementById('move-history').appendChild = row => rows.push(row.textContent);
    vm.runInContext(`gameState = {move_history: ['(T0) e7-e5'],
        move_history_display: ['L0 · T0 白方：e2 → e4']}; renderHistory();`, context);
    assert.deepEqual(rows, ['1. L0 · T0 白方：e2 → e4']);
    rows.length = 0;
    vm.runInContext('delete gameState.move_history_display; renderHistory();', context);
    assert.deepEqual(rows, ['1. (T0) e7-e5']);
}

async function testReconnectCountdownAndSameVersionRecoveryControls() {
    const context = loadClient(true);
    vm.runInContext(`
        __now = 100000;
        Date = class extends Date { static now() { return __now; } };
        mode = 'p2p'; p2pRoomCode = 'ABC123'; p2pPlayerToken = 'secret';
        p2pLastStateAt = __now;
        gameState = { mode: 'p2p', game_state: 'PLAYING', turn: 'white', player_color: 'white', boards: [],
            action: {can_submit: true}, p2p: {room_code: 'ABC123', state_version: 4, can_act: true,
                retention_seconds: 608, opponent_connected: true, opponent_status: 'connected',
                saved: {action_counter: 2, saved_at: '2026-10-12T12:00:00Z'} } };
        updateAll = () => {}; showToast = () => {}; clearSelection = () => {};
        noteP2PPollFailure();
    `, context);
    assert.equal(context.document.getElementById('submit-action-btn').disabled, true);
    assert.match(context.document.getElementById('p2p-connection-status').textContent, /连接中断.*10分08秒/);
    vm.runInContext('__now += 300000; renderP2PConnection();', context);
    assert.match(context.document.getElementById('p2p-connection-status').textContent, /5分08秒/);
    vm.runInContext(`api = async () => gameState`, context);
    await vm.runInContext('pollP2PState()', context);
    assert.equal(context.document.getElementById('submit-action-btn').disabled, false);
    assert.match(context.document.getElementById('p2p-connection-status').textContent, /连接正常/);
    vm.runInContext(`gameState.p2p.opponent_status = 'offline';
        gameState.p2p.opponent_retention_remaining = 300;
        applyP2PState(gameState, captureSession(), null, {preserveSelection: true});`, context);
    assert.match(context.document.getElementById('p2p-connection-status').textContent, /对手离线.*5分00秒/);
    assert.match(context.document.getElementById('p2p-save-status').textContent, /已存档 2 个行动/);
    // A transient failure while recovering on the menu has no gameState yet.
    vm.runInContext(`mode = null; gameState = null; noteP2PPollFailure()`, context);
}

async function testSavedGameRestoreOwnershipAndTerminalInstructions() {
    const context = loadClient(true);
    const options = [];
    context.document.getElementById('p2p-save-list').appendChild = item => options.push(item);
    vm.runInContext(`api = async () => ({saves: [{save_id: 'abc', action_counter: 4,
        saved_at: '2026-10-12T12:00:00Z', game_state: 'PLAYING'}], unreadable: 1})`, context);
    await vm.runInContext('openSavedP2PGames()', context);
    assert.equal(options[0].value, 'abc');
    assert.match(context.document.getElementById('p2p-save-detail').textContent, /无法读取/);
    assert.equal(context.document.getElementById('p2p-restore-btn').disabled, false);
    context.document.getElementById('p2p-save-list').value = 'abc';
    vm.runInContext(`__posts = 0; __entered = 0;
        enterP2PGame = () => { __entered++; };
        api = () => { __posts++; return new Promise(resolve => { __restoreResolve = resolve; }); };`, context);
    const pending = vm.runInContext('restoreSavedP2PGame()', context);
    await vm.runInContext('replaySavedP2PGame()', context);
    assert.equal(vm.runInContext('__posts', context), 1);
    vm.runInContext(`invalidateSession(); __restoreResolve({success: true});`, context);
    await pending;
    assert.equal(vm.runInContext('__entered', context), 0);
    vm.runInContext(`showToast = () => {}; terminateP2PSession({code: 'room_expired'});`, context);
    assert.match(context.document.getElementById('p2p-recovery-note').textContent, /房主.*恢复/);
}

async function testLocalHostInviteNeverCopiesLoopbackURL() {
    const context = loadClient(true);
    context.window.location = {hostname: '127.0.0.1', origin: 'http://127.0.0.1:5050', search: ''};
    const pills = [];
    context.document.getElementById('top-status').appendChild = item => pills.push(item);
    vm.runInContext(`globalThis = window; mode = 'p2p'; gameState = {player_color: 'white', p2p: {room_code: 'ABC123'}};
        __copied = ''; navigator.clipboard.writeText = async value => { __copied = value; };
        showToast = () => {};`, context);
    vm.runInContext(fs.readFileSync('src/web/static/js/p2p_invite.js', 'utf8'), context);
    vm.runInContext('renderTopStatus()', context);
    await pills.at(-1).onclick();
    assert.equal(vm.runInContext('__copied', context), 'ABC123');
    context.window.location = {hostname: 'game.trycloudflare.com', origin: 'https://game.trycloudflare.com'};
    await pills.at(-1).onclick();
    assert.equal(vm.runInContext('__copied', context), 'https://game.trycloudflare.com/?room=ABC123');
}

async function testSavedReplaySelectionAndPlaybackOwnership() {
    const context = loadClient(true);
    vm.runInContext(`api = async () => ({saves: [{save_id: 'finished', game_state: 'DRAW',
        saved_at: '2026-10-12T12:00:00Z', action_counter: 2}], unreadable: 0});`, context);
    await vm.runInContext('openSavedP2PGames()', context);
    assert.equal(context.document.getElementById('p2p-restore-btn').disabled, true);
    assert.equal(context.document.getElementById('p2p-replay-btn').disabled, false);
    vm.runInContext(`__path = null; showToast = () => {}; scrollToCurrent = () => {};
        api = async path => { __path = path; return {mode: 'replay', current_index: 0,
            total_moves: 2, game_state: 'PLAYING', turn: 'white', boards: [], action: {}}; };`, context);
    await vm.runInContext('replaySavedP2PGame()', context);
    assert.equal(vm.runInContext('__path', context), '/api/p2p/replay');
    assert.equal(vm.runInContext('mode', context), 'replay');
    assert.equal(vm.runInContext('p2pPlayerToken', context), null);
    assert.equal(vm.runInContext('p2pRecoveryOwner', context), null);
    assert.match(context.document.getElementById('replay-position').textContent, /第 0 \/ 2 手/);
    // Captured timer callbacks cannot advance another UI session.
    const timers = [];
    context.setTimeout = callback => { timers.push(callback); return timers.length; };
    context.clearTimeout = () => {};
    vm.runInContext(`__posts = 0; gameState.is_playing = true;
        api = () => { __posts++; return new Promise(resolve => { __tickResolve = resolve; }); };
        renderReplayPanel();`, context);
    const staleTimer = timers.at(-1);
    const pending = vm.runInContext("replayAction('tick')", context);
    await vm.runInContext("replayAction('tick')", context);
    assert.equal(vm.runInContext('__posts', context), 1);
    vm.runInContext(`invalidateSession(); gameState = {is_playing: true, current_index: 0, total_moves: 2};
        __tickResolve({mode: 'replay', current_index: 1, total_moves: 2, is_playing: true});`, context);
    await pending;
    staleTimer();
    assert.equal(vm.runInContext('gameState.current_index', context), 0);
    assert.equal(vm.runInContext('__posts', context), 1);
    vm.runInContext(`api = async () => ({error: 'offline'});`, context);
    await vm.runInContext("replayAction('tick')", context);
    assert.equal(vm.runInContext('gameState.is_playing', context), false);
    vm.runInContext(`__jumpPayload = null; api = async (path, method, payload) => {
        __jumpPayload = payload; return {...gameState, current_index: payload.index}; };`, context);
    context.document.getElementById('replay-jump-index').value = '3';
    await vm.runInContext('replayJump()', context);
    assert.equal(vm.runInContext('__jumpPayload', context), null);
    context.document.getElementById('replay-jump-index').value = '1';
    await vm.runInContext('replayJump()', context);
    assert.equal(vm.runInContext('__jumpPayload.action', context), 'jump');
    assert.equal(vm.runInContext('gameState.current_index', context), 1);
    let overlaysRemoved = 0;
    context.document.getElementById('game-over-overlay').remove = () => { overlaysRemoved++; };
    vm.runInContext(`gameState.game_state = 'DRAW'; checkGameOver();`, context);
    assert.equal(overlaysRemoved, 1);
}

function testIncrementalBoardRendering() {
    const context = loadClient();
    let created = 0;
    let animations = 0;
    function domElement() {
        created++;
        const node = element();
        node.children = []; node.dataset = {}; node.attributes = {}; node.className = '';
        node.appendChild = child => node.insertBefore(child, null);
        node.insertBefore = (child, next) => {
            child.remove();
            const index = next ? node.children.indexOf(next) : node.children.length;
            node.children.splice(index, 0, child); child.parentNode = node;
            return child;
        };
        node.remove = () => {
            if (node.parentNode) node.parentNode.children.splice(node.parentNode.children.indexOf(node), 1);
            node.parentNode = null;
        };
        node.replaceChildren = () => { node.children.forEach(child => {child.parentNode = null;}); node.children = []; };
        node.setAttribute = (key, value) => {node.attributes[key] = value;};
        node.animate = () => { animations++; };
        Object.defineProperty(node, 'firstChild', {get: () => node.children[0]});
        return node;
    }
    const container = domElement();
    const originalGet = context.document.getElementById;
    context.document.getElementById = id => id === 'timeline-lanes' ? container : originalGet(id);
    context.document.createElement = domElement;
    vm.runInContext(`queueLinkDraw = () => {}; mode = 'pvp';
        __boards = Array.from({length: 120}, (_, i) => ({key: '0:' + i,
            coord: {timeline: 0, time_point: i, turn: Math.floor(i/2), side: i%2 ? 'black' : 'white'},
            board: Array.from({length: 8}, () => Array(8).fill('')), timeline_active: true,
            role: i === 119 ? 'playable' : 'historical', is_movable: i === 119, historical: i < 119}));
        gameState = {boards: __boards, timelines: [{id: 0, name: 'L0', is_active: true}], move_counter: 0};
        renderMultiverse(); __oldCells = boardViews.get('0:119').card._cells.slice();
        __oldCard = boardViews.get('0:0').card;`, context);
    const initialCreated = created;
    vm.runInContext(`selectedSource = {boardKey: '0:119', x: 3, y: 4};
        legalMoves = [{destination: {board: {key: '0:0'}, x: 5, y: 3}, is_branching: true},
                      {destination: {board: {key: '0:119'}, x: 4, y: 4}, is_branching: false}];
        renderMultiverse();`, context);
    assert.equal(created, initialCreated, 'Selecting on 120 boards must create zero elements');
    assert.equal(vm.runInContext("boardViews.get('0:0').card === __oldCard", context), true);
    assert.equal(vm.runInContext("boardViews.get('0:119').card._cells.every((c, i) => c === __oldCells[i])", context), true);
    assert.match(vm.runInContext("boardViews.get('0:0').card._cells[29].className", context), /branch-target/);
    assert.match(vm.runInContext("boardViews.get('0:119').card._cells[35].className", context), /source-selected/);
    // A full network snapshot recreates JS objects, but preserves historical DOM and scroll position.
    const viewport = originalGet('multiverse-viewport'); viewport.scrollLeft = 200; viewport.scrollTop = 100;
    vm.runInContext(`gameState.boards = JSON.parse(JSON.stringify(__boards));
        gameState.boards.push({...__boards[119], key: '0:120', coord: {...__boards[119].coord, time_point: 120}});
        gameState.move_counter = 1;
        gameState.last_move = {source: {board: {key: '0:119'}, x: 3, y: 4},
            destination: {board: {key: '0:119'}, x: 4, y: 4}, result_destination_board: {key: '0:120'}};
        clearSelection(false); renderMultiverse();`, context);
    assert.ok(created - initialCreated < 140, 'Only one new board is created');
    assert.equal(vm.runInContext("boardViews.get('0:0').card === __oldCard", context), true);
    assert.doesNotMatch(vm.runInContext("boardViews.get('0:0').card._cells[29].className", context), /target/);
    assert.equal(viewport.scrollLeft, 200); assert.equal(viewport.scrollTop, 100);
    assert.equal(animations, 2, 'Animate only the new board and accepted arrival');
    vm.runInContext('renderMultiverse()', context);
    assert.equal(animations, 2, 'Mutation release must not replay the arrival');
    context.window.matchMedia = () => ({matches: true});
    vm.runInContext(`gameState.move_counter = 2; gameState.boards.push({...__boards[119], key: '0:121',
        coord: {...__boards[119].coord, time_point: 121}}); renderMultiverse();`, context);
    assert.equal(animations, 2, 'Respect reduced motion for board and piece animations');
    vm.runInContext('gameState.boards = gameState.boards.slice(0, 2); renderMultiverse();', context);
    assert.equal(vm.runInContext('boardViews.size', context), 2);
    assert.equal(container.children[0].children[1].children.length, 2);
    vm.runInContext('invalidateSession(); renderMultiverse();', context);
    assert.equal(vm.runInContext("boardViews.get('0:0').card === __oldCard", context), false);
}

function testKeyboardControlsDoNotAlsoSubmitTurn() {
    const context = loadClient();
    vm.runInContext(`mode = 'pvp'; gameState = {action: {can_submit: true}};
        __submitted = 0; submitAction = () => { __submitted++; };`, context);
    const keydown = context.document.listeners.get('keydown');
    keydown({key: 'Enter', target: {closest: () => ({})}});
    assert.equal(vm.runInContext('__submitted', context), 0, 'Native square/button Enter owns its click');
    keydown({key: 'Enter', target: {closest: () => null}});
    assert.equal(vm.runInContext('__submitted', context), 1, 'Background Enter shortcut remains available');
}

async function testDelayedSelectionFeedbackAndOwnership() {
    for (const online of [false, true]) {
        const context = loadClient(online);
        vm.runInContext(`mode = ${online ? "'p2p'" : "'pvp'"};
            gameState = {move_counter: 0, turn: 'white', game_state: 'PLAYING'};
            renderMultiverse = () => {}; renderInspector = () => {};
            __board = {key: '0:0', coord: {timeline: 0, time_point: 0}};
            ${online ? 'p2pMovesForSelection' : 'api'} = () => new Promise(resolve => {__resolveSelection = resolve;});`, context);
        const pending = vm.runInContext('selectSource(__board, 6, 7)', context);
        assert.equal(context.document.getElementById('interaction-status').hidden, false);
        assert.match(context.document.getElementById('interaction-label').textContent, /合法落点/);
        assert.equal(vm.runInContext('selectedSource', context), null, 'No speculative legal state');
        vm.runInContext(`invalidateSession(); __newOwner = {}; beginInteraction(__newOwner, '正在同步行动…');
            __resolveSelection({moves: [{destination: {board: {key: '0:0'}, x: 5, y: 5}}]});`, context);
        await pending;
        assert.equal(context.document.getElementById('interaction-status').hidden, false, 'Late response cannot dismiss newer feedback');
        assert.equal(vm.runInContext('selectedSource', context), null);
        vm.runInContext('endInteraction(__newOwner)', context);
        assert.equal(context.document.getElementById('interaction-status').hidden, true);
    }
}

async function testCompactPollPreservesBoardsAndRejectsLateVersion() {
    const context = loadClient(true);
    vm.runInContext(`mode = 'p2p'; p2pRoomCode = 'ABC123'; p2pPlayerToken = 'fixture';
        __boards = [{key: '0:0'}]; __selection = {boardKey: '0:0', x: 6, y: 7};
        gameState = {boards: __boards, move_counter: 2, p2p: {room_code: 'ABC123', state_version: 5}};
        selectedSource = __selection; __renders = 0; updateAll = () => { __renders++; };
        api = async (path, method, body) => { __pollBody = body;
            return {unchanged: true, p2p: {room_code: 'ABC123', state_version: 5}}; };`, context);
    await vm.runInContext('pollP2PState()', context);
    assert.equal(vm.runInContext('__pollBody.known_version', context), 5);
    assert.equal(vm.runInContext('gameState.boards === __boards && selectedSource === __selection', context), true);
    assert.equal(vm.runInContext('__renders', context), 0);
    assert.equal(vm.runInContext(`applyP2PState({unchanged: true, p2p: {room_code: 'ABC123', state_version: 4}},
        captureSession(), null, {preserveSelection: true})`, context), false);
    assert.equal(vm.runInContext(`applyP2PState({unchanged: true, p2p: {room_code: 'OTHER1', state_version: 5}},
        captureSession(), null, {preserveSelection: true})`, context), false);
    assert.equal(vm.runInContext(`applyP2PState({unchanged: true, p2p: {room_code: 'ABC123', state_version: 6}},
        captureSession(), null, {preserveSelection: true})`, context), false);
    assert.equal(vm.runInContext('gameState.move_counter', context), 2);
}

function testPastBranchControlsAndReasons() {
    for (const online of [false, true]) {
        const context = loadClient(online);
        const links = [];
        const container = context.document.getElementById('movable-board-list');
        container.appendChild = node => links.push(node);
        container.replaceChildren = () => { links.length = 0; };
        vm.runInContext(`mode = '${online ? 'p2p' : 'pvp'}';
            __old = {key:'2:1', playable:true, historical:false, is_movable:true, is_required:false,
                timeline_active:false, coord:{key:'2:1',timeline:2,turn:0,time_point:1,side:'black'}};
            __main = {...__old,key:'0:3',is_required:true,timeline_active:true,
                coord:{key:'0:3',timeline:0,turn:1,time_point:3,side:'black'}};
            gameState = {game_state:'PLAYING',turn:'black',player_color:'black', boards:[__main,__old],
                p2p:{can_act:true,opponent_connected:true},action:{required_boards:[__main.coord]}};
            __focused = null; focusBoard = key => { __focused = key; }; renderMovableBoards();`, context);
        assert.equal(vm.runInContext("canSelectSource(__old, 'p')", context), true);
        const optional = links.find(node => node.className === 'board-chip optional');
        assert.ok(optional, 'old inactive branch must have a navigation button');
        vm.runInContext('renderMovableBoards()', context);
        assert.equal(links.find(node => node.className === 'board-chip optional'), optional, 'unchanged polls retain the navigation button and its focus');
        optional.onclick();
        assert.equal(vm.runInContext('__focused', context), '2:1');
        assert.match(vm.runInContext('boardInteractionHelp(__old)', context), /现在可以走子/);
        vm.runInContext("gameState.turn = 'white'; __old.is_movable = false;", context);
        assert.equal(vm.runInContext("canSelectSource(__old, 'N')", context), false);
        assert.match(vm.runInContext('boardInteractionHelp(__old)', context), /轮到黑方/);
        assert.match(vm.runInContext('boardInteractionHelp({...__old,historical:true,playable:false})', context), /最右端/);
        assert.match(vm.runInContext("moveFeedback({is_branching:true,created_timeline:2,captured:{type:'P'},result_destination_board:{side:'black'}})", context), /吃子已在新支线 L\+2；原时间线保留/);
        vm.runInContext("gameState.game_state = 'CHECKMATE'; renderActionPanel();", context);
        assert.match(context.document.getElementById('action-help').textContent, /白方已被将杀/);
        assert.equal(links.some(node => node.className?.startsWith('board-chip')), false);
    }
}

async function testLLMSetupAndFallbackStatus() {
    const context = loadClient();
    const calls = [];
    const settings = {ready:false,has_key:false,base_url:'https://api.deepseek.com',model:'deepseek-flash',timeout_seconds:8,max_requests:80,revision:'missing',editing_locked:false,message:'尚未配置在线 AI'};
    context.fetch = async path => { calls.push(path); return {ok:true,status:200,json:async () => settings}; };
    await vm.runInContext('openLLMSetup()', context);
    assert.equal(context.document.getElementById('llm-dialog').open, true);
    assert.equal(context.document.getElementById('llm-start-btn').disabled, true);
    assert.match(context.document.getElementById('llm-config-status').textContent, /尚未配置/);
    context.fetch = async path => { calls.push(path); return {ok:true,status:200,json:async () => ({...settings,ready:true,has_key:true,revision:'saved'})}; };
    await vm.runInContext('checkLLMConfig()', context);
    assert.equal(context.document.getElementById('llm-start-btn').disabled, false);
    assert.ok(calls.every(path => path === '/api/ai/llm_status'), 'setup must never make a paid AI request');
    const key = context.document.getElementById('llm-api-key');
    assert.equal(key.value, '');
    assert.equal(key.required, false);
    key.value = 'new-test-key';
    vm.runInContext('markLLMConfigDirty()', context);
    assert.equal(context.document.getElementById('llm-start-btn').disabled, true);
    assert.equal(context.document.getElementById('llm-test-btn').disabled, true);
    let finishSave;
    context.fetch = async (path, options) => {
        calls.push(path);
        assert.equal(JSON.parse(options.body).api_key, 'new-test-key');
        await new Promise(resolve => { finishSave = resolve; });
        return {ok:true,status:200,json:async () => ({...settings,ready:true,has_key:true,revision:'next',message:'已保存'})};
    };
    const saving = vm.runInContext('saveLLMConfig()', context);
    assert.equal(key.value, '', 'clear entered key immediately after sending');
    assert.equal(context.document.getElementById('llm-save-btn').disabled, true);
    await vm.runInContext('saveLLMConfig()', context);
    assert.equal(calls.filter(path => path === '/api/ai/llm_config').length, 1);
    finishSave();
    await saving;
    assert.equal(context.document.getElementById('llm-start-btn').disabled, false);
    assert.equal(key.value, '');
    assert.ok([...context.window.localStorage.values.values()].every(value => !String(value).includes('new-test-key')));
    key.value = 'unsubmitted-test-key';
    vm.runInContext('toggleLLMKeyVisibility(); closeLLMSetup()', context);
    assert.equal(key.value, '');
    assert.equal(key.type, 'password');
    vm.runInContext(`mode='pve'; gameState={ai_difficulty:'llm',ai_opponent:{model:'deepseek-flash',requests_used:1,max_requests:80,last_source:'local'},ai_warning:'在线 AI 响应超时，本回合已使用本地合法方案。'}; renderLLMStatus();`, context);
    assert.match(context.document.getElementById('llm-ai-status').textContent, /请求 1\/80.*超时/);
    vm.runInContext("mode='p2p'; renderLLMStatus();", context);
    assert.equal(context.document.getElementById('llm-ai-status').hidden, true);
    assert.equal(context.document.getElementById('llm-ai-status').textContent, '');
}

(async () => {
    await testLLMSetupAndFallbackStatus();
    testPastBranchControlsAndReasons();
    testIncrementalBoardRendering();
    testKeyboardControlsDoNotAlsoSubmitTurn();
    await testDelayedSelectionFeedbackAndOwnership();
    await testCompactPollPreservesBoardsAndRejectsLateVersion();
    await testSavedReplaySelectionAndPlaybackOwnership();
    await testReconnectCountdownAndSameVersionRecoveryControls();
    await testSavedGameRestoreOwnershipAndTerminalInstructions();
    await testLocalHostInviteNeverCopiesLoopbackURL();
    await testRequestDeadline();
    await testAbortAwareAndBodyDeadlines();
    await testHTTPAndNetworkEnvelopes();
    await testAITimeoutOnlyResyncsOnce();
    await testP2PTimeoutKeepsTokenAndRejectsStaleState();
    await testP2PPollIntervalAndRequestDeadlineAreSeparate();
    await testMutationReleaseRerendersControls();
    await testP2PLoadWrapperIgnoresEventOverride();
    await testSameVersionPollPreservesSelection();
    await testP2PLegalPrefetchReusesRequestAndInvalidates();
    await testP2PLegalPrefetchCannotCrossRoomOrRetainFailure();
    await testMutationCommitRejectsOlderRefresh();
    await testManualRefreshCompletesPendingAIRetry();
    await testRecoveryRetirementCannotClearNewOwner();
    await testP2PMenuExitIsSynchronousAndLeaveIsSingleShot();
    await testReplayFrameUsesAcceptedStateIdentity();
    await testLateLocalResponseCannotCrossMenuOrMode();
    await testLateP2PResponseCannotCrossRoomOrMode();
    await testDuplicateMoveAndSubmitUseOneMutationPost();
    await testSuccessfulMoveRerendersAndEnablesSubmitButton();
    testArrivalUsesCreatedBranchAndExplainsUnsafeSubmission();
    testRepetitionBannerShowsAndClearsWithoutChangingGame();
    testActionAndMoveCountersRemainDistinct();
    testHistoryUsesBoardCoordinatesWithLegacyFallback();
    console.log('Browser reliability tests passed');
})().catch(error => {
    console.error(error);
    process.exitCode = 1;
});
