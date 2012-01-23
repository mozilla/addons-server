function initPromos($context, version, platform, context) {
    if (typeof $context === 'undefined') {
        $context = $(document.body);
    }
    var $promos = $('#promos[data-promo-url]', $context);
    if (!$promos.length) {
        return;
    }
    var promos_base = $promos.attr('data-promo-url');
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
    var data = {version: version, platform: platform};
    if (context) {
        data['context'] = context;
    }
    $.get(promos_base, data, function(resp) {
        $('.slider', $promos).append($(resp));
        if ($('.panel', $promos).length) {
            // Show promo module only if we have at least panel.
            $promos.trigger('promos_shown', [$promos]);
        }
    });
}
