/*
    Provides the apps module, a wrapper around navigator.mozApps
*/
(function(exports) {
"use strict";

/*

apps.install(manifest_url, options)

It's just like navigator.apps.install with the following enhancements:
- If navigator.apps.install doesn't exist, an error is displayed
- If the install resulted in errors, they are displayed to the user

This requires at least one apps-error-msg div to be present.

See also: https://developer.mozilla.org/en-US/docs/Apps/Apps_JavaScript_API/navigator.mozApps.install

The recognized option attributes are as follows:

data
    Optional dict to pass as navigator.apps.install(url, data, ...)
success
    Optional callback for when app installation was successful
error
    Optional callback for when app installation resulted in error
domContext
    Something other than document, useful for testing
navigator
    Something other than the global navigator, useful for testing

*/
exports.install = function(product, opt) {
    opt = $.extend({'domContext': document,
                    'navigator': navigator,
                    'data': {}},
                   opt || {});
    opt.data.categories = product.categories;
    var self = apps,
        errSummary,
        manifest_url = product.manifest_url,
        $def = $.Deferred();

    /* Try and install the app. */
    if (manifest_url && opt.navigator.mozApps && opt.navigator.mozApps.install) {
        /* TODO: combine the following check with the above. But don't stop
         * clients without installPackage from using apps for now.
         */
        if (product.is_packaged && !opt.navigator.mozApps.installPackage && !manifest_url) {
            $def.reject();
        }
        var installRequest;
        if (product.is_packaged) {
            installRequest = opt.navigator.mozApps.installPackage(manifest_url, opt.data);
        } else {
            installRequest = opt.navigator.mozApps.install(manifest_url, opt.data);
        }
        installRequest.onsuccess = function() {
            var status;
            var isInstalled = setInterval(function() {
                // "status" is now deprecated in favor of "installState" (bug 796016).
                status = installRequest.result.status || installRequest.result.installState;
                if (status == 'installed') {
                    clearInterval(isInstalled);
                    $def.resolve(installRequest.result, product);
                }
            }, 100);
        };
        installRequest.onerror = function() {
            // The JS shim still uses this.error instead of this.error.name.
            $def.reject(installRequest.result, product, this.error.name || this.error);
        };
    } else {
        $def.reject();
    }
    return $def.promise();
};

exports.lookupError = function(msg) {
    switch (msg) {
        // mozApps error codes, defined in
        // https://developer.mozilla.org/en-US/docs/Apps/Apps_JavaScript_API/Error_object
         case 'MANIFEST_URL_ERROR':
            msg = gettext('The manifest could not be found at the given location.');
            break;
        case 'NETWORK_ERROR':
            msg = gettext('App host could not be reached.');
            break;
        case 'MANIFEST_PARSE_ERROR':
            msg = gettext('App manifest is unparsable.');
            break;
        case 'INVALID_MANIFEST':
            msg = gettext('App manifest is invalid.');
            break;
        case 'REINSTALL_FORBIDDEN':
            msg = gettext('App is already installed.');
            break;
        // Marketplace specific error codes.
        case 'MKT_SERVER_ERROR':
            msg = gettext('Internal server error.');
            break;
        case 'MKT_INSTALL_ERROR':
            msg = gettext('Internal server error on app installation.');
            break;
        default:
            msg = gettext('Install failed. Please try again later.');
            break;
    }
    return msg;
}

})(typeof exports === 'undefined' ? (this.apps = {}) : exports);
