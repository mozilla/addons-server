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

var vc = new VersionCompare(),
    notavail = '<div class="extra"><span class="notavail">{0}</span></div>';

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
    });

    var addon = $this.attr('data-addon'),
        min = $this.attr('data-min'),
        max = $this.attr('data-max'),
        name = $this.attr('data-name'),
        icon = $this.attr('data-icon'),
        after = $this.attr('data-after'),
        search = $this.hasattr('data-search'),
        accept_eula = $this.hasClass('accept'),
        // L10n: {0} is an app name like Firefox.
        _s = accept_eula ? gettext('Accept and Install') : gettext('Add to {0}'),
        addto = format(_s, [z.appName]),
        // params is used for popup variable interpolation.
        // The `url` key is set after we've messed with the buttons.
        params = {addon: addon,
                  msg: z.appMatchesUserAgent ? addto : gettext('Download Now')},
        appSupported = z.appMatchesUserAgent && min && max,
        olderBrowser = null,
        newerBrowser = null;

    // If we have os-specific buttons, check that one of them matches the
    // current platform.
    var badPlatform = ($button.find('.os').length &&
                       !$button.hasClass(z.platform));

    // min and max only exist if the add-on is compatible with request[APP].
    if (appSupported) {
        // The user *has* an older/newer browser.
        olderBrowser = vc.compareVersions(z.browserVersion, min) < 0;
        newerBrowser = vc.compareVersions(z.browserVersion, max) > 0;
    }

    // Helper for dealing with lazy-loaded z.button.messages.
    var message = function(msg) {
        return function(){
            // Get the xpi link for the first visible button.
            params.url = $button.filter(':visible').attr('href');
            return format(z.button.messages[msg], params);
        }
    };

    var addWarning = function(msg) { $this.parent().append(format(notavail, [msg])); };

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
        if (!appSupported && !search) return;

        $this.click(function(e) {
            // If the click was on a.installer or a child, call the special
            // install method.  We can't bind this directly because we add
            // more .installers dynamically.
            var $target = $(e.target);
            if ($target.hasClass('installer')) {
                var installer = $target;
            } else {
                var installer =  $target.parents('.installer').first();
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

            var f = _.haskey(z.button.after, after)
                    ? z.button.after[after] : _.identity,
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
                return format(z.button.messages['platform_link'], o);
            });
            return format(z.button.messages['bad_platform'],
                          {platforms: links.join('')});
        });
        var vmsg = addExtra(function() {
            params['new_version'] = max;
            params['old_version'] = z.browserVersion;
            return message(newerBrowser ? 'not_updated' : 'newer_version')();
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
        }

        if (appSupported && (olderBrowser || newerBrowser)) {
            // L10n: {0} is an app name, {1} is the app version.
            warn(format(gettext('Not available for {0} {1}'),
                              [z.appName, z.browserVersion]));
            $button.addClass('concealed');
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
        } else if (badPlatform && opts.addPopup) {
            // Only bad platform is possible.
            $button.addPopup(pmsg);
            return true;
        } else if (!unreviewed && (appSupported || search)) {
            // Good version, good platform.
            $button.addClass('installer');
        }
        return false;
    };

    // What kind of button are we dealing with?
    var selfhosted = $this.hasClass('selfhosted'),
        beta = $this.hasClass('beta');
        unreviewed = $this.hasClass('unreviewed') && !beta,
        persona = $this.hasClass('persona'),
        contrib = $this.hasClass('contrib'),
        search = $this.hasattr('data-search'),
        eula = $this.hasClass('eula');

    if (unreviewed && !(selfhosted || eula || contrib || beta)) {
        $button.addPopup(message('unreviewed'));
    }

    // Drive the install button based on its type.
    if (selfhosted) {
        $button.addPopup(message('selfhosted'));
    } else if (eula || contrib) {
        versionsAndPlatforms({addPopup: false})
    } else if (persona) {
        $button.removeClass('download').addClass('add').find('span').text(addto);
        if ($.hasPersonas()) {
            $button.personasButton();
        } else {
            $button.addClass('concealed');
            if (z.appMatchesUserAgent) {
                // Need upgrade
                params['old_version'] = z.browserVersion;
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
        $button.addPopup(message('learn_more')).addClass('concealed');
        versionsAndPlatforms({addPopup: false});
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
            $this.bind('newPopup', function(e, popup) {
                $this.unbind('newPopup');
                $(popup).find('.installer').click(function(e) {
                    $this.unbind('click');  // Drop the current popup.
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

                // Callback to destroy the popup on the first click outside the popup.
                var cb = function(e) {
                    // Bail if the click was somewhere on the popup.
                    if (e.type == 'click' &&
                        popup_root == e.target ||
                        _.indexOf($(e.target).parents(), popup_root) != -1) {
                        return;
                    }
                    _html.remove();
                    $body.unbind('click newPopup', cb);
                }
                // Trampoline the binding so it isn't triggered by the current click.
                setTimeout(function(){ $body.bind('click newPopup', cb); }, 0);
            });
        }
    });
}


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
        params[name]['Hash'] = hash;
    }
    // InstallTrigger is a Gecko API.
    InstallTrigger.install(params, callback);
};


z.installSearch = function(name, url, icon, hash, callback) {
    if (window.external && window.external.AddSearchProvider) {
        window.external.AddSearchProvider(url);
        callback();
    } else {
        // Alert!  Deal with it.
        alert(gettext('Sorry, you need a Mozilla-based browser (such as Firefox) to install a search plugin.'));
    }
};
})();
