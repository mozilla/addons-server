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

var notavail = '<div class="extra"><span class="notavail">{0}</span></div>',
    incompat = '<div class="extra"><span class="notavail acr-incompat">{0}</span></div>',
    noappsupport = '<div class="extra"><span class="notsupported">{0}</span></div>',
    download_re = new RegExp('(/downloads/(?:latest|file)/\\d+)');

// Restyle is enabled; we're going to modify the text.
if ($('body').hasClass('restyle')) {
    notavail = '<div class="extra"><span class="button disabled not-available" disabled>{0}</span></div>';
    incompat = '<div class="extra"><span class="button disabled not-available" disabled>{0}</span></div>';
    noappsupport = '<div class="extra"><span class="button disabled not-available" disabled>{0}</span></div>';
}

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
        accept_eula = $this.hasClass('accept'),
        compatible = $this.attr('data-is-compatible') == 'true',
        compatible_app = $this.attr('data-is-compatible-app') == 'true',
        has_overrides = $this.hasattr('data-compat-overrides'),
        versions_url = $this.attr('data-versions'),
        // L10n: {0} is an app name like Firefox.
        _s = accept_eula ? gettext('Accept and Install') : gettext('Add to {0}'),
        addto = format(_s, [z.appName]),
        // params is used for popup variable interpolation.
        // The `url` key is set after we've messed with the buttons.
        params = {addon: addon,
                  msg: z.appMatchesUserAgent ? addto : gettext('Download Now')},
        appSupported = z.appMatchesUserAgent && min && max,
        $body = $(document.body),
        $d2c_reasons = $this.closest('.install-shell').find('.d2c-reasons-popup ul'),
        olderBrowser,
        newerBrowser;

    // If we have os-specific buttons, check that one of them matches the
    // current platform.
    var badPlatform = ($button.find('.os').length &&
                       !$button.hasClass(z.platform));

    // Only show default-to-compatible reasons if the add-on has the minimum
    // required maxVersion to support it.
    var is_d2c = false;
    if (max) {
        if (z.browser.firefox && VersionCompare.compareVersions(max, D2C_MAX_VERSIONS.firefox) >= 0) {
            is_d2c = true;
        } else if (!z.browser.firefox && VersionCompare.compareVersions(max, D2C_MAX_VERSIONS.mobile) >= 0) {
            is_d2c = true;
        } else if (z.browser.mobile && VersionCompare.compareVersions(max, D2C_MAX_VERSIONS.mobile) >= 0) {
            is_d2c = true;
        } else if (z.browser.seamonkey && VersionCompare.compareVersions(max, D2C_MAX_VERSIONS.seamonkey) >= 0) {
            is_d2c = true;
        } else if (z.browser.thunderbird && VersionCompare.compareVersions(max, D2C_MAX_VERSIONS.thunderbird) >= 0) {
            is_d2c = true;
        }
    }

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
    if (is_d2c && compatible) {
        if (!compatible_app) {
            $d2c_reasons.append($('<li>', {text: gettext('Add-on has not been updated to support default-to-compatible.')}));
            compatible = false;
        }
        // TODO: Figure out if this needs to handle other apps.
        if (z.browserVersion !== 0 && VersionCompare.compareVersions(z.browserVersion, '10.0') < 0) {
            $d2c_reasons.append($('<li>', {text: gettext('You need to be using Firefox 10.0 or higher.')}));
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
                    $d2c_reasons.append($('<li>', {text: gettext('Mozilla has marked this version as incompatible with your Firefox version.')}));
                    return;
                }
            });
        }
    } else {
        compatible = false;  // We always assumed not compatible before.
    }

    // Helper for dealing with lazy-loaded z.button.messages.
    var message = function(msg) {
        return function(){
            // Get the xpi link for the first visible button.
            params.url = escape_($button.filter(':visible').attr('href'));
            return format(z.button.messages[msg], params);
        };
    };

    var addWarning = function(msg, type) {
        $this.parent().append(format(type || notavail, [msg]));
    };

    // Change the button text to "Add to Firefox".
    var addToApp = function() {
        if (appSupported || (search && z.appMatchesUserAgent)) {
            $button.addClass('add').removeClass('download')
                .find('span').text(addto);
        }
    };

    // Calls InstallTrigger.install or AddSearchProvider if we capture a click
    // on something with a .installer class.
    var clickHijack = function() {
        try {
            if (!appSupported && !search || !("InstallTrigger" in window)) return;
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

    // Add version and platform warnings and (optionally) popups.  This is one
    // big function since we merge the messaging when bad platform and version
    // occur simultaneously.  Returns true if a popup was added.
    var versionsAndPlatforms = function(options) {
        var opts = $.extend({addPopup: true, addWarning: true, extra: ''},
                            options);
            warn = opts.addWarning ? addWarning : _.identity;

        var addExtra = function(f) {
            /* Decorator to add extra content to a message. */
            return function() {
                var extra = $.isFunction(opts.extra) ? opts.extra()
                                : opts.extra;
                return $(f.apply(this, arguments)).append(extra);
            };
        };

        // Popup message helpers.
        var pmsg = addExtra(function() {
            var links = $.map(platforms, function(o) {
                return format(z.button.messages.platform_link, o);
            });
            return format(z.button.messages.bad_platform,
                          {platforms: links.join('')});
        });
        var vmsg = addExtra(function() {
            params.new_version = max;
            params.old_version = z.browserVersion;
            return message(newerBrowser ? 'not_updated' : 'newer_version')();
        });
        var nocompat = addExtra(function() {
            return message('not_compatible')();
        });
        var nocompat_noreason = addExtra(function() {
            return message('not_compatible_no_reasons')();
        });
        var merge = addExtra(function() {
            // Prepend the platform message to the version message.  We only
            // want to move the installer when we're looking at an older
            // version of the add-on.
            var p = $(pmsg()), v = $(vmsg());
            v.prepend(p.find('.msg').clone());
            if (this.switchInstaller) {
                v.find('.installer').parent().html(p.find('ul').clone());
            }
            return v;
        });

        // Do badPlatform prep out here since we need it in all branches.
        if (badPlatform) {
            warn(gettext('Not available for your platform'));
            $button.addClass('concealed');
            $button.first().css('display', 'inherit');
            $button.closest('.item.addon').addClass('incompatible');
        }

        if (appSupported && !compatible && (olderBrowser || newerBrowser)) {
            if (is_d2c) {
                // If it's a bad platform, don't bother also showing the
                // incompatible reasons.
                if (!badPlatform) {
                    // L10n: {0} is an app name, {1} is the app version.
                    var warn_txt = gettext('Not available for {0} {1}');
                    if ($d2c_reasons.children().length) {
                        warn_txt += '<span><a class="d2c-reasons-help" href="#">?</a></span>';
                    }
                    warn(format(warn_txt, [z.appName, z.browserVersion]));
                }
                $button.closest('div').attr('data-version-supported', false);
                $button.addClass('concealed');
                $button.closest('.item.addon').addClass('incompatible');

                var $ishell = $button.closest('.install-shell');
                if (!compatible && $d2c_reasons.children().length) {
                    $ishell.find('.d2c-reasons-popup').popup(
                        $ishell.find('.d2c-reasons-help'), {
                            callback: function(obj) {
                                return {pointTo: $(obj.click_target)};
                            }
                        }
                    );
                }

                if (!opts.addPopup) return;

                if (badPlatform) {
                    $button.addPopup(pmsg);
                } else if (!compatible) {
                    // Show compatibility message.
                    params.versions_url = versions_url;
                    params.reasons = $d2c_reasons.html();

                    $button.addPopup(params.reasons ? nocompat : nocompat_noreason);
                } else {
                    // Bad version.
                    $button.addPopup(vmsg);
                }
                return true;
            } else {
                // L10n: {0} is an app name, {1} is the app version.
                warn(format(gettext('Not available for {0} {1}'),
                            [z.appName, z.browserVersion]));
                $button.closest('div').attr('data-version-supported', false);
                $button.addClass('concealed');
                $button.closest('.item.addon').addClass('incompatible');
                if (!opts.addPopup) return;

                if (badPlatform && olderBrowser) {
                    $button.addPopup(merge);
                } else if (badPlatform && newerBrowser) {
                    $button.addPopup(_.bind(merge, {switchInstaller: true}));
                } else {
                    // Bad version.
                    $button.addPopup(vmsg);
                }
                return true;
            }
        } else if (badPlatform && opts.addPopup) {
            // Only bad platform is possible.
            $button.addPopup(pmsg);
            $button.closest('div').attr('data-version-supported', true);
            return true;
        } else if (!unreviewed && (appSupported || search)) {
            // Good version, good platform.
            $button.addClass('installer');
            $button.closest('div').attr('data-version-supported', true);
        } else if (!appSupported) {
            var msg = (min && max ?
              gettext('Works with {app} {min} - {max}') :
              gettext('Works with {app}'));
            var tpl = template(msg +
                '<span class="more-versions"><a href="{versions_url}">' +
                gettext('View other versions') + '</a></span>');
            var context = {'app': z.appName, 'min': min, 'max': max,
                'versions_url': versions_url};
            addWarning(tpl(context), noappsupport);
        }
        return false;
    };

    // What kind of button are we dealing with?
    var beta = $this.hasClass('beta'),
        unreviewed = $this.hasClass('unreviewed') && !beta,
        persona = $this.hasClass('persona'),
        contrib = $this.hasClass('contrib'),
        eula = $this.hasClass('eula');

    if (unreviewed && !(eula || contrib || beta)) {
        $button.addPopup(message('unreviewed'));
    }


    // Drive the install button based on its type.
    if (eula || contrib) {
        versionsAndPlatforms({addPopup: false});
    } else if (persona) {
        $button.removeClass('download').addClass('add').find('span').text(addto);
        if ($.hasPersonas()) {
            $button.personasButton();
        } else {
            $button.addClass('concealed');
            if (z.appMatchesUserAgent) {
                // Need upgrade
                params.old_version = z.browserVersion;
                $button.addPopup(message('personas_need_upgrade'));
            } else {
                $button.addPopup(message('learn_more_personas'));
            }
        }
    } else if (z.appMatchesUserAgent) {
        clickHijack();
        addToApp();
        var opts = search ? {addPopup: false, addWarning: false} : {};
        versionsAndPlatforms(opts);
    } else if (z.app == 'firefox') {
        $('#downloadAnyway').attr('href',escape_($button.filter(':visible').attr('href')));
        $('#downloadAnyway').show();
        $button.addClass('concealed');
        versionsAndPlatforms({addPopup: false});
        $button.addClass('CTA');
        $button.text(gettext('Only with Firefox \u2014 Get Firefox Now!'));
        $button.attr('href', 'https://www.mozilla.org/firefox/new/?scene=2&utm_source=addons.mozilla.org&utm_medium=referral&utm_campaign=non-fx-button#download-fx');
        $('#site-nonfx').hide();
    } else if (z.app == 'android' && !is_d2c) {
        $('#downloadAnyway').attr('href',escape_($button.filter(':visible').attr('href')));
        $('#downloadAnyway').show();
        $button.addClass('button-red');
        $button.text(gettext('Download now'));
        $('.extra').hide();
        addWarning(gettext('Only available on Firefox Desktop'));
    } else if (z.app == 'thunderbird') {
        var msg = function() {
            return $(message('learn_more')()).html();
        };
        if (!versionsAndPlatforms({extra: msg})) {
            $button.addPopup(message('learn_more'), true);
        }
    } else {
        clickHijack();
        addToApp();
        versionsAndPlatforms();
    }
};


var data_purchases = $('body').attr('data-purchases') || "",
    addons_purchased = $.map(data_purchases.split(','),
                             function(v) { return parseInt(v, 10); });

jQuery.fn.installButton = function() {
    return this.each(installButton);
};

// Create a popup box when the element is clicked.  html can be a function.
jQuery.fn.addPopup = function(html, allowClick) {
    return this.each(function() {
        var $this = $(this),
            self = this,
            $body = $(document.body);

        if (this.hasPopup) {
            // We've been here before, queue a follow-up button.
            $this.on('newPopup', function(e, popup) {
                $this.off('newPopup');
                $(popup).find('.installer').click(function(e) {
                    $this.off('click');  // Drop the current popup.
                    self.hasPopup = false;
                    var next = self.popupQueue.pop();
                    if (!next[1]) { // allowClick
                        e.preventDefault();
                        e.stopPropagation();
                    }
                    jQuery.fn.addPopup.apply($this, next);
                    $this.click();
                });
            });
            self.popupQueue = self.popupQueue || [];
            self.popupQueue.push([html, allowClick]);
        } else {
            this.hasPopup = true;

            $this.click(function(e) {
                var _html = $($.isFunction(html) ? html() : html),
                    popup_root = _html.get(0);

                if (!$this.filter(':visible').length) { return; }
                if (!allowClick) { e.preventDefault(); }

                if ($this.offset().left > $(window).width() / 2) {
                    _html.addClass('left');
                }
                $this.trigger('newPopup', [_html]);
                $this.after(_html);
                $body.trigger('newStatic');

                // Callback to destroy the popup on the first click outside the popup.
                var cb = function(e) {
                    // Bail if the click was somewhere on the popup.
                    if (e.type == 'click' &&
                        popup_root == e.target ||
                        _.indexOf($(e.target).parents(), popup_root) != -1) {
                        return;
                    }
                    _html.remove();
                    $body.off('click newPopup', cb);
                    $body.trigger('closeStatic');
                };
                // Trampoline the binding so it isn't triggered by the current click.
                setTimeout(function(){ $body.on('click newPopup', cb); }, 0);
            });
        }
    });
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
