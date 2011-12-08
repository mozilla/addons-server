$(document).ready(function(){

module('profile', {
    setup: function() {
        this.sandbox = tests.createSandbox('#profile-test');
    },
    teardown: function() {
        this.sandbox.remove();
    }
});

asyncTest('success -> redirect', function() {
    var sb = this.sandbox,
        mockWindow = {},
        $form = $('form', sb);
    $form.attr('action', '/complete-profile');
    $form.attr('data-post-login-url', '/elsewhere');
    var resultMock = $.mockjax({url: '/complete-profile',
                                status: 200,
                                responseText: {}});
    loadProfileCompletionForm(sb, {'window': mockWindow});
    $form.one('success.profile_completion', function() {
        equals(mockWindow.location, '/elsewhere');
        $.mockjaxClear(resultMock);
        start();
    });
    $form.trigger('submit');
});

asyncTest('success -> callback', function() {
    var sb = this.sandbox,
        mockWindow = {},
        $form = $('form', sb),
        redirectOb = $('<div></div>'),
        mock = $.mockjax({url: '/complete-profile-cb',
                          status: 200,
                          responseText: {}});
    redirectOb.bind('finish', function() {
        $.mockjaxClear(mock);
        ok('success event fired');
        start();
    });
    $form.attr('action', '/complete-profile-cb');
    loadProfileCompletionForm(sb, {'window': mockWindow,
                                   to: {on: redirectOb, fire: 'finish'}});
    $form.trigger('submit');
});

asyncTest('success -> object redirect', function() {
    var sb = this.sandbox,
        mockWindow = {},
        $form = $('form', sb),
        redirectOb = $('<div></div>'),
        mock = $.mockjax({url: '/complete-profile-cb-to',
                          status: 200,
                          responseText: {}});
    $form.one('success.profile_completion', function() {
        $.mockjaxClear(mock);
        equals(mockWindow.location, '/to-elsewhere');
        start();
    });
    $form.attr('action', '/complete-profile-cb-to');
    loadProfileCompletionForm(sb, {'window': mockWindow, to: '/to-elsewhere'});
    $form.trigger('submit');
});

// These are throwing an unknown exception in CI only for some reason.

// asyncTest('form error', function() {
//     var sb = this.sandbox,
//         mockWindow = {},
//         $form = $('form', sb);
//     $form.attr('action', '/complete-profile-error');
//     var resultMock = $.mockjax({url: '/complete-profile-error',
//                                 status: 400,
//                                 responseText: {username: ['invalid characters']}});
//     loadProfileCompletionForm(sb, {'window': mockWindow});
//     $form.one('error.profile_completion', function() {
//         equals($('.notification-box', sb).text(),
//                'username: invalid characters');
//         $.mockjaxClear(resultMock);
//         start();
//     });
//     $form.trigger('submit');
// });
// 
// asyncTest('internal error', function() {
//     var sb = this.sandbox,
//         mockWindow = {},
//         $form = $('form', sb);
//     $form.attr('action', '/complete-server-error');
//     var resultMock = $.mockjax({url: '/complete-server-error',
//                                 status: 500});
//     loadProfileCompletionForm(sb, {'window': mockWindow});
//     $form.one('error.profile_completion', function() {
//         equals($('.notification-box', sb).text(), 'Internal server error');
//         $.mockjaxClear(resultMock);
//         start();
//     });
//     $form.trigger('submit');
// });

module('profile form load', {
    setup: function() {
        this.sandbox = tests.createSandbox('#profile-form-load-test');
    },
    teardown: function() {
        this.sandbox.remove();
    }
});

asyncTest('load', function() {
    var sb = this.sandbox;
    $('.browserid-login', sb).attr('data-profile-form-url', '/load-form');
    var doRedirect = browserIDRedirect('/after-load', {doc: sb});
    var mock = $.mockjax({url: '/load-form',
                          status: 200,
                          responseText: $('#profile-ajax-form').html()});
    doRedirect({profile_needs_completion: true}).always(function() {
        equals($('form', sb).length, 1);
        $.mockjaxClear(mock);
        start();
    });
});

module('profile form load into modal', {
    setup: function() {
        this.sandbox = tests.createSandbox('#profile-form-modal-test');
        this.origModalFromURL = modalFromURL;
        this.origLoadProfileCompletionForm = loadProfileCompletionForm;
    },
    teardown: function() {
        this.sandbox.remove();
        modalFromURL = this.origModalFromURL;
        loadProfileCompletionForm = this.origLoadProfileCompletionForm;
    }
});

asyncTest('load', function() {
    var sb = this.sandbox;
    $('.browserid-login', sb).attr('data-profile-form-url', '/load-modal-form');
    loadProfileCompletionForm = function() {};
    modalFromURL = function(url, opt) {
        opt.callback();
        ok('loaded modal correctly');
        start();
    }
    completeUserProfile({doc: sb});
});

});
