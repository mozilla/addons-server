/*
    Provides the apps module, a wrapper around navigator.mozApps
*/
(function(exports) {
"use strict";

/*

apps.install(manifestUrl, options)

It's just like navigator.apps.install with the following enhancements:
- If navigator.apps.install doesn't exist, an error is displayed
- If the install resulted in errors, they are displayed to the user

This requires at least one apps-error-msg div to be present.

See also: https://developer.mozilla.org/en/Apps/Apps_JavaScript_API/navigator.mozApps.install

The recognized option attributes are as follows:

data
    Optional dict to pass as navigator.apps.install(url, data, ...)
success
    Optional callback for when app installation was successful
error
    Optional callback for when app installation resulted in error
errModalCallback
    Callback to pass into $.modal(...)
domContext
    Something other than document, useful for testing
navigator
    Something other than the global navigator, useful for testing

*/
exports.install = function(manifestUrl, opt) {
    opt = $.extend({'domContext': document,
                    'navigator': navigator,
                    'data': undefined}, opt || {});
    var self = apps,
        errSummary,
        $def = $.Deferred();
    /* Try and install the app. */
    if (opt.navigator.mozApps && opt.navigator.mozApps.install) {
        var installRequest = opt.navigator.mozApps.install(manifestUrl, opt.data);
        installRequest.onsuccess = function() {
            $def.resolve();
        };
        installRequest.onerror = function(errorOb) {
            switch (errorOb.code) {
                case 'denied':
                    break;
                case 'permissionDenied':
                    errSummary = gettext('App installation not allowed');
                    break;
                case 'manifestURLError':
                    errSummary = gettext('App manifest is malformed');
                    break;
                case 'networkError':
                    errSummary = gettext('App host could not be reached');
                    break;
                case 'manifestParseError':
                    errSummary = gettext('App manifest is unparsable');
                    break;
                case 'invalidManifest':
                    errSummary = gettext('App manifest is invalid');
                    break;
                default:
                    errSummary = gettext('Unknown error');
                    break;
            }
            $def.fail(errorOb, errSummary);
        };
    } else {
        $def.fail();        
    }
    return $def.promise();
};

})(typeof exports === 'undefined' ? (this.apps = {}) : exports);
