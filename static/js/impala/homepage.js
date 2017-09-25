(function () {
    $('.toplist .name').truncate({showTitle: true});

    initPromos();
    $(document).on('promos_shown', function(e, $promos) {
        hideHomePromo();
        $promos.slideDown('slow')
               .append('<a href="#" class="control prev">&laquo;</a>\
                        <a href="#" class="control next">&raquo;</a>');
        $('div', $promos).zCarousel({
            circular: true,
            btnPrev: $('.prev', $promos),
            btnNext: $('.next', $promos)
        });

        // Intialize the pager for any paging promos
        $('.pager', $promos).promoPager();

        $('.addons h3', $promos).truncate({dir: 'h'});
        $('.addons .desc', $promos).truncate({dir: 'v'});
        $('.install', $promos).installButton();
        var $disabled = $('.disabled, .concealed', $promos);
        if ($disabled.length) {
            $disabled.closest('.wrap').addClass('hide-install');
        }
        $('#monthly .blurb > p').lineclamp(4);
        $('#featuredaddon .blurb > p').lineclamp(4);
        $('.ryff .desc').lineclamp(6);
        $('h2:not(.multiline)', $promos).linefit();
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
