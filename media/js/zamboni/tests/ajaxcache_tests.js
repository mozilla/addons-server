module('Ajax Cache', {
    setup: function() {
        this.newItems = {'ajax': [], 'cache': []};
        z._AjaxCache = {};
        $.mockjaxClear();
        $.mockjaxSettings = {
            status: 200,
            responseTime: 0,
            contentType: 'text/json',
            dataType: 'json'
        };
    },
    teardown: function() {
        $.mockjaxClear();
    },
    query: function(term, url) {
        var self = this,
            results = [];
        if (url) {
            for (var i = 0; i < 10; i++) {
                results.push({'id': i, 'url': url});
            }
        } else {
            url = '/cacheMoney';
            results = [
                {'id': 1, 'url': 'gkoberger.net'},
                {'id': 2, 'url': 'gkoberger.net'},
                {'id': 3, 'url': 'gkoberger.net'}
            ];
        }
        $.mockjax({
            url: url,
            responseText: JSON.stringify(results),
            status: 200,
            responseTime: 0
        });

        var self = this;
        this.ajaxCalled = false;
        this.cacheCalled = false;
        return {
            url: url,
            data: {'q': term},
            ajaxSuccess: function(data, items) {
                self.newItems['ajax'].push(items);
                self.ajaxCalled = true;
            },
            cacheSuccess: function(data, items) {
                self.newItems['cache'].push(items);
                self.cacheCalled = true;
            }
        };
    },
    is_ajax: function() {
        equal(this.ajaxCalled, true);
        equal(this.cacheCalled, false);
    },
    is_cache: function() {
        equal(this.ajaxCalled, false);
        equal(this.cacheCalled, true);
    }
});


asyncTest('New request', function() {
    var self = this;

    $.ajaxCache(self.query('some term')).done(function() {
        self.is_ajax();
        start();
    });
});


asyncTest('Identical requests', function() {
    var self = this,
        request1,
        request2;

    request1 = $.ajaxCache(self.query('some term')).done(function() {
        self.is_ajax();

        // This request should be cached.
        request2 = $.ajaxCache(self.query('some term'));
        self.is_cache();

        // Ensure that we returned the correct items.
        tests.equalObjects(self.newItems['ajax'], self.newItems['cache']);

        // When the request is cached, we don't return an $.ajax request.
        equal(request2, undefined);

        start();
    });
});


asyncTest('Same URLs, unique parameters, same results', function() {
    var self = this,
        request1,
        request2,
        request3;

    request1 = $.ajaxCache(self.query('some term')).done(function() {
        // This is a cached request.
        request2 = $.ajaxCache(self.query('some term'));

        // This is a request with new parameters but will return same items.
        request3 = $.ajaxCache(self.query('new term')).done(function() {
            self.is_ajax();

            // We return `undefined` when items remain unchanged.
            equal(self.newItems['ajax'][1], undefined);

            start();
        });
    });
});


asyncTest('Unique URLs, same parameters, unique results', function() {
    var self = this,
        request1,
        request2;

    request1 = $.ajaxCache(self.query('some term', 'poop')).done(function() {
        self.is_ajax();

        // This is a new request with a different URL.
        request2 = $.ajaxCache(self.query('some term', 'crap')).done(function() {
            self.is_ajax();
            tests.notEqualObjects(self.newItems['ajax'][0],
                                  self.newItems['ajax'][1]);
            start();
        });
    });
});


asyncTest('Unique URLs, unique parameters, unique results', function() {
    var self = this,
        request1,
        request2;

    request1 = $.ajaxCache(self.query('some term', 'poop')).done(function() {
        self.is_ajax();

        // This is a new request with a different URL and different parameters.
        request2 = $.ajaxCache(self.query('diff term', 'crap')).done(function() {
            self.is_ajax();
            tests.notEqualObjects(self.newItems['ajax'][0],
                                  self.newItems['ajax'][1]);
            start();
        });
    });
});
