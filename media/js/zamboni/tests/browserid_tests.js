$(document).ready(function(){

module('browserid login', {
           setup: function() {this.sandbox = tests.createSandbox("#browserid-test");},
           teardown: function() {this.sandbox.remove();}
       });

asyncTest('Login failure (error from server)', function() {
    var sandbox = this.sandbox;
    $('.browserid-login', sandbox).attr('data-url', '/browserid-login-fail');
    equal($(".primary .notification-box", sandbox).length, 0);
    browserIDRedirect = function() { start();};
    $.mockjax({url: '/browserid-login-fail',
               response: function() {},
               status: 401});
    gotVerifiedEmail("browserid-assertion", "/", sandbox).fail(
        function() {
            equal($(".primary .notification-box h2", sandbox).text().indexOf(
                  'BrowserID login failed. Maybe you don\'t have an account'
                + ' under that email address?'), 0);
            $(".primary .notification-box", sandbox).remove();
            start();
        });
});

test('Login cancellation', function() {
    var sandbox = this.sandbox;
    $('.browserid-login', sandbox).attr('data-url', '/browserid-login-cancel');
    $.mockjax({url: '/browserid-login-cancel',
               response: function () {
                   ok(false, "XHR call made when user cancelled");
               }});
    equal(gotVerifiedEmail(null, "/", sandbox), null);
    equal($(".primary .notification-box", sandbox).length, 0);
});

asyncTest('Login success', function() {
    var ajaxCalled = false,
        sandbox = this.sandbox;
    $('.browserid-login', sandbox).attr('data-url', '/browserid-login-success');
    equal($(".primary .notification-box", sandbox).length, 0);
    browserIDRedirect = function(to) {
        return function() { ajaxCalled = true; };
    };
    $.mockjax({url: '/browserid-login-success',
               response: function () {
                   return "win";
               },
               status: 200});
    gotVerifiedEmail("browserid-assertion", "/", sandbox).done(
        function() {
            ok(ajaxCalled);
            start();
        });
    });


asyncTest('Admin login failure', function() {
    var sandbox = this.sandbox;
    $('.browserid-login', sandbox).attr('data-url', '/browserid-login-fail');
    equal($(".primary .notification-box", sandbox).length, 0);
    browserIDRedirect = function() { start();};
    $.mockjax({url: '/browserid-login-fail',
               response: function() {},
               status: 405});
    gotVerifiedEmail('browserid-assertion', '/', sandbox).fail(
        function() {
            equal($('.primary .notification-box h2', sandbox).text(),
                  'Admins and editors must provide a password'
                + ' to log in.');
            $(".primary .notification-box", sandbox).remove();
            start();
        });
});

});