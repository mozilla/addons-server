$(document).ready(function(){

module('login', {
           setup: function() {this.sandbox = tests.createSandbox("#browserid-test");},
           teardown: function() {this.sandbox.remove();}
       });
asyncTest('Login failure (error from server)', function() {
    equal($(".primary .notification-box", this.sandbox).length, 0);
    function check() {
        $.mockjaxClear();
    };
    redirectAfterBrowserIDLogin = function() { start();};
    $.mockjax({url: '/en-US/firefox/users/browserid-login',
               response: check,
               status: 401});
    gotVerifiedEmail("browserid-assertion", "/", this.sandbox).fail(
        function() {
            equal($(".primary .notification-box h2", this.sandbox).text(),
                  'BrowserID login failed. Maybe you don\'t have an account'
                + ' under that email address?');
            $(".primary .notification-box", this.sandbox).remove();
            start();
        });
});

test('Login cancellation', function() {
    $.mockjax({url: '/en-US/firefox/users/browserid-login',
               response: function () {
                   ok(false, "XHR call made when user cancelled");
               }});
    equal(gotVerifiedEmail(null, "/", this.sandbox), null);
    equal($(".primary .notification-box", this.sandbox).length, 0);

    $.mockjaxClear();
});

asyncTest('Login success', function() {
    var ajaxCalled = false;
    equal($(".primary .notification-box", this.sandbox).length, 0);
    makeRedirectAfterBrowserIDLogin = function(to) {
        return function() { ajaxCalled = true; $.mockjaxClear();};
    };
    $.mockjax({url: '/en-US/firefox/users/browserid-login',
               response: function () {
                   return "win";
               },
               status: 200});
    gotVerifiedEmail("browserid-assertion", "/", this.sandbox).done(
        function() {
            ok(ajaxCalled);
            start();
        });
});
});