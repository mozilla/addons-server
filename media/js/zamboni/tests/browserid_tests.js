$(document).ready(function(){
module('browserid setup', {
        setup: function() {
          $(window).undelegate('.browserid-login', 'click');
          this.sandbox = tests.createSandbox('#browserid-test');
          this.originalGVE = gotVerifiedEmail;
          this.originalID = navigator.id;
          var that = this;
          gotVerifiedEmail = function(x, y){
            that.assertion = x;
            that.to = y;
          };
        },
        teardown: function() {
          gotVerifiedEmail = this.originalGVE;
          navigator.id = this.originaID;
          this.sandbox.remove();
        }
});
test('Setup with redirect', function() {
       var win = {
         'location': {'href': '/users/login?to=/en-US/firefox/'}
       };
       navigator.id = {
         'getVerifiedEmail': function (f) {
          f('fake-assertion');
         }
       };
       initBrowserID(win, this.sandbox);
       $('.browserid-login', this.sandbox).eq(0).click();
       equal(this.to, '/en-US/firefox/');
       equal(this.assertion, 'fake-assertion');
     });

test('Setup with absolute redirect', function() {
       var win = {
         'location': {'href': 'http://evilsite.com/badnews/'}
       };
       navigator.id = {
         'getVerifiedEmail': function (f) {
          f('fake-assertion');
         }
       };
       initBrowserID(win, this.sandbox);
       $('.browserid-login').click();
       equal(this.to, '/');
       equal(this.assertion, 'fake-assertion');
     });

test('Setup with no redirect', function() {
       var win = {
         'location': {'href': '/users/login'}
       };
       navigator.id = {
         'getVerifiedEmail': function (f) {
          f('fake-assertion');
         }
       };
       initBrowserID(win, this.sandbox);
       $('.browserid-login').click();
       equal(this.to, '/');
       equal(this.assertion, 'fake-assertion');
     });

test('Setup with no redirect from non login page', function() {
       var win = {
         'location': {'href': '/users/test'}
       };
       navigator.id = {
         'getVerifiedEmail': function (f) {
          f('fake-assertion');
         }
       };
       initBrowserID(win, this.sandbox);
       $('.browserid-login').click();
       equal(this.to, '/users/test');
       equal(this.assertion, 'fake-assertion');
     });

module('browserid login', {
         setup: function() {
             this.origRedirect = browserIDRedirect;
             this.sandbox = tests.createSandbox('#browserid-test');
         },
         teardown: function() {
             this.sandbox.remove();
             browserIDRedirect = this.origRedirect;
         }
       });


asyncTest('Login failure (error from server)', function() {
    var sandbox = this.sandbox;
    $('.browserid-login', sandbox).attr('data-url', '/browserid-login-fail');
    equal($('.primary .notification-box', sandbox).length, 0);
    browserIDRedirect = function() {};
    var i = $.mockjax({url: '/browserid-login-fail',
                       responseText: '',
                       status: 401});
    gotVerifiedEmail('browserid-assertion', '/', sandbox).always(
        function(ex) {
            equal($('.primary .notification-box h2', sandbox).text().indexOf(
                  "BrowserID login failed. Maybe you don't have an account"
                + ' under that email address?'), 0);
            $('.primary .notification-box', sandbox).remove();
            $.mockjaxClear(i);
            start();
        });
});

asyncTest('Login failure (message from server)', function() {
    var TESTMSG = 'Example error message';
    var sandbox = this.sandbox;
    $('.browserid-login', sandbox).attr('data-url', '/browserid-login-fail');
    equal($('.primary .notification-box', sandbox).length, 0);
    browserIDRedirect = function() { };
    var i = $.mockjax({url: '/browserid-login-fail',
                       responseText: TESTMSG,
                       status: 401});
    gotVerifiedEmail('browserid-assertion', '/', sandbox).fail(
        function() {
            equal($('.primary .notification-box h2', sandbox).text().indexOf(
                  TESTMSG), 0);
            $('.primary .notification-box', sandbox).remove();
            $.mockjaxClear(i);
            start();
        });
});


test('Login cancellation', function() {
    var sandbox = this.sandbox;
    $('.browserid-login', sandbox).attr('data-url', '/browserid-login-cancel');
    var i = $.mockjax({url: '/browserid-login-cancel',
               response: function () {
                   ok(false, 'XHR call made when user cancelled');
               }});
    equal(gotVerifiedEmail(null, '/', sandbox), null);
    equal($('.primary .notification-box', sandbox).length, 0);
    $.mockjaxClear(i);
});

asyncTest('Login success', function() {
    var ajaxCalled = false,
        sandbox = this.sandbox;
    $('.browserid-login', sandbox).attr('data-url', '/browserid-login-success');
    equal($('.primary .notification-box', sandbox).length, 0);
    browserIDRedirect = function(to) {
        return function() { ajaxCalled = true; };
    };
    var i = $.mockjax({url: '/browserid-login-success',
               responseText: '',
               status: 200});
    gotVerifiedEmail('browserid-assertion', '/', sandbox).done(
        function() {
            ok(ajaxCalled);
            $.mockjaxClear(i);
            start();
        });
    });


asyncTest('Admin login failure', function() {
    var sandbox = this.sandbox;
    $('.browserid-login', sandbox).attr('data-url', '/browserid-login-fail');
    equal($('.primary .notification-box', sandbox).length, 0);
    browserIDRedirect = function() {};
    var i = $.mockjax({url: '/browserid-login-fail',
                       responseText: '',
                       status: 400});
    gotVerifiedEmail('browserid-assertion', '/', sandbox).fail(
        function() {
            equal($('.primary .notification-box h2', sandbox).text(),
                  'Admins and editors must provide a password'
                + ' to log in.');
            $('.primary .notification-box', sandbox).remove();
            $.mockjaxClear(i);
            start();
        });
});

});
