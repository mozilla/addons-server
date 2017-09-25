function initPromos($context, module_context, version, platform) {
    if (!$context) {
        $context = $(document.body);
    }
    var $promos = $('#promos[data-promo-url]', $context);
    if (!$promos.length) {
        return;
    }
    var promo_url = $promos.attr('data-promo-url');
    if (!version) {
        version = z.browserVersion;
    }
    if (!platform) {
        platform = z.platform;
    }
    if (z.badBrowser && !version && !platform) {
        version = '5.0';
        platform = 'mac';
    }
    var data = {};
    if (module_context != 'discovery') {
        // The version + platform are passed in the `promo_url` for the
        // discopane promos because when we serve static assets the
        // `?build=<BUILD_ID>` cachebustage kills our querystring.
        data = {version: version, platform: platform};
    }
    $.get(promo_url, data, function(resp) {
        $('.slider', $promos).append($(resp));
        if ($('.panel', $promos).length) {
            // Show promo module only if we have at least panel.
            $promos.trigger('promos_shown', [$promos]);
            $('.persona-preview', $promos).previewPersona(true);
        }
        // Hide panel is we have no promos to show
        if (resp !== '' && $('body.restyle').length === 1) {
            $('#page > .secondary').addClass('shift-secondary');
            $('#background-wrapper').addClass('carousel-header');
            $('#promos').addClass('show');
            $('#side-nav').addClass('expanded');
            // .4px needed to fix half-pixel issue in FF.
            var extraHeight = $('body.restyle').length ? 24.4 : 40;
            $('#background-wrapper').height(
                $('.amo-header').height() +
                $('#promos').height() + extraHeight
            );
        }
    });
}

$.fn.promoPager = function() {
    $.each(this, function(index, pager) {
        var $dots = $('.dot', pager);
        $dots.click(_pd(function(ev) {
            $('.selected', pager).removeClass('selected');
            setPage(pager, $dots, $dots.index(ev.target));
        }));
    });

    function setPage(pager, dots, pageNum) {
        var offset = -271 * pageNum + 'px';
        dots.eq(pageNum).addClass('selected');
        $(pager).siblings('.pages').css('top', offset);
    }
};

(function() {
    $(document).on('click', '#holiday .addons a', function() {
        dcsMultiTrack('DCS.dcssip', 'addons.mozilla.org',
                      'DCS.dcsuri', location.pathname,
                      'WT.ti', 'Link: ' + $('h3', this).text(),
                      'WT.dl', 99,
                      'WT.z_convert', 'HolidayShopping'
        );
    });
})();
