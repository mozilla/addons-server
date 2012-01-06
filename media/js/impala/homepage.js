(function () {
    initPromos();
})();


function initPromos($context) {
    if (typeof $context === 'undefined') {
        $context = $(document.body);
    }
    var $promos = $('#promos[data-promo-url]', $context);
    if (!$promos.length) {
        return;
    }
    $promos.show();
    var promos_base = $promos.attr('data-promo-url'),
        promos_url = format('{0}?version={1}&platform={2}',
                            promos_base, z.browserVersion, z.platform);
    if (z.badBrowser) {
        promos_url = format('{0}?version={1}&platform={2}',
                            promos_base, '5.0', 'mac');
    }
    $.get(promos_url, function(resp) {
        $('ul', $promos).append($(resp));
        hideHomePromo();
        $promos.append('<a href="#" class="control prev">&laquo;</a>\
                        <a href="#" class="control next">&raquo;</a>');
        var $q = $('div', $promos).zCarousel({
            circular: true,
            btnPrev: $('.prev', $promos),
            btnNext: $('.next', $promos)
        });
        $('.addons h3', $promos).truncate({dir: 'h'});
        $('.addons .desc', $promos).truncate({dir: 'v'});
        $('#monthly .blurb > p').truncate({dir: 'v'});
        $('.install', $promos).installButton();
    });
    $('.toplist .name').truncate({showTitle: true});
}


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
