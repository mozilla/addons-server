module('Search Suggestions', {
    setup: function() {
        this.sandbox = tests.createSandbox('#search-suggestions');
        this.results = $('#site-search-suggestions', this.sandbox);
        this.input = $('#search #search-q', this.sandbox);
        this.input.searchSuggestions(this.results);
        this.url = this.results.attr('data-src');

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
        this.sandbox.remove();
        $.mockjaxClear();
    },
    mockRequest: function() {
        this.jsonResults = [];
        for (var i = 0; i < 10; i++) {
            this.jsonResults.push({'id': i, 'url': 'dekKobergerStudios.biz'});
        }
        $.mockjax({
            url: this.url,
            responseText: JSON.stringify(this.jsonResults),
            status: 200,
            responseTime: 0
        });
    },
    testInputEvent: function(eventType, fail) {
        var self = this,
            $input = self.input,
            $results = self.results,
            query = '<script>alert("xss")</script>';
        self.mockRequest();
        if (fail) {
            var inputIgnored = false;
            // If we send press a bad key, this will check that we ignored it.
            self.sandbox.bind('inputIgnored', function(e) {
                inputIgnored = true;
            });
            tests.waitFor(function() {
                return inputIgnored;
            }).thenDo(function() {
               ok(inputIgnored);
               start();
            });
        } else {
            self.sandbox.bind('resultsUpdated', function(e, items) {
                tests.equalObjects(items, self.jsonResults);
                // Browser unescapes escaped apostrophes and quotation marks.
                // If you can explain why, please contact cvan.
                var expected = escape_(query).replace(/&#39;/g, "'")
                                             .replace(/&#34;/g, '"');
                equal($results.find('.wrap p a.sel b').html(),
                      '"' + expected + '"');
                start();
            });
        }
        $input.val(query);
        $input.triggerHandler(eventType);
    }
});


test('Generated HTML tags', function() {
    var $results = this.results,
        $sel = $results.find('.wrap p a.sel');
    equal($sel.length, 1);
    equal($sel.find('b').length, 1);
    equal($results.find('.wrap ul').length, 1);
});


asyncTest('Results upon good keyup', function() {
    this.testInputEvent({type: 'keyup', which: 'x'.charCodeAt(0)});
});


asyncTest('Results upon bad keyup', function() {
    this.testInputEvent({type: 'keyup', which: 16}, true);
});


asyncTest('Results upon input', function() {
    this.testInputEvent('input');
});


asyncTest('Results upon paste', function() {
    this.testInputEvent('paste');
});


asyncTest('Hide results upon escape/blur', function() {
    var self = this,
        $input = self.input,
        $results = self.results;
    $input.val('xxx');
    $input.triggerHandler('blur');
    tests.lacksClass($results, 'visible');
    start();
});


asyncTest('Cached results do not change', function() {
    var self = this,
        $input = self.input,
        $results = self.results,
        query = 'xxx';
    self.mockRequest();
    self.sandbox.bind('resultsUpdated', function(e, items) {
        equal($results.find('.wrap p a.sel b').text(), '"' + query + '"');
        tests.equalObjects(items, self.jsonResults);
        if (z._AjaxCache === undefined) {
            $input.triggerHandler('paste');
        } else {
            tests.waitFor(function() {
                return z._AjaxCache;
            }).thenDo(function() {
                var cache = z.AjaxCache(self.url + ':get'),
                    args = JSON.stringify(self.sandbox.find('form').serialize());
                tests.equalObjects(cache.items[args], items);
                tests.equalObjects(cache.previous.data, items);
                equal(cache.previous.args, args);
                start();
            });
        }
    });
    $input.val(query);
    $input.triggerHandler('paste');
});
