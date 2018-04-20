(function() {

/* Call this with something like $('.install').installButton(); */
z.button = {};

/* A library of callbacks that may be run after InstallTrigger succeeds.
 * ``this`` will be bound to the .install button.
 */
z.button.after = {'contrib': function(xpi_url, status) {
    if (status === 0) { //success
        document.location = $(this).attr('data-developers');
    }
}};

var notavail = '<div class="extra"><span class="button disabled not-available" disabled>{0}</span></div>',
    incompat = '<div class="extra"><span class="button disabled not-available" disabled>{0}</span></div>',
    noappsupport = '<div class="extra"><span class="button disabled not-available" disabled>{0}</span></div>',
    download_re = new RegExp('(/downloads/(?:latest|file)/\\d+)');

// The lowest maxVersion an app has to support to allow default-to-compatible.
var D2C_MAX_VERSIONS = {
    firefox: '4.0',
    mobile: '11.0',
    seamonkey: '2.1',
    thunderbird: '5.0'
};

/* Called by the jQuery plugin to set up a single button. */
var installButton = function() {
    // Create a bunch of data and helper functions, then drive the buttons
    // based on the button type at the end.
    var self = this,
        $this = $(this),
        $button = $this.find('.button');

    // Unreviewed and self-hosted buttons point to the add-on detail page for
    // non-js safety.  Flip them to the real xpi url here.
    $button.each(function() {
        var $this = $(this);
        if ($this.hasattr('data-realurl')) {
            $this.attr('href', $this.attr('data-realurl'));
        }

        /* If we're on the mobile site but it's not a mobile browser, force
         * the download url to type:attachment.
         */
        if (z.app === 'mobile' && !z.appMatchesUserAgent) {
            var href = $this.attr('href');
            $this.attr('href', href.replace(download_re, '$1/type:attachment'));
        }
    });

    var addon = $this.attr('data-addon'),
        min = $this.attr('data-min'),
        max = $this.attr('data-max'),
        name = $this.attr('data-name'),
        icon = $this.attr('data-icon'),
        after = $this.attr('data-after'),
        search = $this.hasattr('data-search'),
        no_compat_necessary = $this.hasattr('data-no-compat-necessary'),
        accept_eula = $this.hasClass('accept'),
        compatible = $this.attr('data-is-compatible-by-default') == 'true',
        compatible_app = $this.attr('data-is-compatible-app') == 'true',
        has_overrides = $this.hasattr('data-compat-overrides'),
        versions_url = $this.attr('data-versions'),
        // L10n: {0} is an app name like Firefox.
        _s = accept_eula ? gettext('Accept and Install') : gettext('Add to {0}'),
        addto = format(_s, [z.appName]),
        appSupported = z.appMatchesUserAgent && min && max,
        $body = $(document.body),
        olderBrowser,
        newerBrowser;

    // If we have os-specific buttons, check that one of them matches the
    // current platform.
    var badPlatform = ($button.find('.os').length &&
                       !$button.hasClass(z.platform));

    // min and max only exist if the add-on is compatible with request[APP].
    if (appSupported) {
        // The user *has* an older/newer browser.
        olderBrowser = VersionCompare.compareVersions(z.browserVersion, min) < 0;
        newerBrowser = VersionCompare.compareVersions(z.browserVersion, max) > 0;
        if (olderBrowser) {
            // Make sure we show the "Not available for ..." messaging.
            compatible = false;
        }
    }

    // Default to compatible checking.
    if (compatible) {
        if (!compatible_app) {
            compatible = false;
        }
        // If it's still compatible, check the overrides.
        if (compatible && has_overrides) {
            var overrides = JSON.parse($this.attr('data-compat-overrides'));
            _.each(overrides, function(override) {
                var _min = override[0],
                    _max = override[1];
                if (VersionCompare.compareVersions(z.browserVersion, _min) >= 0 &&
                    VersionCompare.compareVersions(z.browserVersion, _max) <= 0) {
                    compatible = false;
                    return;
                }
            });
        }
    } else {
        compatible = false;
    }

    var addWarning = function(msg, type) {
        $this.parent().append(format(type || notavail, [msg]));
    };

    // Change the button text to "Add to Firefox".
    var addToApp = function() {
        if (appSupported || (no_compat_necessary && z.appMatchesUserAgent)) {
            $button.addClass('add').removeClass('download')
                .find('span').text(addto);
        }
    };

    // Calls InstallTrigger.install or AddSearchProvider if we capture a click
    // on something with a .installer class.
    var clickHijack = function() {
        try {
            if (!appSupported && !no_compat_necessary || !("InstallTrigger" in window)) return;
        } catch (e) {
            return;
        }

        $this.addClass('clickHijack'); // So we can disable pointer events

        $this.on('mousedown focus', function(e) {
            $this.addClass('active');
        }).on('mouseup blur', function(e) {
            $this.removeClass('active');
        }).click(function(e) {
            // If the click was on a.installer or a child, call the special
            // install method.  We can't bind this directly because we add
            // more .installers dynamically.
            var $target = $(e.target),
                $installer = '';
            if ($target.hasClass('installer')) {
                installer = $target;
            } else {
                installer =  $target.parents('.installer').first();
                if (_.indexOf($this.find('.installer'), installer[0]) == -1) {
                    return;
                }
            }
            e.preventDefault();

            // map download url => file hash.
            var hashes = {};
            $this.find('.button[data-hash]').each(function() {
                hashes[$(this).attr('href')] = $(this).attr('data-hash');
            });
            var hash = hashes[installer.attr('href')];

            var f = _.haskey(z.button.after, after) ? z.button.after[after] : _.identity,
                callback = _.bind(f, self),
                install = search ? z.installSearch : z.installAddon;
            install(name, installer[0].href, icon, hash, callback);
        });
    };

    // Gather the available platforms.
    var platforms = $button.map(function() {
        var name = $(this).find('.os').attr('data-os'),
            text = z.appMatchesUserAgent ?
                /* L10n: {0} is an platform like Windows or Linux. */
                gettext('Install for {0} anyway') : gettext('Download for {0} anyway');
        return  {
            href: $(this).attr('href'),
            msg: format(text, [name])
        };
    });

    var showDownloadAnyway = function($button) {
        var $visibleButton = $button.filter(':visible')
        var $installShell = $visibleButton.parents('.install-shell');
        var $downloadAnyway = $visibleButton.next('.download-anyway');
        if ($downloadAnyway.length) {
            // We want to be able to add the download anyway link regardless
            // of what is already shown. There could be just an error message,
            // or an error message plus a link to more versions. We also want
            // those combinations to work without the download anyway link
            // being shown.
            // Append a separator to the .more-versions element:
            // if it's displayed we need to separate the download anyway link
            // from the text shown in that span.
            var $moreVersions = $installShell.find('.more-versions');
            $moreVersions.append(' | ');
            // In any case, add the download anyway link to the parent div.
            // It'll show up regardless of whether we are showing the more
            // versions link or not.
            var $newParent = $installShell.find('.extra .not-available');
            $newParent.append($downloadAnyway);
            $downloadAnyway.show();
        }
    }

    // Add version and platform warnings.  This is one
    // big function since we merge the messaging when bad platform and version
    // occur simultaneously.
    var versionsAndPlatforms = function(options) {
        var opts = $.extend({addWarning: true}, options);
            warn = opts.addWarning ? addWarning : _.identity;

        // Do badPlatform prep out here since we need it in all branches.
        if (badPlatform) {
            warn(gettext('Not available for your platform'));
            $button.addClass('concealed');
            $button.first().css('display', 'inherit');
            $button.closest('.item.addon').addClass('incompatible');
        }

        if (appSupported && !compatible && (olderBrowser || newerBrowser)) {
            // L10n: {0} is an app name.
            var msg = format(gettext('This add-on is not compatible with your version of {0}.'),
                        [z.appName, z.browserVersion]);
            var tpl = template(msg +
                ' <br/><span class="more-versions"><a href="{versions_url}">' +
                gettext('View other versions') + '</a></span>');
            warn(tpl({'versions_url': versions_url}));

            $button.closest('div').attr('data-version-supported', false);
            $button.addClass('concealed');
            $button.closest('.item.addon').addClass('incompatible');
            if (!badPlatform) {
                showDownloadAnyway($button);
            }

            return true;
        } else if (!unreviewed && (appSupported || no_compat_necessary)) {
            // Good version, good platform.
            $button.addClass('installer');
            $button.closest('div').attr('data-version-supported', true);
        } else if (!appSupported) {
            var msg = (min && max ?
              gettext('Works with {app} {min} - {max}') :
              gettext('Works with {app}'));
            var tpl = template(msg +
                '<br/><span class="more-versions"><a href="{versions_url}">' +
                gettext('View other versions') + '</a></span>');
            var context = {'app': z.appName, 'min': min, 'max': max,
                'versions_url': versions_url};
            addWarning(tpl(context), noappsupport);
            if (!badPlatform) {
                showDownloadAnyway($button);
            }
        }
        return false;
    };

    // What kind of button are we dealing with?
    var unreviewed = $this.hasClass('unreviewed'),
        persona = $this.hasClass('persona'),
        contrib = $this.hasClass('contrib'),
        eula = $this.hasClass('eula');

    // Drive the install button based on its type.
    if (eula || contrib) {
        versionsAndPlatforms();
    } else if (persona && $.hasPersonas()) {
        $button.removeClass('download').addClass('add').find('span').text(addto);
        $button.personasButton();
    } else if (z.appMatchesUserAgent) {
        clickHijack();
        addToApp();
        var opts = no_compat_necessary ? {addWarning: false} : {};
        versionsAndPlatforms(opts);
    } else if (z.app == 'firefox') {
        $button.addClass('CTA');
        $button.text(gettext('Only with Firefox \u2014 Get Firefox Now!'));
        $button.attr('href', 'https://www.mozilla.org/firefox/new/?scene=2&utm_source=addons.mozilla.org&utm_medium=referral&utm_campaign=non-fx-button#download-fx');
        $('#site-nonfx').hide();
    } else if (z.app == 'thunderbird') {
        versionsAndPlatforms();
    } else {
        clickHijack();
        addToApp();
        versionsAndPlatforms();
    }
};

jQuery.fn.installButton = function() {
    return this.each(installButton);
};

/* Install an XPI or a JAR (or something like that).
 *
 * hash and callback are optional.  callback is triggered after the
 * installation is complete.
 */
z.installAddon = function(name, url, icon, hash, callback) {
    var params = {};
    params[name] = {
        URL: url,
        IconURL: icon,
        toString: function() { return url; }
    };
    if (hash) {
        params[name].Hash = hash;
    }
    // InstallTrigger is a Gecko API.
    InstallTrigger.install(params, callback);
    _gaq.push(['_trackEvent', 'AMO Addon / Theme Installs', 'addon', name]);
};


z.installSearch = function(name, url, icon, hash, callback) {
    if (window.external && window.external.AddSearchProvider) {
        window.external.AddSearchProvider(url);
        callback();
        _gaq.push(['_trackEvent', 'AMO Addon / Theme Installs', 'addon', name]);
    } else {
        // Alert!  Deal with it.
        alert(gettext('Sorry, you need a Mozilla-based browser (such as Firefox) to install a search plugin.'));
    }
};
})();
