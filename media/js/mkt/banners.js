(function() {
    if (!z.capabilities.localStorage || !localStorage.seen_beta_pitch) {
        $('.incompatible-browser').addClass('active');
        z.body.addClass('incompatible');
    }

    // Clicking cancel should dismiss notification boxes.
    z.body.on('click', '.incompatible-browser .close', function() {
        if (z.capabilities.localStorage) {
            localStorage.seen_beta_pitch = '1';
        }
        $('.incompatible-browser').removeClass('active');
        z.body.removeClass('incompatible');
    }).on('click', '.incompatible.button:not(.firefoxos)', _pd(function(e) {
        if (z.capabilities.localStorage) {
            delete localStorage.seen_beta_pitch;
        }
        $('.incompatible-browser').addClass('active');
        z.body.addClass('incompatible');
    }));

})();
