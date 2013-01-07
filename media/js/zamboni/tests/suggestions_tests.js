module('Search Suggestions', {
    setup: function() {
        this.sandbox = tests.createSandbox('#search-suggestions');
        this.results = $('#site-search-suggestions', this.sandbox);
        this.input = $('#search #search-q', this.sandbox);
        this.input.searchSuggestions(this.results, processResults, true);
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
                var expected = escape_(query).replace(/&#39;/g, "'")
                                             .replace(/&#34;/g, '"');
                equal($results.find('.wrap p a.sel b').html(),
                      '"' + expected + '"');
                start();
            });
        }
        $input.val(query);
        $input.triggerHandler(eventType);
    },
    testRowSelector: function(eventWhich, rowIndex) {
        var $input = this.input,
            $results = this.results,
            expected = null;

        this.sandbox.bind('selectedRowUpdate', function(e, row) {
            expected = row;
        });

        tests.waitFor(function() {
            return expected !== null;
        }).thenDo(function() {
           // Row index is zero-based. There are four rows: one for the
           // placeholder and three results.
           equal(expected, rowIndex,
                 'Expected row ' + rowIndex + ' to be highlighted');
           start();
        });

        // Let's pretend we made a query. Generate three result rows.
        for (var i = 0; i < 3; i++) {
            $results.append('<li><a></li>');
        }

        // Initialize highlighting.
        $results.trigger('highlight', ['xxx']);

        // Simulate keystrokes.
        $input.val('xxx');
        $input.triggerHandler({type: 'keydown', which: eventWhich});
    },
    testKeyIgnored: function(event) {
        var $input = this.input,
            $results = this.results,
            expected = null;

        this.sandbox.bind('keyIgnored', function(e) {
            expected = true;
        });

        tests.waitFor(function() {
            return expected !== null;
        }).thenDo(function() {
            ok(expected, 'Key binding should have been ignored');
            start();
        });

        // Initialize highlighting.
        $results.trigger('highlight', ['xxx']);

        // Simulate keystrokes.
        $input.val('xxx').triggerHandler(event);
    }
});

function processResults(settings) {
    if (!settings || !settings.category) {
        return;
    }

    // Update the 'Search add-ons for <b>"{addon}"</b>' text.
    settings['$results'].find('p b').html(format('"{0}"',
                                                 settings.searchTerm));

    var li_item = template(
        '<li><a href="{url}"><span {cls} {icon}>{name}</span>{subtitle}</a></li>'
    );

    $.ajaxCache({
        url: settings['$results'].attr('data-src'),
        data: settings['$form'].serialize() + '&cat=' + settings.category,
        newItems: function(formdata, items) {
            var eventName;
            if (items !== undefined) {
                var ul = '';
                $.each(items, function(i, item) {
                    var d = {
                        url: escape_(item.url) || '#',
                        icon: '',
                        cls: '',
                        subtitle: '',
                    };
                    if (item.icon) {
                        d.icon = format(
                            'style="background-image:url({0})"',
                            escape_(item.icon)
                        );
                    }
                    if (item.cls) {
                        d.cls = format('class="{0}"',
                                       escape_(item.cls));
                        if (item.cls == 'cat') {
                            d.subtitle = format(
                                ' <em class="subtitle">{0}</em>',
                                gettext('Category')
                            );
                        }
                    }
                    if (item.name) {
                        d.name = escape_(item.name);
                        // Append the item only if it has a name.
                        ul += li_item(d);
                    }
                });
                settings['$results'].find('ul').html(ul);
            }
            settings['$results'].trigger('highlight', [settings.searchTerm])
                                .trigger('resultsUpdated', [items]);
        }
    });
}


test('Generated HTML tags', function() {
    var $results = this.results,
        $sel = $results.find('.wrap p a.sel');
    equal($sel.length, 1);
    equal($sel.find('b').length, 1);
    equal($results.find('.wrap ul').length, 1);
});


test('Default search label', function() {
    var $results = this.results,
        $input = this.input;
    function check(cat, expected) {
        $results.attr('data-cat', cat);
        $.when($input.searchSuggestions($results, processResults, true))
                     .done(function() {
            equal($results.find('p a.sel').text(), expected);
        });
    }
    check('',         'Search add-ons for {0}');
    check('all',      'Search add-ons for {0}');
    check('themes',   'Search themes for {0}');
    check('apps',     'Search apps for {0}');
});


