'use strict';

const assert = require('node:assert/strict');
const {
    normalizeRoomCode,
    roomCodeFromSearch,
    buildInviteURL,
} = require('../src/web/static/js/p2p_invite.js');

assert.equal(normalizeRoomCode('ABC123'), 'ABC123');
assert.equal(normalizeRoomCode('abc123'), 'ABC123');
assert.equal(normalizeRoomCode('  AbC123  '), 'ABC123');

for (const invalid of [
    null,
    '',
    'A',
    'ABC12345',
    'ABC-12',
    'ABC 12',
    '<script>',
    'ABC12<',
]) {
    assert.equal(normalizeRoomCode(invalid), null, `expected invalid room code: ${invalid}`);
}

assert.equal(roomCodeFromSearch('?room=ABC123'), 'ABC123');
assert.equal(roomCodeFromSearch('?room=abc123'), 'ABC123');
assert.equal(roomCodeFromSearch('?room='), null);
assert.equal(roomCodeFromSearch('?room=A'), null);
assert.equal(roomCodeFromSearch('?room=ABC12345'), null);
assert.equal(roomCodeFromSearch('?room=%3Cscript%3E'), null);
assert.equal(roomCodeFromSearch('?other=ABC123'), null);

const invite = buildInviteURL('https://example.trycloudflare.com/', 'abc123');
assert.equal(invite, 'https://example.trycloudflare.com/?room=ABC123');
assert.equal(invite.includes('token'), false);
assert.equal(invite.includes('#'), false);
assert.equal(buildInviteURL('https://example.trycloudflare.com', '<script>'), null);
assert.equal(buildInviteURL('', 'ABC123'), null);

console.log('P2P invite helper tests passed');
