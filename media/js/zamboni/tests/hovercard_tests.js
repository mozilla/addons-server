$(document).ready(function(){

var hovercardFixture = {
    setup: function() {
        this.sandbox = tests.createSandbox('#hovercard-grid');
        this.grid = listing_grid.call(this.sandbox.find(".listing-grid"));
    },
    teardown: function() {
        this.sandbox.remove();
    }
};

module('hovercards', hovercardFixture);

test('paginator exists', function() {
    equals($('nav.pager', this.sandbox).length, 1);
});

test('paginator has correct number of pages', function() {
    equals($('nav.pager .dot', this.sandbox).length, 3);
});

test('paginator works properly', function() {
    this.grid.go(2);
    equals($('section:visible', this.sandbox).index(), 2);
});

});