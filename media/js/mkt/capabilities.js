z.capabilities = {
    'JSON': window.JSON && typeof JSON.parse == 'function',
    'debug': (('' + document.location).indexOf('dbg') >= 0),
    'debug_in_page': (('' + document.location).indexOf('dbginpage') >= 0),
    'console': window.console && (typeof window.console.log == 'function'),
    'replaceState': typeof history.replaceState === 'function',
    'chromeless': window.locationbar && !window.locationbar.visible,
    'localStorage': false,
    'sessionStorage': false,
    'webApps': !!(navigator.mozApps && navigator.mozApps.install),
    'app_runtime': !!(
        navigator.mozApps &&
        typeof navigator.mozApps.html5Implementation === 'undefined'
    ),
    'fileAPI': !!window.FileReader,
    'userAgent': navigator.userAgent,
    'desktop': window.matchMedia('(min-width: 673px)').matches,
    'tablet': window.matchMedia('(max-width: 672px)').matches &&
              window.matchMedia('(min-width: 601px)').matches,
    'mobile': window.matchMedia('(max-width: 600px)').matches,
    'touch': ('ontouchstart' in window) || window.DocumentTouch && document instanceof DocumentTouch,
    'nativeScroll': (function() {
        return 'WebkitOverflowScrolling' in document.createElement('div').style;
    })(),
    'performance': !!(window.performance || window.msPerformance || window.webkitPerformance || window.mozPerformance)
};
z.capabilities.getDeviceType = function() {
    return this.desktop ? 'desktop' : (this.tablet ? 'tablet' : 'mobile');
};

if (z.capabilities.tablet) {
    // If we're on tablet, then we're not on desktop.
    z.capabilities.desktop = false;
}

if (z.capabilities.mobile) {
    // If we're on mobile, then we're not on desktop nor tablet.
    z.capabilities.desktop = z.capabilities.tablet = false;
}

try {
    if ('localStorage' in window && window.localStorage !== null) {
        z.capabilities.localStorage = true;
    }
} catch (e) {
}

try {
    if ('sessionStorage' in window && window.sessionStorage !== null) {
        z.capabilities.sessionStorage = true;
    }
} catch (e) {
}
