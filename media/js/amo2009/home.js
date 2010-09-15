$(document).ready(function() {
    var homepageSlider = AmoSlideshow();
    if ($(document.body).hasClass('user-login')) {
        // If the user login detected, switch to the second item to skip intro.
        homepageSlider.moveToItem(2);
    } else {
        // Show the intro to anon users for 5 visits, then switch to second item.
        var SEEN_COOKIE = 'amo_home_promo_seen',
            MAX_SEEN    = 5,
            times_seen  = parseInt($.cookie(SEEN_COOKIE));
        if (!times_seen) times_seen = 0;

        if (times_seen >= MAX_SEEN) {
            // If the intro has been seen enough times, skip it.
            // disabling this for Firefox Cup. TODO potch re-enable this.
            // homepageSlider.moveToItem(2);
        } else {
            // Otherwise, count another appearance and stash in a cookie.
            $.cookie(SEEN_COOKIE, times_seen + 1, {
                path: '/',
                expires: (new Date()).getTime() + ( 1000 * 60 * 60 * 24 * 365 )
            });
        }
    }

});
