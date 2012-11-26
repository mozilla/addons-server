(function() {
    if (!z.capabilities.localStorage || !localStorage.seen_beta_pitch) {
        $('.incompatible-browser').addClass('active');
    }

    // Clicking cancel should dismiss notification boxes.
    z.body.on('click', '.incompatible-browser .close', function() {
        if (z.capabilities.localStorage) {
            localStorage.seen_beta_pitch = '1';
        }
        $('.incompatible-browser').removeClass('active');
    }).on('click', '.incompatible.button', _pd(function(e) {
        if (z.capabilities.localStorage) {
            delete localStorage.seen_beta_pitch;
        }
        $('.incompatible-browser').addClass('active');
    }));

})();
