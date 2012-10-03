$(document).ready(function(){


module('apps errors', {
    setup: function() {
        this.sandbox = tests.createSandbox('#apps-error-msg');
        $('.modal', this.sandbox).hide();
    },
    teardown: function() {
        this.sandbox.remove();
    },
    installAppWithError: function(manifestUrl, errorOb, errModalCallback) {
        var sb = this.sandbox,
            nav = {};
        nav.mozApps = {
            install: function(manifestUrl, data, success, error) {
                error(errorOb);
            }
        };
        if (!errModalCallback) {
            errModalCallback = function() {
                // False tells the modal code not to execute all the dom
                // re-positioning for rendering. Otherwise this makes
                // verifying the sandbox hard.
                return false;
            };
        }
        apps.install(manifestUrl, {domContext: sb,
                                   navigator: nav,
                                   errModalCallback: errModalCallback});
    }
});


asyncTest('test permission error', function() {
    var sb = this.sandbox;
    $(sb).one('error_shown.apps', function() {
        equals($('.apps-error-msg h2', sb).text(),
               'App installation not allowed.');
        equals($('.apps-error-msg p', sb).text(), 'detailed message');
        start();
    });
    this.installAppWithError('http://nice.com/nice.webapp',
                             {code: 'permissionDenied',
                              message: "detailed message"});
});


test('test user canceled', function() {
    var sb = this.sandbox,
        callback;
    callback = function() {
        ok(false, 'dialog should not be shown when a user cancels install');
        return false;
    };
    this.installAppWithError('http://nice.com/nice.webapp',
                             {code: 'denied',
                              message: 'user canceled installation'},
                             callback);
});


asyncTest('test unexpected error', function() {
    var sb = this.sandbox;
    $(sb).one('error_shown.apps', function() {
        equals($('.apps-error-msg h2', sb).text(),
               'Install failed. Please try again later.');
        equals($('.apps-error-msg p', sb).text(), 'surprise');
        start();
    });
    this.installAppWithError('http://nice.com/nice.webapp', {code: 'bogus',
                                                             message: "surprise"});
});


test('test successful app install', function() {
    var sb = this.sandbox,
        nav = {},
        callback;
    nav.mozApps = {
        install: function(manifestUrl, data, success, error) {}
    };
    callback = function() {
        ok(false, 'dialog should not be shown on successful app install');
        return false;
    };
    apps.install('http://nice.com/nice.webapp', {domContext: sb,
                                                 navigator: nav,
                                                 errModalCallback: callback});
});


asyncTest('test append to visible modal', function() {
    var $sb = $(this.sandbox);
    // Simulate a popup:
    $sb.append('<div class="existing modal"><div class="modal-inside"></div></div>');
    $sb.one('error_shown.apps', function() {
        equals($('.existing h2', $sb).text(),
               'App installation not allowed.');
        equals($('.existing p', $sb).text(),
               'detailed message');
        start();
    });
    this.installAppWithError('http://nice.com/nice.webapp',
                             {code: 'permissionDenied',
                              message: "detailed message"});
});


module('apps as wrapper', {
    setup: function() {
        this.sandbox = tests.createSandbox('#apps-error-msg');
        $('.modal', this.sandbox).hide();
    },
    teardown: function() {
        this.sandbox.remove();
    }
});


asyncTest('success callback', function() {
    var sb = this.sandbox,
        nav = {},
        callback;
    nav.mozApps = {
        install: function(manifestUrl, data, success, error) {
            success();
        }
    };
    callback = function() {
        ok(true, 'success was called');
        start();
    }
    apps.install('http://nice.com/nice.webapp', {domContext: sb,
                                                 navigator: nav,
                                                 success: callback});
});


asyncTest('install error: system unsupported', function() {
    var sb = this.sandbox,
        nav = {};
    $(sb).one('mobile_error_shown.apps', function() {
        equal($('.apps-error-msg h2', sb).text(), 'App installation failed.');
        equal($('.apps-error-msg p', sb).text(), 'This system does not support installing apps.');
        start();
    });
    apps.install('http://nice.com/nice.webapp', {domContext: sb, navigator: nav, mobile: true});
});


asyncTest('data', function() {
    var sb = this.sandbox,
        nav = {},
        callback,
        dataReceived;
    nav.mozApps = {
        install: function(manifestUrl, data, success, error) {
            dataReceived = data;
            success();
        }
    };
    callback = function() {
        equals(dataReceived.receipt, '<receipt>');
        start();
    }
    apps.install('http://nice.com/nice.webapp', {domContext: sb,
                                                 navigator: nav,
                                                 success: callback,
                                                 data: {receipt: '<receipt>'}});
});


asyncTest('error callback', function() {
    var sb = this.sandbox,
        nav = {},
        callback;
    nav.mozApps = {
        install: function(manifestUrl, data, success, error) {
            error({code: 'someCode', message: 'some message'});
        }
    };
    callback = function(errOb) {
        equals(errOb.code, 'someCode');
        start();
    }
    apps.install('http://nice.com/nice.webapp', {domContext: sb,
                                                 navigator: nav,
                                                 errModalCallback: function() { return false; },
                                                 error: callback});
});


});
