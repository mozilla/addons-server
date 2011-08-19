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

    var messages = {
        'tooNew': format(gettext("Not Updated for {0} {1}"), z.appName, z.browserVersion),
        'tooOld': format(gettext("Requires Newer Version of {0}"), z.appName),
        'unreviewed': gettext("Unreviewed"),
        'lite': gettext("Experimental <span>(Learn More)</span>"),
        'badApp': format(gettext("Not Available for {0}"), z.appName),
        'badPlatform': format(gettext("Not Available for {0}"), z.platformName),
        'experimental': gettext("Experimental"),
        'personasTooOld': format(gettext("Personas Require Newer Version of {0}"), z.appName),
        'personasLearnMore': format(gettext("Personas Require {0}"), z.appName)
    };

    function Button(el) {
        // the actionQueue holds all the various events that have to happen
        // when the user clicks the button. This includes the terminal action,
        // such as "install", "purchase", or "add to mobile".
        // actions are a tuple of the form [n, cb], where cb is a method that
        // is called when the action is executed, and n is the priority of the
        // action. The queue is sorted before execution. the callback is
        // executed in the function's scope. To resume, call this.nextAction()
        // after a user or other blocking action, or return true to
        // immediately execute the next action.
        this.actionQueue = [];

        var self = this,
            attr, classes,
            hashes = {},
            errors = [],
            warnings = [],
            activeInstaller,
            currentAction=0,
            //setup references to DOM UI.
            dom = {
                'self'      : $(el),
                'badges'    : $(el).find(".badges"),
                //Can be multiple buttons in the case of platformers
                'buttons'   : $('.button', el),
                'labels'    : $('.button span', el)
            };

        // the initializer is called once when the button is created.
        this.init = function() {
            initFromDom();
            collectHashes();

            if (self.classes.webapp) {
                initWebapp();
            }

            versionPlatformCheck();

            this.actionQueue.push([0, function() {
                if (self.classes.persona) {
                    return;
                }
                var href = activeInstaller.attr('href'),
                    hash = hashes[href],
                    attr = self.attr,
                    install = attr.search ? z.installSearch : z.installAddon;
                install(attr.name, href, attr.icon, hash);
                return true;
            }]);

            for (var i=0; i<errors.length; i++) {
                dom.badges.append(format("<li class='error'>{0}</li>", messages[errors[i]]));
            }
            var badgeEl;
            for (i=0; i<warnings.length; i++) {
                badgeEl = $(format("<li class='warning'>{0}</li>", messages[warnings[i]]));
                dom.badges.append(badgeEl);
                if (warnings[i] == "lite") {
                    dom.badges.append("<p class='lite-msg'>"+gettext("This add-on has been preliminarily reviewed by Mozilla.")+"</p>");
                    badgeEl.click(function() {
                        dom.self.find('.lite-msg').toggle();
                    });
                }
            }

            // sort the actionQueue by priority
            this.actionQueue.sort(function (a, b) {return b[0]-a[0];});
        };

        function collectHashes() {
            dom.self.find('.button[data-hash]').each(function() {
                hashes[$(this).attr('href')] = $(this).attr('data-hash');
            });
        }

        function startInstall(e) {
            e.preventDefault();
            self.currentAction=0;
            activeInstaller = $(this);
            nextAction();
        }

        // performs the next action in the queue.
        function nextAction() {
            if (self.currentAction >= self.actionQueue.length) return;
            // execute the next action.
            var result = self.actionQueue[self.currentAction][1].call(this);
            self.currentAction++;
            // execute the next action if the current action returns true.
            if (result === true) {
                self.resumeInstall();
            }
        }
        this.resumeInstall = function() {
            // moving on.
            nextAction();
        };

        //collects all the classes and parameters from the DOM elements.
        function initFromDom() {
            var b = dom.self;

            self.attr = {
                'addon'       : b.attr('data-addon'),
                'min'         : b.attr('data-min'),
                'max'         : b.attr('data-max'),
                'name'        : b.attr('data-name'),
                'icon'        : b.attr('data-icon'),
                'after'       : b.attr('data-after'),
                'search'      : b.hasattr('data-search'),
                'accept_eula' : b.hasClass('accept'),
                'manifest_url': b.attr('data-manifest-url')
            };

            self.classes = {
                'selfhosted'  : b.hasClass('selfhosted'),
                'beta'        : b.hasClass('beta'),
                'lite'        : b.hasClass('lite'),
                'unreviewed'  : b.hasClass('unreviewed'), // && !beta,
                'persona'     : b.hasClass('persona'),
                'contrib'     : b.hasClass('contrib'),
                'search'      : b.hasattr('data-search'),
                'eula'        : b.hasClass('eula'),
                'webapp'      : b.hasClass('webapp')
            };

            dom.buttons.each(function() {
                var $this = $(this);
                if ($this.hasattr('data-realurl')) {
                    $this.attr('href', $this.attr('data-realurl'));
                }
            });

        }

        // Add version and platform warnings and (optionally) popups.  This is one
        // big function since we merge the messaging when bad platform and version
        // occur simultaneously.  Returns true if a popup was added.
        function versionPlatformCheck(options) {
            var b = dom.self,
                attr = self.attr,
                classes = self.classes,
                platformer = !!b.find('.platform').length,
                platformSupported = !platformer || dom.buttons.filter("." + z.platform).length,
                appSupported = z.appMatchesUserAgent && attr.min && attr.max,
                canInstall = true;
            if (!attr.search) {
                // min and max only exist if the add-on is compatible with request[APP].
                if (appSupported && platformSupported) {
                    // The user *has* an older/newer browser.
                    self.tooOld = VersionCompare.compareVersions(z.browserVersion, attr.min) < 0;
                    self.tooNew = VersionCompare.compareVersions(z.browserVersion, attr.max) > 0;
                    if (self.tooOld || self.tooNew) {
                        canInstall = false;
                    }
                    if (self.tooOld) errors.push("tooOld");
                    if (self.tooNew) errors.push("tooNew");
                } else {
                    if (!z.appMatchesUserAgent && !z.badBrowser) {
                        errors.push("badApp");
                        canInstall = false;
                    }
                    if (!platformSupported) {
                        errors.push("badPlatform");
                        dom.buttons.hide().eq(0).show();
                        canInstall = false;
                    }
                }

                if (platformer) {
                    dom.self.find(format(".platform:not(.{0})", z.platform)).hide();
                }

                if (classes.beta) warnings.push("experimental");
                if (classes.unreviewed && !classes.beta) warnings.push("unreviewed");
                if (classes.lite && !classes.beta) warnings.push("lite");

                if (classes.beta || classes.unreviewed || classes.lite) {
                    dom.buttons.addClass("warning");
                }

                if (classes.eula) {
                    self.actionQueue.push([1,z.eula.show]);
                    z.eula.acceptButton.click(_pd(self.resumeInstall));
                }

                if (classes.persona) {
                    dom.buttons.removeClass("download").addClass("add");
                    var persona = new MobilePersona(b);
                    if ($.hasPersonas()) {
                        dom.buttons.text(gettext("Keep it"));
                        dom.buttons.personasButton("click",
                            persona.states().installed);
                    } else {
                        persona.buttons().disable();
                        dom.buttons.addClass("disabled");
                        if (z.appMatchesUserAgent) {
                            // Need upgrade.
                            errors.push("personasTooOld");
                        } else {
                            errors.push("personasLearnMore");
                        }
                    }
                }
            }

            if (z.badBrowser) {
                canInstall = false;
            }

            if (!canInstall) {
                dom.buttons.removeClass("warning").addClass("disabled");
                if (!dom.buttons.filter(":visible").length) {
                    dom.buttons.eq(0).show();
                }
                dom.buttons.each(function() {
                    this.removeAttribute("href");
                });
            } else {
                dom.buttons.click(startInstall);
            }
        }


        function initWebapp() {
            if (navigator.apps && navigator.apps.install) {
                dom.self.find('.button')
                    .removeClass('disabled')
                    .click(function(e) {
                        e.preventDefault();
                        navigator.apps.install({url: manifestURL});
                    });
            } else {
                // Attach something that says you can't install apps.
            }
        }


        //and of course, initialize the button.
        this.init();
    }

    z.b = function() {
        new Button(this);
    };

    jQuery.fn.installButton = function() {
        return this.each(z.b);
    };

})();
