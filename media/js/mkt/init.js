var z = {
    page: $('#page'),
};


$(document).ready(function() {
    // Initialize email links.
    $('span.emaillink').each(function() {
        var $this = $(this);
        $this.find('.i').remove();
        var em = $this.text().split('').reverse().join('');
        $this.prev('a').attr('href', 'mailto:' + em);
    });
    if (z.readonly) {
        $('form[method=post]')
            .before(gettext('This feature is temporarily disabled while we ' +
                            'perform website maintenance. Please check back ' +
                            'a little later.'))
            .find('button, input, select, textarea').attr('disabled', true)
            .addClass('disabled');
    }
    var data_user = $('body').data('user');
    _.extend(z, {
        anonymous: data_user.anonymous,
        pre_auth: data_user.pre_auth
    });
});


$(function() {
    // Get list of installed apps and mark as such.
    r = window.navigator.mozApps.getInstalled();
    r.onsuccess = function() {
        _.each(r.result, function(val) {
            $(window).trigger('app_install_success',
                             {'manifestUrl': val.manifestURL});
        });
    };

    // Add class for touch devices.
    $('body').addClass(z.capabilities.touch ? 'touch' : 'desktop');
});
