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
exports.install = function(manifest_url, opt) {
    opt = $.extend({'domContext': document,
                    'navigator': navigator,
                    'data': undefined,
                    'success': undefined,
                    'error': undefined,
                    'errModalCallback': undefined}, opt || {});
    var self = apps,
        errSummary,
        showError = true;
    /* Try and install the app. */
    if (opt.navigator.mozApps && opt.navigator.mozApps.install) {
        opt.navigator.mozApps.install(manifest_url, opt.data, opt.success, function(errorOb) {
            switch (errorOb.code) {
                case 'denied':
                    // User canceled installation.
                    showError = false;
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
            if (showError) {
                self._showError(errSummary, errorOb.message, opt);
            }
            if (opt.error) {
                opt.error.call(this, errorOb);
            }
        });
    } else {
        self._showError(gettext('App installation failed'),
                        gettext('This system does not support installing apps'),
                        opt);
    }
};

exports._showError = function(errSummary, errMessage, opt) {
    var $errTarget = $('<a>'),
        $visibleModals,
        $innerErr,
        win = opt.window || window;
    if (opt.mobile) {
        $('.apps-error-msg h2', opt.domContext).text(errSummary);
        $('.apps-error-msg p', opt.domContext).text(errMessage);
        $('.apps-error-msg', opt.domContext).show();
        $(opt.domContext).trigger('mobile_error_shown.apps');
    } else {
        $visibleModals = $('.modal:visible', opt.domContext);
        if ($visibleModals.length) {
            $innerErr = $('.inner-modal-error', $visibleModals);
            if (!$innerErr.length) {
                $innerErr = $('<div class="inner-modal-error"><h2></h2><p></p></div>');
                $('.modal-inside', $visibleModals).prepend($innerErr);
            }
            $('h2', $innerErr).text(errSummary);
            $('p', $innerErr).text(errMessage);
            $(win).trigger('resize');
        } else {
            // Create a new modal:
            $('.apps-error-msg:first', opt.domContext).modal($errTarget,
                                                             {width: '400px', close: true,
                                                              callback: opt.errModalCallback});
            $errTarget.trigger('click');  // show the modal
            $('.apps-error-msg h2', opt.domContext).text(errSummary);
            $('.apps-error-msg p', opt.domContext).text(errMessage);
        }
        $(opt.domContext).trigger('error_shown.apps');
    }

};

})(typeof exports === 'undefined' ? (this.apps = {}) : exports);
