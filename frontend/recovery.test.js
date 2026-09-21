const assert = require('node:assert/strict');
const { reconnectDelay, recoveryAction, branchNotificationAction } = require('./recovery.js');

assert.deepEqual([0, 1, 2, 3, 10].map(reconnectDelay), [1000, 2000, 4000, 8000, 30000]);
assert.equal(recoveryAction('finished'), 'render');
assert.equal(recoveryAction('failed'), 'retry');
assert.equal(recoveryAction('retired'), 'retired');
assert.equal(recoveryAction('processing'), 'reconnect');
assert.equal(recoveryAction('pending'), 'reconnect');
assert.equal(branchNotificationAction('failed'), 'retry');
assert.equal(branchNotificationAction('retired'), 'retired');
assert.equal(branchNotificationAction('in-progress'), 'continue');

console.log('recovery tests passed');