test('Highlight search terms', function() {
    var items = [
        // Input, highlighted output
        ['', ''],
        ['x xx', 'x xx'],
        ['xxx', '<b>xxx</b>'],
        [' XxX', ' <b>XxX</b>'],
        ['XXX', '<b>XXX</b>'],
        ['An XXX-rated add-on', 'An <b>XXX</b>-rated add-on'],
        ['Myxxx', 'My<b>xxx</b>'],
        ['XXX xxx XXX', '<b>XXX</b> <b>xxx</b> <b>XXX</b>'],

        // Ignore non-alphanumeric characters (i.e., regex chars).
        ['xxx: xxx', '<b>xxx</b>: <b>xxx</b>'],
        ['xxx (){}[]*+:=?!\|^$. xxx', '<b>xxx</b> (){}[]*+:=?!\|^$. <b>xxx</b>']
    ];

    var $ul = $('<ul>');
    _.each(items, function(element) {
        $ul.append($('<li>', {'html': element[0]}));
    });

    $.when($ul.find('li').highlightTerm('xxx')).done(function() {
        $ul.find('li').each(function(index) {
            equal($(this).html(), items[index][1]);
        });
    });
});


asyncTest('Results upon good keyup', function() {
    this.testInputEvent({type: 'keyup', which: 'x'.charCodeAt(0)});
});


asyncTest('Results upon bad keyup', function() {
    this.testInputEvent({type: 'keyup', which: 16}, true);
});


asyncTest('Results upon paste', function() {
    this.testInputEvent('paste');
});


asyncTest('Hide results upon escape/blur', function() {
    var $input = this.input,
        $results = this.results;
    $input.val('xxx').triggerHandler('blur');
    tests.lacksClass($results, 'visible');
    start();
});


asyncTest('Key bindings: Hijacked: arrow up', function() {
    this.testRowSelector(z.keys.UP, 0);
});
asyncTest('Key bindings: Hijacked: arrow down', function() {
    this.testRowSelector(z.keys.DOWN, 1);
});


asyncTest('Key bindings: Ignored: home', function() {
    this.testKeyIgnored({type: 'keydown', which: z.keys.HOME});
});
asyncTest('Key bindings: Ignored: end', function() {
    this.testKeyIgnored({type: 'keydown', which: z.keys.END});
});
asyncTest('Key bindings: Ignored: page up', function() {
    this.testKeyIgnored({type: 'keydown', which: z.keys.PAGE_UP});
});
asyncTest('Key bindings: Ignored: page down', function() {
    this.testKeyIgnored({type: 'keydown', which: z.keys.PAGE_DOWN});
});


asyncTest('Key bindings: Ignored: alt + home', function() {
    this.testKeyIgnored({type: 'keydown', which: z.keys.HOME, altKey: true});
});
asyncTest('Key bindings: Ignored: ctrl + home', function() {
    this.testKeyIgnored({type: 'keydown', which: z.keys.HOME, ctrlKey: true});
});
asyncTest('Key bindings: Ignored: meta + home', function() {
    this.testKeyIgnored({type: 'keydown', which: z.keys.HOME, metaKey: true});
});
asyncTest('Key bindings: Ignored: shift + home', function() {
    this.testKeyIgnored({type: 'keydown', which: z.keys.HOME, shiftKey: true});
});


asyncTest('Key bindings: Ignored: alt + end', function() {
    this.testKeyIgnored({type: 'keydown', which: z.keys.END, altKey: true});
});
asyncTest('Key bindings: Ignored: ctrl + end', function() {
    this.testKeyIgnored({type: 'keydown', which: z.keys.END, ctrlKey: true});
});
asyncTest('Key bindings: Ignored: meta + end', function() {
    this.testKeyIgnored({type: 'keydown', which: z.keys.END, metaKey: true});
});
asyncTest('Key bindings: Ignored: shift + end', function() {
    this.testKeyIgnored({type: 'keydown', which: z.keys.END, shiftKey: true});
});


asyncTest('Key bindings: Ignored: alt + left', function() {
    this.testKeyIgnored({type: 'keydown', which: z.keys.LEFT, altKey: true});
});
asyncTest('Key bindings: Ignored: alt + right', function() {
    this.testKeyIgnored({type: 'keydown', which: z.keys.RIGHT, altKey: true});
});


asyncTest('Key bindings: Ignored: ctrl + left', function() {
    this.testKeyIgnored({type: 'keydown', which: z.keys.LEFT, ctrlKey: true});
});
asyncTest('Key bindings: Ignored: ctrl + right', function() {
    this.testKeyIgnored({type: 'keydown', which: z.keys.RIGHT, ctrlKey: true});
});


asyncTest('Key bindings: Ignored: meta + left', function() {
    this.testKeyIgnored({type: 'keydown', which: z.keys.LEFT, metaKey: true});
});
asyncTest('Key bindings: Ignored: meta + right', function() {
    this.testKeyIgnored({type: 'keydown', which: z.keys.RIGHT, metaKey: true});
});


asyncTest('Key bindings: Ignored: shift + left', function() {
    this.testKeyIgnored({type: 'keydown', which: z.keys.LEFT, shiftKey: true});
});
asyncTest('Key bindings: Ignored: shift + right', function() {
    this.testKeyIgnored({type: 'keydown', which: z.keys.RIGHT, shiftKey: true});
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
                    fields = self.sandbox.find('form').serialize(),
                    args = JSON.stringify(fields + '&cat=' + $results.attr('data-cat'));
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
