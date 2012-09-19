function safeMatchMedia(query) {
    var m = window.matchMedia(query);
    return !!m && m.matches;
}

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
    'desktop': safeMatchMedia('(min-width: 673px)'),
    'tablet': safeMatchMedia('(max-width: 672px)') &&
              safeMatchMedia('(min-width: 601px)'),
    'mobile': safeMatchMedia('(max-width: 600px)'),
    'touch': ('ontouchstart' in window) || window.DocumentTouch && document instanceof DocumentTouch,
    'nativeScroll': (function() {
        return 'WebkitOverflowScrolling' in document.createElement('div').style;
    })(),
    'performance': !!(window.performance || window.msPerformance || window.webkitPerformance || window.mozPerformance),
    'navPay': !!navigator.mozPay
};

// Packaged-app installation are supported only on Firefox OS, so this is how we sniff.
z.capabilities.gaia = !!(z.capabilities.mobile && navigator.mozApps && navigator.mozApps.installPackage);
z.capabilities.android = z.capabilities.mobile && !z.capabilities.gaia;

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
