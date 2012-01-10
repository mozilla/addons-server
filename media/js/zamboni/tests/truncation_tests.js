module('Truncation', {
    setup: function() {
        this.sandbox = tests.createSandbox();
    }
});


test('lineclamp: none', function() {
    var $src = $('<p>ballin</p>').appendTo(this.sandbox);

    // Check that we return the same thing.
    equal($src.lineclamp(), $src);

    // Check that `max-height` was not set.
    equal($src.css('max-height'), 'none');
});


test('lineclamp: round', function() {
    var $src = $('<p>ballin</p>').appendTo(this.sandbox);

    // Set some arbitrary `line-height`.
    $src.css('line-height', '14.2px');

    // Check that we return the same thing.
    equal($src.lineclamp(1), $src);

    // If we're clamping one line with a `line-height` of 14.2px, then the
    // `max-height` should be 15px.
    equal($src.css('max-height'), '15px');
});


test('lineclamp: normal', function() {
    var $src = $('<p>ballin</p>').appendTo(this.sandbox);

    // Set some arbitrary `line-height`.
    $src.css('line-height', '15px');

    // Check that we return the same thing.
    equal($src.lineclamp(2), $src);

    // If we're clamping two lines whose `line-height` are 15px, then the
    // `max-height` should be 50px.
    equal($src.css('max-height'), '30px');
});
