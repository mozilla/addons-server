var z = {
    body: $(document.body),
    page: $('#container'),
    context: $('#page').data('context'),
    prefix: (function() {
        try {
            var s = window.getComputedStyle(document.body, '');
            return (Array.prototype.slice.call(s).join('').match(/moz|webkit|ms|khtml/)||(s.OLink===''&&['o']))[0];
        } catch (e) {
            return 'moz';
        }
    })(),
    prefixed: function(property) {
        if (!z.prefix) return property;
        return '-' + z.prefix + '-' + property;
    },
    canInstallApps: true,
    allowAnonInstalls: !!$('body').data('allow-anon-installs'),
    // if ($('#myDialog li').length > z.confirmBreakNum) add class 'two-col'.
    confirmBreakNum: 6
};

z.prefixUpper = z.prefix[0].toUpperCase() + z.prefix.substr(1);

(function() {
    _.extend(z, {'nav': BrowserUtils()});
    if (!z.nav.browser.firefox ||
        z.nav.browser.mobile || z.nav.os.maemo ||
        VersionCompare.compareVersions(z.nav.browserVersion, '16.0') < 0 ||
        (z.nav.os.android && VersionCompare.compareVersions(z.nav.browserVersion, '17.0') < 0)) {
        z.canInstallApps = false;
    }
})();

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

    // Set cookie if user is on B2G.
    // TODO: remove this once we allow purchases on desktop/android.
    if (document.cookie && z.capabilities.gaia) {
        document.cookie = 'gaia=true;path=/';
    }

    stick.basic();
});


z.page.on('fragmentloaded', function() {
    var badPlatform = '<div class="bad-platform">' + gettext('This app is unavailable for your platform.') + '</div>';

    z.apps = {};
    if (z.capabilities.webApps) {
        // Get list of installed apps and mark as such.
        r = window.navigator.mozApps.getInstalled();
        r.onsuccess = function() {
            _.each(r.result, function(val) {
                z.apps[val.manifestURL] = val;
                $(window).trigger('app_install_success',
                                  [val, {'manifest_url': val.manifestURL}, false]);
            });
        };
        if (!z.capabilities.gaia) {
            // Only Firefox OS currently supports packaged apps.
            // (The 'bad' class ensures we append the message only once.)
            $('.listing .product[data-is_packaged="true"]').addClass('disabled')
                .closest('.mkt-tile:not(.bad)').addClass('bad').append(badPlatform);
        }
    }

    if (!z.canInstallApps) {
        $(window).trigger('app_install_disabled');
        $('.listing .mkt-tile:not(.bad)').addClass('bad').append(badPlatform);
    }

    // Navigation toggle.
    var $header = $('#site-header'),
        $nav = $header.find('nav ul'),
        $outer = $('html, body');
    $header.on('click', '.menu-button', _pd(function() {
        $nav.addClass('active');
        $('.nav-overlay').addClass('show');
    })).on('click', '.region', _pd(function() {
        $outer.animate({scrollTop: $outer.height()}, 1000);
    }));

    $(window).bind('overlay_dismissed', function() {
       $nav.removeClass('active');
    });

    // Hijack external links if we're on mobile.
    if (z.capabilities.touch) {
        $('a[rel=external]').attr('target', '_blank');
    }

    // Header controls.
    $('header').on('click', '.header-button', function(e) {
        var $this = $(this),
            $btns = $('.header-button');

        if ($this.hasClass('dismiss')) {
            // Dismiss looks like back but actually just dismisses an overlay.
            $('#filters').hide();
        } else if ($this.hasClass('filter')) {
            // Yea...
            var sortoption = z.getVars(location.href);

            $('#filter-sort li a').removeClass('sel');
            switch(sortoption.sort) {
                case 'None':
                    $('#filter-sort li.relevancy a').addClass('sel');
                    break;
                case 'popularity':
                    $('#filter-sort li.popularity a').addClass('sel');
                    break;
                case 'rating':
                    $('#filter-sort li.rating a').addClass('sel');

            }
            $('#filters').show();
        } else if ($this.hasClass('search')) {
            z.body.addClass('show-search');
            $btns.blur();
            $('#search-q').focus();
        } else if ($this.hasClass('cancel')) {
            z.body.removeClass('show-search');
            $('#search-q').blur();
            $btns.blur();
        }

        z.page.on('fragmentloaded', function() {
            z.body.removeClass('show-search');
            $('#search-q').blur();
        });
        e.preventDefault();
    });

    // iPhone-style scroll up.
    z.body.on('click', '#top, header', function(e) {
        var $target = $(e.target);
        if (!$target.filter('a, form, input').length) {
            e.preventDefault();
            $outer.animate({scrollTop: 0}, 500);
        }
    });
});
