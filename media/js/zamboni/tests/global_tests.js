$(document).ready(function(){

function _inspectHeaders(inspector, url) {
    var headersInspected = false,
        url = url || '/local-request-for-csrf.json';
    $.mockjax({
        url: url,
        status: 200,
        response: function(settings) {
            inspector(this.headers);
            headersInspected = true;
        }
    });
    $.ajax({
        url: url,
        type: 'post',
        data: 'foo=bar',
        success: function(response) {},
        error: function(xhr) {
            console.log('ajax request Failed');
        }
    });
    tests.waitFor(function() {
        return headersInspected;
    }).thenDo(function() {
        start();
    });
}

module('CSRF Token from input', {
    setup: function() {
        this._csrf = $.cookie('csrftoken');
        $.cookie('csrftoken', '');
        this.sandbox = tests.createSandbox('#csrf-template');
    },
    teardown: function() {
        $.mockjaxClear();
        this.sandbox.remove();
        if (this._csrf) {
            $.cookie('csrftoken', this._csrf);
        }
    }
});

asyncTest('header sent', function() {
    _inspectHeaders(function(headers) {
        equals(headers['X-CSRFToken'], '<csrf-from-input>');
    });
});

module('CSRF Token from cookie', {
    setup: function() {
        this._csrf = $.cookie('csrftoken');
        $.cookie('csrftoken', '<csrf-cookie>');
    },
    teardown: function() {
        $.mockjaxClear();
        if (this._csrf) {
            $.cookie('csrftoken', this._csrf);
        }
    }
});

asyncTest('header sent', function() {
    _inspectHeaders(function(headers) {
        equals(headers['X-CSRFToken'], '<csrf-cookie>');
    });
});

module('CSRF Token: remote', {
    teardown: function() {
        $.mockjaxClear();
    }
});

asyncTest('CSRF not sent', function() {
    _inspectHeaders(function(headers) {
        var htype = typeof headers['X-CSRFToken'];
        equals(htype, 'undefined');
    }, 'http://someserver/hijack');
});

asyncTest('CSRF not sent', function() {
    _inspectHeaders(function(headers) {
        var htype = typeof headers['X-CSRFToken'];
        equals(htype, 'undefined');
    }, 'https://someserver/hijack');
});

asyncTest('CSRF not sent', function() {
    _inspectHeaders(function(headers) {
        var htype = typeof headers['X-CSRFToken'];
        equals(htype, 'undefined');
    }, '//someserver/hijack');
});

asyncTest('CSRF not sent', function() {
    _inspectHeaders(function(headers) {
        var htype = typeof headers['X-CSRFToken'];
        equals(htype, 'undefined');
    }, '://someserver/hijack');
});

});
