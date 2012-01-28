(function () {
    $('.toplist .name').truncate({showTitle: true});

    initPromos();
    $(document).bind('promos_shown', function(e, $promos) {
        hideHomePromo();
        $promos.slideDown('slow')
               .append('<a href="#" class="control prev">&laquo;</a>\
                        <a href="#" class="control next">&raquo;</a>');
        $('div', $promos).zCarousel({
            circular: true,
            btnPrev: $('.prev', $promos),
            btnNext: $('.next', $promos)
        });
        $('.addons h3', $promos).truncate({dir: 'h'});
        $('.addons .desc', $promos).truncate({dir: 'v'});
        $('.install', $promos).installButton();
        $('#monthly .blurb > p').lineclamp(4);
        $('h2', $promos).linefit();
    });
})();


function hideHomePromo($context) {
    if (typeof $context === 'undefined') {
        $context = $(document.body);
    }
    if (!$('#promos', $context).length) {
        return;
    }
    // Show the intro to anon users for 5 visits, then switch to second item.
    var KEY = 'amo_home_promo_seen',
        MAX_SEEN = 5,
        visitor = z.Storage('visitor'),
        times_seen = parseInt(visitor.get(KEY) || 0, 10);
    if (times_seen >= MAX_SEEN) {
        // If the intro has been seen enough times, skip it.
        $('#starter', $context).closest('.panel').remove();
    } else {
        // Otherwise, count another appearance and stash in localStorage.
        visitor.set(KEY, times_seen + 1);
    }
}
