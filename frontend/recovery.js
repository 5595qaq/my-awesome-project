(function (root, factory) {
    const api = factory();
    if (typeof module === 'object' && module.exports) module.exports = api;
    root.Recovery = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
    function reconnectDelay(attempt) {
        return Math.min(30000, 1000 * (2 ** Math.max(0, attempt)));
    }

    function recoveryAction(status) {
        if (status === 'finished') return 'render';
        if (status === 'failed') return 'retry';
        return 'reconnect';
    }

    return { reconnectDelay, recoveryAction };
});
