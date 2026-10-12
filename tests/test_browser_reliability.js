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
        remove() {},
        querySelector() { return null; },
        querySelectorAll() { return []; },
    };
}

function loadClient(includeP2P = false) {
    const elements = new Map();
    const document = {
        getElementById(id) {
            if (!elements.has(id)) elements.set(id, element());
            return elements.get(id);
        },
        querySelector() { return null; },
        querySelectorAll() { return []; },
        addEventListener() {},
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

(async () => {
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
