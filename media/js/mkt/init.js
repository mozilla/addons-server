var z = {
    page: $('#page'),
    prefix: (function() {
        var s = window.getComputedStyle(document.body,"");
        return (Array.prototype.slice.call(s).join('').match(/moz|webkit|ms|khtml/)||(s.OLink===''&&['o']))[0];
    })(),
    prefixed: function(property) {
        if (!z.prefix) return property;
        return '-' + z.prefix + '-' + property;
    }
};

// Initialize webtrends tracking.
z.page.on('fragmentloaded', webtrendsAsyncInit);

(function() {
    function trigger() {
        $(window).trigger('saferesize');
    }
    window.addEventListener('resize', _.debounce(trigger, 200), false);
})();

$(document).ready(function() {
    // Initialize email links.
    z.page.on('fragmentloaded', function() {
        $('span.emaillink').each(function() {
            var $this = $(this);
            $this.find('.i').remove();
            var em = $this.text().split('').reverse().join('');
            $this.prev('a').attr('href', 'mailto:' + em);
        });
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
                              {'manifestUrl': val.manifestURL})
                     .trigger('app_install_mark',
                              {'manifestUrl': val.manifestURL});
        });
    };

    var $body = $('body');
    // Add class for touch devices.
    $body.addClass(z.capabilities.touch ? 'touch' : 'desktop');
    // Store baseline classes.
    $body.data('class', $body.attr('class'));

    // Navigation toggle.
    var $header = $('#site-header'),
        $nav = $header.find('nav ul');
    $header.on('click', '.menu-button', function() {
        $nav.toggleClass('active');
        $('.nav-overlay').addClass('show');
    });
    $(window).bind('overlay_dismissed', function() {
       $nav.removeClass('active');
    }).bind('app_install_mark', function(e, product) {
        var $li = $(format('.listing li[data-manifest="{0}"]',
                           product.manifestUrl)),
            $actions = $li.find('.actions'),
            $purchased = $actions.find('.checkmark.purchased'),
            installed = format('<span class="checkmark installed">{0}</span>',
                               gettext('Installed'));
        if ($purchased.length) {
            $purchased.replaceWith(installed);
        } else {
            $purchased.prepend(installed);
        }
    });
});
