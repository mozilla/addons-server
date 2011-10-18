z.capabilities = {
    'JSON': window.JSON && typeof JSON.parse == 'function',
    'debug': (('' + document.location).indexOf('dbg') >= 0),
    'debug_in_page': (('' + document.location).indexOf('dbginpage') >= 0),
    'console': window.console && (typeof window.console.log == 'function'),
    'replaceState': typeof history.replaceState === 'function',
    'localStorage': false
};


try {
    if ('localStorage' in window && window['localStorage'] !== null) {
        z.capabilities.localStorage = true;
    }
} catch (e) {
}
