module('Homepage promos', {
    setup: function(hasAppsSupport, hasSeenAppsSupportWarning) {
        this.sandbox = tests.createSandbox('#amo-promos');
        this.visitor = z.Storage('visitor');
        this.KEY = 'amo_home_promo_seen';
        this.MAX_SEEN = 5;
        this._promo_seen = this.visitor.get(this.KEY);
        this.visitor.remove(this.KEY);
        hideHomePromo(this.sandbox);
    },
    teardown: function() {
        this.visitor.set(this.KEY, this._promo_seen);
        this.sandbox.remove();
    },
    check: function(showPromo, cnt) {
        var $panel = $('#starter', this.sandbox).closest('.panel');
        equal($panel.length, showPromo ? 1 : 0);
        equal(parseInt(this.visitor.get(this.KEY), 10), cnt || 0);
    }
});

test('No promos visible', function() {
    $('.panel', this.sandbox).remove('.panel');
    initPromos(this.sandbox);
    equal($('.slider:hidden', this.sandbox).length, 1);
});

test('Home promo visible', function() {
    this.check(true, 1);
});

test('Home promo not visible on 6th visit', function() {
    for (var i = 0; i < 5; i++) {
        hideHomePromo(this.sandbox);
    }
    this.check(false, 5);
});
