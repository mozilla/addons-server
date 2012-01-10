module('Autofill Platform for Search', {
    setup: function() {
        this._z = $.extend(true, {}, z);  // Deep copy `z` so we can patch.
        this.sandbox = tests.createSandbox('#search-box');
    },
    teardown: function() {
        z = this._z;
    }
});


test('Firefox using Firefox', function() {
    z.appMatchesUserAgent = true;
    z.app = 'firefox';
    z.browser.firefox = true;
    z.browserVersion = '10.0';
    z.platform = 'mac';
    autofillPlatform(this.sandbox);
    equal($('input[name=appver]', this.sandbox).val(), z.browserVersion);
    equal($('input[name=platform]', this.sandbox).val(), z.platform);
});


test('Thunderbird using Firefox', function() {
    z.appMatchesUserAgent = false;
    z.app = 'thunderbird';
    z.browser.firefox = true;
    z.browserVersion = '10.0';
    z.platform = 'mac';
    autofillPlatform(this.sandbox);
    equal($('input[name=appver]', this.sandbox).val(), '');
    equal($('input[name=platform]', this.sandbox).val(), '');
});


test('Thunderbird using Thunderbird', function() {
    z.appMatchesUserAgent = true;
    z.app = 'thunderbird';
    z.browser.thunderbird = true;
    z.browserVersion = '10.0';
    z.platform = 'mac';
    autofillPlatform(this.sandbox);
    equal($('input[name=appver]', this.sandbox).val(), z.browserVersion);
    equal($('input[name=platform]', this.sandbox).val(), z.platform);
});


module('Pjax Search', {
    setup: function() {
        this.container = $('#pjax-results', this.sandbox);
        this.filters = $('#search-facets', this.sandbox);
        this.container.initSearchPjax(this.filters);
    }
});


test('Loading', function() {
    var loaded = false;
    this.container.bind('search.loading', function() {
        loaded = true;
    });
    $.when(this.container.trigger('start.pjax')).done(function() {
        ok(loaded);
    })
});


test('Finished', function() {
    var finished = false;
    this.container.bind('search.finished', function() {
        finished = true;
    });
    $.when(this.container.trigger('end.pjax')).done(function() {
        ok(finished);
    })
});


test('Rebuild links', function() {
    function check(s, expected) {
        // rebuildLink accepts the following parameters:
        //     1) previous target URL,
        //     2) fixed URL params,
        //     3) new query string (i.e, location.search)
        equal(rebuildLink(s[0], s[1], s[2]), expected);
    }

    // We're showing results for Macs, so the filter URLs should get updated
    // to reflect that.
    check(['/en-US/firefox/search/?q=adblock&amp;appver=10.0',
           '{"appver": "10.0"}',
           '?q=adblock&platform=mac'],
          '/en-US/firefox/search/?q=adblock&platform=mac&appver=10.0');

    // We're showing results filtered by cat 14, so the filter URL for cat 72
    // should not change values.
    check(['/en-US/firefox/search/?q=adblock&amp;appver=8.0&amp;cat=72&amp;atype=1',
           '{"atype": 1, "cat": 72}',
           '?q=adblock&cat=14&atype=1'],
          '/en-US/firefox/search/?q=adblock&cat=72&atype=1');

    // We're showing results filtered by cat 14, so the filter URL to show
    // all categories/types should not contain cat=14.
    check(['/en-US/firefox/search/?q=adblock',
         '{"atype": null, "cat": null}',
         '?q=adblock&cat=14'],
        '/en-US/firefox/search/?q=adblock&cat=&atype=');
});
