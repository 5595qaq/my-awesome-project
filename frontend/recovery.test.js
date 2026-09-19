const assert = require('node:assert/strict');
const { reconnectDelay, recoveryAction } = require('./recovery.js');

assert.deepEqual([0, 1, 2, 3, 10].map(reconnectDelay), [1000, 2000, 4000, 8000, 30000]);
assert.equal(recoveryAction('finished'), 'render');
assert.equal(recoveryAction('failed'), 'retry');
assert.equal(recoveryAction('processing'), 'reconnect');
assert.equal(recoveryAction('pending'), 'reconnect');

console.log('recovery tests passed');
