function safeMatchMedia(query) {
    var m = window.matchMedia(query);
    return !!m && m.matches;
}

define('capabilities', [], function() {
    var capabilities = {
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
        'desktop': false,
        'tablet': false,
        'mobile': safeMatchMedia('(max-width: 600px)'),
        'firefoxAndroid': (navigator.userAgent.indexOf('Firefox') != -1 && navigator.userAgent.indexOf('Android') != -1),
        'touch': ('ontouchstart' in window) || window.DocumentTouch && document instanceof DocumentTouch,
        'nativeScroll': (function() {
            return 'WebkitOverflowScrolling' in document.createElement('div').style;
        })(),
        'performance': !!(window.performance || window.msPerformance || window.webkitPerformance || window.mozPerformance),
        'navPay': !!navigator.mozPay,
        'firefoxOS': null  // This is set below.
    };

    // We're probably tablet if we have touch and we're larger than mobile.
    capabilities.tablet = capabilities.touch && safeMatchMedia('(min-width: 601px)');

    // We're probably desktop if we don't have touch and we're larger than some arbitrary dimension.
    capabilities.desktop = !capabilities.touch && safeMatchMedia('(min-width: 673px)');

    // Packaged-app installation are supported only on Firefox OS, so this is how we sniff.
    capabilities.gaia = !!(capabilities.mobile && navigator.mozApps && navigator.mozApps.installPackage);

    capabilities.getDeviceType = function() {
        return this.desktop ? 'desktop' : (this.tablet ? 'tablet' : 'mobile');
    };

    if (capabilities.tablet) {
        // If we're on tablet, then we're not on desktop.
        capabilities.desktop = false;
    }

    if (capabilities.mobile) {
        // If we're on mobile, then we're not on desktop nor tablet.
        capabilities.desktop = capabilities.tablet = false;
    }

    // Detect Firefox OS.
    // This will be true if the request is from a Firefox OS phone *or*
    // a desktop B2G build with the correct UA pref, such as this:
    // https://github.com/mozilla/r2d2b2g/blob/master/prosthesis/defaults/preferences/prefs.js
    capabilities.firefoxOS = capabilities.gaia && !capabilities.firefoxAndroid;

    try {
        if ('localStorage' in window && window.localStorage !== null) {
            capabilities.localStorage = true;
        }
    } catch (e) {
    }

    try {
        if ('sessionStorage' in window && window.sessionStorage !== null) {
            capabilities.sessionStorage = true;
        }
    } catch (e) {
    }

    return capabilities;

});

z.capabilities = require('capabilities');
