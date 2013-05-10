/* 2013.05.10_10.44.19 */
(function(window, undefined) {

var defined = {};
var resolved = {};

function define(id, deps, module) {
    defined[id] = [deps, module];
}
define.amd = {jQuery: true};

function require(id) {

    if (!resolved[id]) {

        var definition = defined[id];

        if (!definition) {
            throw 'Attempted to resolve undefined module ' + id;
        }

        var deps = definition[0];
        var module = definition[1];

        if (typeof deps == 'function' && module === undefined) {
            module = deps;
            deps = [];
        }

        resolved[id] = module.apply(window, deps.map(require));

    }
    return resolved[id];
}

require.config = function() {};

window.require = require;
window.define = define;

(function(window, undefined) {

var defined = {};
var resolved = {};

function define(id, deps, module) {
    defined[id] = [deps, module];
}
define.amd = {jQuery: true};

function require(id) {

    if (!resolved[id]) {

        var definition = defined[id];

        if (!definition) {
            throw 'Attempted to resolve undefined module ' + id;
        }

        var deps = definition[0];
        var module = definition[1];

        if (typeof deps == 'function' && module === undefined) {
            module = deps;
            deps = [];
        }

        resolved[id] = module.apply(window, deps.map(require));

    }
    return resolved[id];
}

require.config = function() {};

window.require = require;
window.define = define;

'replace me';

require('marketplace');

})(window, void 0);

/*
    Provides the apps module, a wrapper around navigator.mozApps
*/
define('apps', ['jquery', 'underscore'], function($, _) {
    'use strict';

    /*

    apps.install(manifest_url, options)
    apps.installPackage(manifest_url, options)

    It's just like navigator.apps.install with the following enhancements:
    - If navigator.apps.install doesn't exist, an error is displayed
    - If the install resulted in errors, they are displayed to the user

    This requires at least one apps-error-msg div to be present.

    See also: https://developer.mozilla.org/docs/DOM/Apps.install

    The recognized option attributes are as follows:

    data
        Optional dict to pass as navigator.apps.install(url, data, ...)
    success
        Optional callback for when app installation was successful
    error
        Optional callback for when app installation resulted in error
    navigator
        Something other than the global navigator, useful for testing

    */
    function install(product, opt) {
        opt = opt || {};
        _.defaults(opt, {'navigator': navigator,
                         'data': {}});
        opt.data.categories = product.categories;
        var manifest_url = product.manifest_url;
        var $def = $.Deferred();
        var mozApps = opt.navigator.mozApps;

        /* Try to install the app. */
        if (manifest_url && mozApps &&
            (product.is_packaged ? mozApps.installPackage : mozApps.install)) {

            var installRequest = (
                mozApps[product.is_packaged ? 'installPackage' : 'install'](manifest_url, opt.data));
            installRequest.onsuccess = function() {
                var status;
                var isInstalled = setInterval(function() {
                    status = installRequest.result.installState;
                    if (status == 'installed') {
                        clearInterval(isInstalled);
                        $def.resolve(installRequest.result, product);
                    }
                    // TODO: What happens if there's an installation failure? Does this never end?
                }, 100);
            };
            installRequest.onerror = function() {
                // The JS shim still uses this.error instead of this.error.name.
                $def.reject(installRequest.result, product, this.error.name || this.error);
            };
        } else {
            $def.reject();
        }
        return $def.promise();
    }

    return {install: install};
});

define('assert', ['underscore'], function(_) {

    function assert(x, msg) {
        if (!x) {
            throw new Error(msg || 'Assertion failed');
        }
    }

    function ok_() {
        // <3 andym
        assert.apply(this, arguments);
    }

    function eq_(x, y, msg) {
        try {
            assert(x == y);
        } catch (e) {
            throw new Error(msg || ('"' + x + '" did not match "' + y + '"'));
        }
    }

    function eeq_(x, y, msg) {
        try {
            assert(x === y);
        } catch (e) {
            throw new Error(msg || ('"' + x + '" did not exactly match "' + y + '"'));
        }
    }

    // Fuzzy equals
    function feq_(x, y, msg) {
        try {
            assert(_.isEqual(x, y));
        } catch (e) {
            if (msg) {
                throw new Error(msg);
            } else {
                throw new Error(JSON.stringify(x) + ' did not match ' + JSON.stringify(y));
            }
        }
    }

    function _contain(haystack, needle) {
        if (_.isObject(haystack)) {
            return needle in haystack;
        } else if (_.isString(haystack)) {
            return haystack.indexOf(needle) !== -1;
        } else {
            return _.contains(haystack, needle);
        }
    }

    function contains(haystack, needle, msg) {
        msg = msg || (JSON.stringify(haystack) + ' does not contain ' + JSON.stringify(needle));
        assert(_contain(haystack, needle), msg);
    }

    function disincludes(haystack, needle, msg) {
        msg = msg || (JSON.stringify(haystack) + ' contains ' + JSON.stringify(needle));
        assert(!_contain(haystack, needle), msg);
    }

    /*
    How to mock:

    mock(
        'foomodule',  // The module you're testing
        {  // Modules being mocked
            utils: function() {
                return { ... };
            },
            capabilities: {
                widescreen: false
            }
        },
        function(foomodule) {  // We import the module for you.
            // Run your tests as usual.
            test('foomodule', function(done) {
                foomodule.should_not_explode();
                done();
            });
        }
    );
    */
    function mock(test_module, mock_objs, runner) {
        var stub_map = {};
        var stubbed = _.object(_.pairs(mock_objs).map(function(x) {
            var orig = x[0];
            x[0] += _.uniqueId('_');
            stub_map[orig] = x[0];

            // Function-ify non-functions.
            if (_.isFunction(x[1])) {
                x[1] = x[1]();
            } else if (_.isArray(x[1])) {
                // If it's an array, convert it to an array-like object.
                // Require.js freaks out when you give it an array, but this
                // should work in (almost) all circumstances.
                x[1] = _.extend({}, x[1])
            }

            return x;
        }));

        console.log(stub_map);
        var context = require.config({
            context: _.uniqueId(),
            map: {'*': stub_map},
            baseUrl: 'media/js/',
            paths: requirejs.s.contexts._.config.paths,
            shim: requirejs.s.contexts._.config.shim
        });

        _.each(stubbed, function(v, k) {
            define(k, v);
        });

        context([test_module], function(module) {
            runner.apply(this, [module, mock_objs]);
        });
    }

    return {
        assert: assert,
        ok_: ok_,
        eq_: eq_,
        eeq_: eeq_,
        feq_: feq_,
        contains: contains,
        disincludes: disincludes,
        mock: mock
    };
});


define('browser', ['utils'], function(utils) {
    'use strict';

    var osStrings = {
        'windows': 'Windows',
        'mac': 'Mac',
        'linux': 'Linux',
        'android': 'Android',
        'maemo': 'Maemo'
    };

    var os = {};
    var platform = '';
    for (var i in osStrings) {
        if (osStrings.hasOwnProperty(i)) {
            os[i] = navigator.userAgent.indexOf(osStrings[i]) != -1;
            if (os[i]) {
                platform = i;
            }
        }
    }
    if (!platform) {
        os['other'] = !platform;
        platform = 'other';
    }

    return {
        os: os,
        platform: platform
    };
});

define('buckets', [], function() {

    var aelem = document.createElement('audio');
    var velem = document.createElement('video');

    // Compatibilty with PhantomJS, which doesn't implement canPlayType
    if (!('canPlayType' in aelem)) {
        function noop() {return '';};
        velem = aelem = {canPlayType: noop};
    }

    var prefixes = ['moz', 'webkit', 'ms'];

    function prefixed(property, context) {
        if (!context) {
            context = window;
        }
        if (property in context) {
            return context[property];
        }
        // Camel-case it.
        property = property[0].toUpperCase() + property.substr(1);

        for (var i = 0, e; e = prefixes[i++];) {
            if (!!(context[e + property])) {
                return context[e + property];
            }
        }
    }

    var capabilities = [
        'mozApps' in navigator,
        'mozApps' in navigator && navigator.mozApps.installPackage,
        'mozPay' in navigator,
        'MozActivity' in window,
        'ondevicelight' in window,
        'ArchiveReader' in window,
        'battery' in navigator,
        'mozBluetooth' in navigator,
        'mozContacts' in navigator,
        'getDeviceStorage' in navigator,
        window.mozIndexedDB || window.indexedDB,
        'geolocation' in navigator && 'getCurrentPosition' in navigator.geolocation,
        'addIdleObserver' in navigator && 'removeIdleObserver' in navigator,
        'mozConnection' in navigator && (navigator.mozConnection.metered === true || navigator.mozConnection.metered === false),
        'mozNetworkStats' in navigator,
        'ondeviceproximity' in window,
        'mozPush' in navigator || 'push' in navigator,
        'ondeviceorientation' in window,
        'mozTime' in navigator,
        'vibrate' in navigator,
        'mozFM' in navigator || 'mozFMRadio' in navigator,
        'mozSms' in navigator,
        !!(('ontouchstart' in window) || window.DocumentTouch && document instanceof DocumentTouch),
        window.screen.width <= 540 && window.screen.height <= 960,  // qHD support
        !!aelem.canPlayType('audio/mpeg').replace(/^no$/, ''),  // mp3 support
        !!(window.Audio),  // Audio Data API
        !!(window.webkitAudioContext || window.AudioContext),  // Web Audio API
        !!velem.canPlayType('video/mp4; codecs="avc1.42E01E"').replace(/^no$/,''),  // H.264
        !!velem.canPlayType('video/webm; codecs="vp8"').replace(/^no$/,''),  // WebM
        !!prefixed('cancelFullScreen', document),  // Full Screen API
        !!prefixed('getGamepads', navigator),  // Gamepad API
        !!(prefixed('persistentStorage') || window.StorageInfo)  // Quota Management API
    ];

    var profile = parseInt(capabilities.map(function(x) {return !!x ? '1' : '0';}).join(''), 2).toString(16);
    // Add a count.
    profile += '.' + capabilities.length;
    // Add a version number.
    profile += '.1';

    return {
        get_profile: function() {return profile;},
        capabilities: capabilities
    };

});

(function() {

function defer_parser() {
    this._name = 'defer';
    this.tags = ['defer'];
    this.parse = function(parser, nodes, tokens) {
        var begun = parser.peekToken();
        parser.skipSymbol('defer');
        parser.skip(tokens.TOKEN_WHITESPACE);
        var args = parser.parseSignature();
        parser.advanceAfterBlockEnd(begun.value);

        var body, placeholder, empty, except;
        body = parser.parseUntilBlocks('placeholder', 'empty', 'except', 'end');

        if (parser.skipSymbol('placeholder')) {
            parser.skip(tokens.TOKEN_BLOCK_END);
            placeholder = parser.parseUntilBlocks('empty', 'except', 'end');
        }

        if (parser.skipSymbol('empty')) {
            parser.skip(tokens.TOKEN_BLOCK_END);
            empty = parser.parseUntilBlocks('except', 'end');
        }

        if (parser.skipSymbol('except')) {
            parser.skip(tokens.TOKEN_BLOCK_END);
            except = parser.parseUntilBlocks('end');
        }

        parser.advanceAfterBlockEnd();

        return new nodes.CallExtension(this, 'run', args, [body, placeholder, empty, except]);
    };

}
// If we're running in node, export the extensions.
if (typeof module !== 'undefined' && module.exports) {
    module.exports.extensions = [new defer_parser()];
}

// No need to install the extensions if require.js isn't around.
if (typeof define !== 'function') {
    return;
}

define(
    'builder',
    ['templates', 'helpers', 'l10n', 'models', 'notification', 'requests', 'settings', 'underscore', 'z', 'nunjucks.compat'],
    function(nunjucks, helpers, l10n, models, notification, requests, settings, _, z) {

    var SafeString = nunjucks.require('runtime').SafeString;

    console.log('Loading nunjucks builder tags...');
    var counter = 0;

    var gettext = l10n.gettext;

    function Builder() {
        var env = this.env = new nunjucks.Environment([], {autoescape: true});
        env.dev = nunjucks.env.dev;
        env.registerPrecompiled(nunjucks.templates);

        // For retrieving AJAX results from the view.
        var result_map = this.results = {};
        var result_handlers = {};

        var pool = requests.pool();

        function make_paginatable(injector, placeholder, target) {
            var els = placeholder.find('.loadmore button');
            if (!els.length) {
                return;
            }

            els.on('click', function() {
                injector(els.data('url'), els.parent(), target).done(function() {
                    z.page.trigger('loaded_more');
                }).fail(function() {
                    notification.notification({message: gettext('Failed to load the next page.')});
                });
            });
        }

        // This pretends to be the nunjucks extension that does the magic.
        var defer_runner = {
            run: function(context, signature, body, placeholder, empty, except) {
                var uid = 'ph_' + counter++;
                var out;

                var injector = function(url, replace, extract) {
                    var request;
                    if ('as' in signature && 'key' in signature) {
                        request = models(signature.as).get(url, signature.key, pool.get);
                    } else {
                        request = pool.get(url);
                    }

                    if ('id' in signature) {
                        result_handlers[signature.id] = request;
                        request.done(function(data) {
                            result_map[signature.id] = data;
                        });
                    }

                    function get_result(data, dont_cast) {
                        // `pluck` pulls the value out of the response.
                        // Equivalent to `this = this[pluck]`
                        if ('pluck' in signature) {
                            data = data[signature.pluck];
                        }
                        // `as` passes the data to the models for caching.
                        if (!dont_cast && 'as' in signature) {
                            var caster = models(signature.as).cast;
                            if (_.isArray(data)) {
                                _.each(data, caster);
                            } else {
                                caster(data);
                            }
                        }
                        var content = '';
                        if (empty && _.isArray(data) && data.length === 0) {
                            content = empty();
                        } else {
                            context.ctx.this = data;
                            content = body();
                        }
                        if (extract) {
                            var parsed = $($.parseHTML(content));
                            content = $(parsed.filter(extract).get().concat(parsed.find(extract).get())).children();
                        }
                        return content;
                    }

                    if (request.__cached) {
                        request.done(function(data) {
                            context.ctx['response'] = data;
                            out = get_result(data, true);

                            // Now update the response with the values from the model cache
                            // For details, see bug 870447
                            if ('as' in signature) {
                                var resp = data;
                                var plucked = 'pluck' in signature;
                                var uncaster = models(signature.as).uncast;

                                if (plucked) {
                                    resp = resp[signature.pluck];
                                }
                                if (_.isArray(resp)) {
                                    for (var i = 0; i < resp.length; i++) {
                                        resp[i] = uncaster(resp[i]);
                                    }
                                } else if (plucked) {
                                    data[signature.pluck] = uncaster(resp[i]);
                                }
                                // We can't do this for requests which have no pluck
                                // and aren't an array. :(
                            }

                        });
                        if (signature.paginate) {
                            pool.done(function() {
                                make_paginatable(injector, $('#' + uid), signature.paginate);
                            });
                        }
                        return;
                    }

                    request.done(function(data) {
                        var el = $('#' + uid);
                        context.ctx['response'] = data;
                        var content = get_result(data);
                        (replace ? replace.replaceWith : el.html).apply(replace || el, [content]);
                        if (signature.paginate) {
                            make_paginatable(injector, el, signature.paginate);
                        }
                    }).fail(function() {
                        var el = $('#' + uid);
                        (replace ? replace.replaceWith : el.html).apply(
                            replace || el,
                            [except ? except() : env.getTemplate(settings.fragment_error_template).render(helpers)]);
                    });
                    return request;
                };
                injector(signature.url);
                if (!out) {
                    out = '<div class="loading">' + (placeholder ? placeholder() : '') + '</div>';
                }

                out = '<div id="' + uid + '" class="placeholder">' + out + '</div>';
                var safestring = new SafeString(out);
                return safestring;
            }
        };
        this.env.addExtension('defer', defer_runner);

        this.start = function(template, defaults) {
            z.page.trigger('build_start');
            z.page.html(env.getTemplate(template).render(_.defaults(defaults || {}, helpers)));
            return this;
        };

        this.onload = function(id, callback) {
            result_handlers[id].done(callback);
            return this;
        };

        pool.promise(this);
        this.terminate = pool.abort;

        this.finish = function() {
            pool.always(function() {
                z.page.trigger('loaded');
            });
            pool.finish();
        };

        var context = _.once(function() {return z.context = {};});
        this.z = function(key, val) {
            context()[key] = val;
            switch (key) {
                case 'title':
                    if (!val) {
                        val = settings.title_suffix;
                    } else if (val !== settings.title_suffix) {
                        val += ' | ' + settings.title_suffix;
                    }
                    document.title = val;
                    break;
                case 'type':
                    z.body.attr('data-page-type', val);
                    break;
            }
        };
    }

    return {
        getBuilder: function() {return new Builder();}
    };

});

})();

define('buttons',
    ['browser', 'capabilities', 'format', 'l10n', 'z'],
    function(browser, capabilities, format, l10n, z) {

    var gettext = l10n.gettext;

    function getButton(product) {
        // Look up button by its manifest URL.
        return $(format.format('.button[data-manifest_url="{0}"]', product.manifest_url));
    }

    function setButton($button, text, cls) {
        if (cls == 'purchasing' || cls == 'installing') {
            // Save the old text of the button if we know we may revert later.
            $button.data('old-text', $button.html());
        }
        $button.html(text);
        if (!(cls == 'purchasing' || cls == 'installing')) {
            $button.removeClass('purchasing installing');
        }
        $button.addClass(cls);
    }

    function revertButton($button) {
        // Cancelled install/purchase. Roll back button to its previous state.
        $button.removeClass('purchasing installing error');
        if ($button.data('old-text')) {
            $button.html($button.data('old-text'));
        }
    }

    z.win.on('app_purchase_start', function(e, product) {
        setButton(getButton(product), gettext('Purchasing'), 'purchasing');
    }).on('app_purchase_success', function(e, product) {
        var $button = getButton(product);

        product['isPurchased'] = true;

        setButton($button, gettext('Purchased'), 'purchased');
    }).on('app_install_start', function(e, product) {
        var $button = getButton(product);
        setButton($button, '<span class="spin"></span>',
                  'installing');

        // Reset button if it's been 30 seconds without user action.
        setTimeout(function() {
            if ($button.hasClass('installing')) {
                revertButton($button);
            }
        }, 30000);
    }).on('app_install_success', function(e, installer, product, installedNow) {
        var $button = getButton(product);
        if (installedNow) {
            var $installed = $('#installed'),
                $how = $installed.find('.' + browser.platform);
            // Supported: Mac, Windows, or Linux.
            if ($how.length) {
                $installed.show();
                $how.show();
            }
        }
        z.apps[product.manifest_url] = z.state.mozApps[product.manifest_url] = installer;
        setButton($button, gettext('Launch'), 'launch install');
    }).on('app_purchase_error app_install_error', function(e, installer, product, msg) {
        revertButton($('button.installing'));
    }).on('buttons.overlay_dismissed', function() {
        // Dismissed error. Roll back.
        revertButton($('.button.error'));
    }).on('app_install_disabled', function(e, product) {
        // You're not using a compatible browser.
        var $button = $('.button.product'),
            $noApps = $('.no-apps'); // Reviewers page.

        setButton($button, $button.html(), 'disabled');

        if ($noApps.length) {
            $noApps.show();
        } else {
            $button.parent().append($('#noApps').html());
        }
    }).on('loaded', function() {
        if (!capabilities.webApps) {
            $('.button.product').attr('disabled', true);
        }
    });
});

define('cache', ['rewriters', 'underscore'], function(rewriters, _) {

    var cache = {};

    function has(key) {
        return key in cache;
    }

    function get(key) {
        return cache[key];
    }

    function purge(filter) {
        for (var key in cache) {
            if (cache.hasOwnProperty(key)) {
                if (filter && !filter(key)) {
                    continue;
                }
                delete cache[key];
            }
        }
    }

    function set(key, value) {
        for (var i = 0, rw; rw = rewriters[i++];) {
            var output = rw(key, value, cache);
            if (output === null) {
                return;
            } else if (output) {
                value = output;
            }
        }
        cache[key] = value;
    }

    function bust(key) {
        if (key in cache) {
            delete cache[key];
        }
    }

    function rewrite(matcher, worker, limit) {
        var count = 0;
        for (var key in cache) {
            if (matcher(key)) {
                cache[key] = worker(cache[key], key);
                if (limit && ++count >= limit) {
                    return;
                }
            }
        }
    }

    return {
        has: has,
        get: get,
        set: set,
        bust: bust,
        purge: purge,

        attemptRewrite: rewrite,
        raw: cache
    };
});

define('capabilities', [], function() {
    function safeMatchMedia(query) {
        var m = window.matchMedia(query);
        return !!m && m.matches;
    }

    return {
        'JSON': window.JSON && typeof JSON.parse === 'function',
        'debug': document.location.href.indexOf('dbg') >= 0,
        'debug_in_page': document.location.href.indexOf('dbginpage') >= 0,
        'console': window.console && typeof window.console.log === 'function',
        'replaceState': typeof history.replaceState === 'function',
        'chromeless': window.locationbar && !window.locationbar.visible,
        'webApps': !!(navigator.mozApps && navigator.mozApps.install),
        'app_runtime': !!(
            navigator.mozApps &&
            typeof navigator.mozApps.html5Implementation === 'undefined'
        ),
        'fileAPI': !!window.FileReader,
        'userAgent': navigator.userAgent,
        'widescreen': safeMatchMedia('(min-width: 1024px)'),
        'firefoxAndroid': navigator.userAgent.indexOf('Firefox') !== -1 && navigator.userAgent.indexOf('Android') !== -1,
        'touch': !!(('ontouchstart' in window) || window.DocumentTouch && document instanceof DocumentTouch),
        'nativeScroll': (function() {
            return 'WebkitOverflowScrolling' in document.createElement('div').style;
        })(),
        'performance': !!(window.performance || window.msPerformance || window.webkitPerformance || window.mozPerformance),
        'navPay': !!navigator.mozPay,
        'webactivities': !!(window.setMessageHandler || window.mozSetMessageHandler),
        'firefoxOS': navigator.mozApps && navigator.mozApps.installPackage &&
                     navigator.userAgent.indexOf('Android') === -1 &&
                     navigator.userAgent.indexOf('Mobile') !== -1,
        'phantom': navigator.userAgent.match(/Phantom/)  // Don't use this if you can help it.
    };

});

define('cat-dropdown',
    ['underscore', 'helpers', 'jquery', 'l10n', 'models', 'requests', 'templates', 'urls', 'z'],
    function(_, helpers, $, l10n, models, requests, nunjucks, urls, z) {
    'use strict';

    var gettext = l10n.gettext;

    var cat_models = models('category');
    cat_models.cast({
        name: gettext('All Categories'),
        slug: 'all'
    });

    var cat_dropdown = $('#cat-dropdown');
    var cat_list = $('#cat-list');


    // TODO: Detect when the user is offline and raise an error.

    // Do the request out here so it happens immediately when the app loads.
    var category_req = requests.get(urls.api.url('categories'));
    // Store the categories in models.
    category_req.done(function(data) {
        cat_models.cast(data.objects);
    });

    function toggleMenu(e) {
        if (e) {
            e.preventDefault();
        }
        $('.cat-menu').toggleClass('hidden');
        $('.dropdown').toggleClass('active');
    }

    function updateDropDown(catSlug, catTitle) {
        var $dropDown = $('.dropdown a');
        var oldCatSlug = $dropDown.data('catSlug');
        if (oldCatSlug !== catSlug) {
            category_req.then(function() {
                var model = cat_models.lookup(catSlug);
                catTitle = catTitle || (model && model.name) || catSlug;
                if (catTitle && catSlug && oldCatSlug) {
                    $dropDown.text(catTitle)
                             .removeClass('cat-' + oldCatSlug)
                             .addClass('cat-' + catSlug)
                             .data('catSlug', catSlug);
                }
            });
        }
    }

    function updateCurrentCat(catSlug, $elm) {
        var $catMenu = $('.cat-menu');
        var currentClass = 'current';
        $elm = $elm || $catMenu.find('.cat-' + catSlug);
        if (!$elm.hasClass(currentClass)) {
            $catMenu.find('.' + currentClass).removeClass(currentClass);
            $elm.addClass(currentClass);
        }
    }

    function handleDropDownClicks(e) {
        e.preventDefault();
        var $target = $(e.target);
        var newCat = $target.data('catSlug');
        var catTitle = $target.text();
        toggleMenu();
        updateDropDown(newCat, catTitle);
        updateCurrentCat(newCat, $target);
    }

    function handleDropDownMousedowns(e) {
        // When I press down on the mouse, add that cute little white checkmark.
        e.preventDefault();
        var $target = $(e.target);
        updateCurrentCat($target.data('catSlug'), $target);
    }

    function dropDownRefresh(catSlug) {
        updateDropDown(catSlug);
        updateCurrentCat(catSlug);
    }

    function handleBuildStart(e) {
        // Handle the showing of the dropdown.
        if (z.context && z.context.show_cats === true) {
            z.body.addClass('show-cats');
            z.context.show_cats = false;
            handleCatsRendered();
        } else {
            z.body.removeClass('show-cats');
        }
    }

    function handleCatsRendered() {
        if (z.context && z.context.cat) {
            dropDownRefresh(z.context.cat);
        }
    }

    function handleRenderDropdown() {
        // Render the dropdown itself.
        cat_dropdown.html(
            nunjucks.env.getTemplate('cat_dropdown.html').render(helpers));

        // Fetch the category dropdown-data
        category_req.done(function(data) {
            var context = _.extend({categories: data.objects}, helpers);
            cat_list.html(
                nunjucks.env.getTemplate('cat_list.html').render(context));
            handleCatsRendered();
        });
    }

    z.body.on('click', '.dropdown a', toggleMenu)
          .on('mouseup', '.cat-menu a', handleDropDownClicks)
          .on('mousedown', '.cat-menu a', handleDropDownMousedowns);
    z.page.on('build_start', handleBuildStart)
          .on('reload_chrome', handleRenderDropdown);

});

define('forms', ['z'], function(z) {

    function checkValid(form) {
        if (form) {
            $(form).find('button[type=submit]').attr('disabled', !form.checkValidity());
        }
    }
    z.body.on('change keyup paste', 'input, select, textarea', function(e) {
        checkValid(e.target.form);
    }).on('loaded overlayloaded', function() {
        $('form:not([novalidate])').each(function() {
            checkValid(this);
        });
        $('form[novalidate] button[type=submit]').removeAttr('disabled');
    });

    // Use this if you want to disable form inputs while the post/put happens.
    function toggleSubmitFormState($formElm, enabled) {
            $formElm.find('textarea, button, input').prop('disabled', !enabled);
            $formElm.find('.ratingwidget').toggleClass('disabled', !enabled);
    }

    return {toggleSubmitFormState: toggleSubmitFormState};

});

define('header', ['capabilities', 'z'], function(capabilities, z) {
    var htim;
    z.body.on('mousedown', '.wordmark', function() {
        htim = setTimeout(function() {z.body.toggleClass('nightly');}, 5000);
    }).on('mouseup', '.wordmark', function() {
        clearTimeout(htim);
    });

    // We would use :hover, but we want to hide the menu on fragment load!
    function act_tray() {
        $('.act-tray').on('mouseover', function() {
            $('.act-tray').addClass('active');
        }).on('mouseout', function() {
            $('.act-tray').removeClass('active');
        }).on('click', '.account-links a', function() {
            $('.account-links, .settings, .act-tray').removeClass('active');
        });
    }

    act_tray();
    z.page.on('loaded', function() {
        $('.account-links, .settings').removeClass('active');
    });
    z.body.on('reloaded_chrome', act_tray);
});

define('helpers',
       ['l10n', 'templates', 'underscore', 'utils', 'format', 'settings', 'urls', 'user'],
       function(l10n, nunjucks, _, utils) {

    var SafeString = nunjucks.require('runtime').SafeString;
    var env = nunjucks.env;

    function make_safe(func) {
        return function() {
            return new SafeString(func.apply(this, arguments));
        };
    }

    function safe_filter(name, func) {
        env.addFilter(name, make_safe(func));
    }

    env.addFilter('urlparams', utils.urlparams);
    env.addFilter('urlunparam', utils.urlunparam);

    safe_filter('nl2br', function(obj) {
        return obj.replace(/\n/g, '<br>');
    });

    safe_filter('make_data_attrs', function(obj) {
        return _.pairs(obj).map(function(pair) {
                return 'data-' + utils.escape_(pair[0]) + '="' + utils.escape_(pair[1]) + '"';
            }
        ).join(' ');
    });

    safe_filter('external_href', function(obj) {
        return 'href="' + utils.escape_(obj) + '" target="_blank"';
    });

    env.addFilter('numberfmt', function(obj) {
        // TODO: Provide number formatting
        return obj;
    });

    safe_filter('stringify', JSON.stringify);

    safe_filter('dataproduct', function(obj) {
        var product = _.extend({}, obj);

        if ('this' in product) {
            delete product.this;
        }
        if ('window' in product) {
            delete product.window;
        }
        return 'data-product="' + utils.escape_(JSON.stringify(product)) + '"';
    });

    env.addFilter('format', format.format);

    env.addFilter('sum', function(obj) {
        return obj.reduce(function(mem, num) {return mem + num;}, 0);
    });

    // Functions provided in the default context.
    return {
        api: require('urls').api.url,
        apiParams: require('urls').api.params,
        url: require('urls').reverse,

        _: make_safe(l10n.gettext),
        _plural: make_safe(l10n.ngettext),
        format: require('format').format,
        settings: require('settings'),
        user: require('user'),

        escape: utils.escape_,
        len: function(x) {return x.length;},
        max: Math.max,
        min: Math.min,
        range: _.range,

        REGIONS: require('settings').REGION_CHOICES_SLUG,

        navigator: window.navigator
    };
});

// Hey there! I know how to install apps. Buttons are dumb now.

define('install',
    ['apps', 'cache', 'capabilities', 'jquery', 'login', 'notification', 'payments/payments', 'requests', 'urls', 'user', 'z'],
    function(apps, cache, caps, $, login, notification, payments, requests, urls, user, z) {
    'use strict';

    function _handler(func) {
        return function(e) {
            e.preventDefault();
            e.stopPropagation();
            func($(this).closest('[data-product]').data('product'));
        }
    }

    var launchHandler = _handler(function(product) {
        z.apps[product.manifest_url].launch();
    });

    var installHandler = _handler(startInstall);

    function startInstall(product) {
        if (product.price && !user.logged_in()) {
            console.log('Install suspended; user needs to log in');
            return login.login().done(function() {
                startInstall(product);
            });
            return;
        }

        if (product.price) {
            return purchase(product);
        } else {
            return install(product);
        }
    }

    function purchase(product) {
        z.win.trigger('app_purchase_start', product);
        return $.when(payments.purchase(product))
                .done(purchaseSuccess)
                .fail(purchaseError);
    }

    function purchaseSuccess(product, receipt) {
        // Firefox doesn't successfully fetch the manifest unless I do this.
        z.win.trigger('app_purchase_success', [product]);
        setTimeout(function() {
            install(product);
        }, 0);

        // Bust the cache
        cache.bust(urls.api.url('purchases'));
    }

    function purchaseError(product, msg) {
        z.win.trigger('app_purchase_error', [product, msg]);
    }

    function install(product, receipt) {
        var data = {};
        var post_data = {
            app: product.id,
            chromeless: caps.chromeless ? 1 : 0
        };

        z.win.trigger('app_install_start', product);

        function do_install() {
            return $.when(apps.install(product, data))
                    .done(installSuccess)
                    .fail(installError);
        }

        var def = $.Deferred();
        requests.post(urls.api.url('record'), post_data).done(function(response) {
            if (response.error) {
                $('#pay-error').show().find('div').text(response.error);
                installError(product);
                def.reject();
                return;
            }
            if (response.receipt) {
                data.data = {'receipts': [response.receipt]};
            }
            do_install().done(def.resolve).fail(def.reject);
        }).fail(function() {
            // Could not record/generate receipt!
            installError(null, product);
            def.reject();
        });
        return def;
    }

    function installSuccess(installer, product) {
        z.win.trigger('app_install_success', [installer, product, true]);

        // Bust the cache
        cache.bust(urls.api.url('purchases'));
    }

    function installError(installer, product, msg) {
        console.log('error: ' + msg);

        switch (msg) {
            // mozApps error codes, defined in
            // https://developer.mozilla.org/en-US/docs/Apps/Apps_JavaScript_API/Error_object
            case 'MKT_CANCELLED':
            case 'DENIED':
            case 'MANIFEST_URL_ERROR':
            case 'NETWORK_ERROR':
            case 'MANIFEST_PARSE_ERROR':
            case 'INVALID_MANIFEST':
                break;
            // Marketplace specific error codes.
            default:
                notification.notification({
                    message: gettext('Install failed. Please try again later.')
                });
                break;
        }

        z.win.trigger('app_install_error', [installer, product, msg]);
    }

    z.page.on('click', '.product.launch', launchHandler)
          .on('click', '.button.product:not(.launch):not(.incompatible)', installHandler);
    z.body.on('logged_in', function() {
        if (localStorage.getItem('toInstall')) {
            var lsVal = localStorage.getItem('toInstall');
            localStorage.removeItem('toInstall');
            var product = $(format('.product[data-manifest_url="{0}"]',
                                   lsVal)).data('product');
            if (product) {
                startInstall(product);
            }
        }
    });
});

define('keys', [], function() {
    // Named key codes. That's the key idea here.
    return {
        'SHIFT': 16,
        'CONTROL': 17,
        'ALT': 18,
        'PAUSE': 19,
        'CAPS_LOCK': 20,
        'ESCAPE': 27,
        'ENTER': 13,
        'PAGE_UP': 33,
        'PAGE_DOWN': 34,
        'LEFT': 37,
        'UP': 38,
        'RIGHT': 39,
        'DOWN': 40,
        'HOME': 36,
        'END': 35,
        'COMMAND': 91,
        'WINDOWS_RIGHT': 92,
        'COMMAND_RIGHT': 93,
        'WINDOWS_LEFT_OPERA': 219,
        'WINDOWS_RIGHT_OPERA': 220,
        'APPLE': 24
    };
});

(function() {

var languages = ['cs', 'de', 'en-US', 'es', 'ga-IE', 'it', 'pl', 'pt-BR', 'zh-TW', 'dbg'];

var lang_expander = {
    'en': 'en-US', 'ga': 'ga-IE',
    'pt': 'pt-BR', 'sv': 'sv-SE',
    'zh': 'zh-CN'
};

if (!window.define) {
    function get_locale(locale) {
        if (languages.indexOf(locale) !== -1) {
            return locale;
        }
        locale = locale.split('-')[0];
        if (languages.indexOf(locale) !== -1) {
            return locale;
        }
        if (locale in lang_expander) {
            locale = lang_expander[locale];
            if (languages.indexOf(locale) !== -1) {
                return locale;
            }
        }
        return 'en-US';
    }
    var qs_lang = /[\?&]lang=([\w\-]+)/i.exec(window.location.search);
    var locale = get_locale((qs_lang && qs_lang[1]) || navigator.language);
    if (locale === 'en-US') {
        return;
    }
    document.write('<script src="/locales/' + locale + '.js"></script>');

} else {
    define('l10n', ['format'], function(format) {
        var rtlList = ['ar', 'he', 'fa', 'ps', 'ur'];

        function get(str, args, context) {
            context = context || navigator;
            var out;
            if (context.l10n && str in context.l10n.strings) {
                out = context.l10n.strings[str].body;
            } else {
                out = str;
            }
            if (args) {
                out = format.format(out, args);
            }
            return out;
        }
        function nget(str, plural, args, context) {
            context = context || navigator;
            if (!args || !('n' in args)) {
                throw new Error('`n` not passed to ngettext');
            }
            var out;
            var n = args.n;
            var strings;
            if (context.l10n && str in (strings = context.l10n.strings)) {
                if (strings[str].plurals) {
                    var plid = context.l10n.pluralize(n);
                    out = strings[str].plurals[plid];
                } else {
                    // Support for languages like zh-TW where there is no plural form.
                    out = strings[str].body;
                }
            } else {
                out = n === 1 ? str : plural;
            }
            return format.format(out, args);
        }

        window.gettext = get;
        window.ngettext = nget;

        return {
            gettext: get,
            ngettext: nget,
            getDirection: function(context) {
                var language = context ? context.language : navigator.language;
                if (language.indexOf('-') > -1) {
                    language = language.split('-')[0];
                }
                // http://www.w3.org/International/questions/qa-scripts
                // Arabic, Hebrew, Farsi, Pashto, Urdu
                return rtlList.indexOf(language) >= 0 ? 'rtl' : 'ltr';
            }
        };
    });
}
})();

define('lightbox', ['keys', 'utils', 'shothandles', 'underscore', 'z'],
       function(keys, utils, handles, _, z) {

    var $lightbox = $(document.getElementById('lightbox'));
    var $section = $lightbox.find('section');
    var $content = $lightbox.find('.content');
    var currentApp;
    var previews;
    var slider;
    var trayOrigin; // Remember the tray that originated the lightbox trigger.

    $lightbox.addClass('shots');

    function showLightbox() {
        var $this = $(this);
        var which = $this.closest('li').index();
        var $tray = $this.closest('.tray');
        var $tile = $tray.prev();
        trayOrigin = $this.closest('.content')[0];

        // we get the screenshots from the associated tile. No tile? bail.
        if (!$tile.hasClass('mkt-tile')) return;

        var product = $tile.data('product');
        var id = product.id;

        if (id != currentApp || !slider) {
            currentApp = id;
            previews = product.previews;
            renderPreviews();
        }

        // set up key bindings
        z.win.bind('keydown.lightboxDismiss', function(e) {
            switch (e.which) {
                case keys.ESCAPE:
                    e.preventDefault();
                    hideLightbox();
                    break;
                case keys.LEFT:
                    e.preventDefault();
                    if (slider) slider.toPrev();
                    break;
                case keys.RIGHT:
                    e.preventDefault();
                    if (slider) slider.toNext();
                    break;
            }
        });

        // fade that bad boy in
        $lightbox.show();
        setTimeout(function() {
            slider.moveToPoint(which);
            resize();
            $lightbox.addClass('show');
        }, 0);
    }

    // Beat this mutant with a stick once FF fixes layered transition repaints.
    function ghettoFresh(transformation) {
        if (!transformation) return;
        var trans = transformation.replace('translate3d(', '');
        trans = parseInt(trans.split(',')[0], 10) | 0;

        // Shift the tray by 1px then reset to original position.
        setTimeout(function() {
            trayOrigin.style.MozTransform = 'translate3d(' + (trans + 1) + 'px, 0, 0)';
            trayOrigin.style.MozTransform = 'translate3d(' + trans + 'px, 0, 0)';
            console.log('[lightbox] ghettoFresh() happened');
        }, 100);
    }

    function renderPreviews() {
        // clear out the existing content
        $content.empty();

        // place in a pane for each image/video with a 'loading' placeholder
        // and caption.
        _.each(previews, function(p) {
            var $el = $('<li class="loading">');
            var $cap = $('<div class="caption">');
            $cap.text(p.caption);
            $el.append($cap);
            $content.append($el);

            // let's fail elegantly when our images don't load.
            // videos on the other hand will always be injected.
            if (p.type == 'video/webm') {
                // we can check for `HTMLMediaElement.NETWORK_NO_SOURCE` on the
                // video's `networkState` property at some point.
                var v = $('<video src="' + p.image_url + '" controls></video>');
                $el.removeClass('loading');
                $el.append(v);
            } else {
                var i = new Image();

                i.onload = function() {
                    $el.removeClass('loading');
                    $el.append(i);
                };
                i.onerror = function() {
                    $el.removeClass('loading');
                    $el.append('<b class="err">&#x26A0;</b>');
                };

                // attempt to load the image.
                i.src = p.image_url;
            }
        });

        // $section doesn't have its proper width until after a paint.
        slider = Flipsnap($content[0], {disable3d: true});
        slider.element.addEventListener('fsmoveend', pauseVideos, false);

        handles.attachHandles(slider, $section);
    }

    function resize() {
        if (!slider) return;
        $content.find('.caption');
        slider.distance = $section.width();
        slider.refresh();
    }

    function pauseVideos() {
        $('video').each(function() {
            this.pause();
        });
    }

    function hideLightbox() {
        pauseVideos();
        $lightbox.removeClass('show');
        // We can't trust transitionend to fire in all cases.
        setTimeout(function() {
            $lightbox.hide();
        }, 500);
        z.win.unbind('keydown.lightboxDismiss');
        if (trayOrigin) {
            ghettoFresh(trayOrigin.style.MozTransform);
        }
    }

    // prevent mouse cursors from dragging these images.
    $lightbox.on('dragstart', function(e) {
        e.preventDefault();
    });

    // we need to adjust the scroll distances on resize.
    z.win.on('resize', _.debounce(resize, 200));

    // if a tray thumbnail is clicked, load up our lightbox.
    z.page.on('click', '.tray ul a', utils._pd(showLightbox));

    // dismiss the lighbox when we click outside it or on the close button.
    $lightbox.click(function(e) {
        if ($(e.target).is('#lightbox')) {
            hideLightbox();
            e.preventDefault();
        }
    });
    $lightbox.find('.close').click(utils._pd(hideLightbox));

    // Hide screenshot overlay on back button hit.
    z.page.on('navigate', hideLightbox);

});

define('login',
    ['cache', 'capabilities', 'jquery', 'models', 'notification', 'settings', 'underscore', 'urls', 'user', 'requests', 'z', 'utils'],
    function(cache, capabilities, $, models, notification, settings, _, urls, user, requests, z) {

    function flush_caches() {
        // We need to flush the global cache
        var cat_url = urls.api.url('categories');
        cache.purge(function(key) {return key != cat_url;});

        models('app').purge();
    }

    z.body.on('click', '.persona', function(e) {
        e.preventDefault();

        var $this = $(this);
        $this.addClass('loading-submit');
        startLogin().always(function() {
            $this.removeClass('loading-submit').blur();
        }).done(function() {
            notification.notification({message: gettext('You have been signed in')});
        });

    }).on('click', '.logout', function(e) {
        e.preventDefault();
        user.clear_token();
        z.body.removeClass('logged-in');
        z.page.trigger('reload_chrome');
        flush_caches();
        navigator.id.logout();
        notification.notification({message: gettext('You have been signed out')});
    });

    var pending_logins = [];

    function startLogin() {
        var def = $.Deferred();
        pending_logins.push(def);

        navigator.id.request({
            forceIssuer: settings.persona_unverified_issuer || null,
            allowUnverified: true,
            termsOfService: '/terms-of-use',
            privacyPolicy: '/privacy-policy',
            oncancel: function() {
                _.invoke(pending_logins, 'reject');
                pending_logins = [];
            }
        });
        return def.promise();
    }

    function gotVerifiedEmail(assertion) {
        if (assertion) {
            var data = {
                assertion: assertion,
                audience: window.location.protocol + '//' + window.location.host,
                is_native: navigator.id._shimmed ? 0 : 1
            };

            flush_caches();

            requests.post(urls.api.url('login'), data).done(function(data) {
                user.set_token(data.token, data.settings);
                console.log('[login] Finished login');
                z.body.addClass('logged-in');
                $('.loading-submit').removeClass('loading-submit');
                z.page.trigger('reload_chrome');
                z.page.trigger('logged_in');

                function resolve_pending() {
                    _.invoke(pending_logins, 'resolve');
                    pending_logins = [];
                }

                if (z.context.reload_on_login) {
                    require('views').reload().done(resolve_pending);
                } else {
                    resolve_pending();
                }

                var to = require('utils').getVars().to;
                if (to && to[0] == '/') {
                    z.page.trigger('navigate', [to]);
                    return;
                }
            }).fail(function(jqXHR, textStatus, error) {
                var err = jqXHR.responseText;
                if (!err) {
                    err = gettext("Persona login failed. Maybe you don't have an account under that email address?") + ' ' + textStatus + ' ' + error;
                }
                // Catch-all for XHR errors otherwise we'll trigger a notification
                // with its message as one of the error templates.
                if (jqXHR.status != 200) {
                    err = gettext('Persona login failed. A server error was encountered.');
                }
                $('.loading-submit').removeClass('loading-submit');
                notification.notification({message: err});

                _.invoke(pending_logins, 'reject');
                pending_logins = [];
            });
        } else {
            $('.loading-submit').removeClass('loading-submit');
        }
    }

    function init_persona() {
        $('.persona').css('cursor', 'pointer');
        var email = user.get_setting('email') || '';
        if (email) {
            console.log('[login] detected user', email);
        }
        navigator.id.watch({
            loggedInUser: email,
            onlogin: gotVerifiedEmail,
            onlogout: function() {
                z.body.removeClass('logged-in');
                z.page.trigger('reload_chrome');
                z.win.trigger('logout');
            }
        });
    }

    // Load `include.js` from persona.org, and drop login hotness like it's hot.
    var s = document.createElement('script');
    s.onload = init_persona;
    if (capabilities.firefoxOS) {
        // Load the Firefox OS include that knows how to handle native Persona.
        // Once this functionality lands in the normal include we can stop
        // doing this special case. See bug 821351.
        s.src = settings.native_persona;
    } else {
        s.src = settings.persona;
    }
    document.body.appendChild(s);
    $('.persona').css('cursor', 'wait');

    return {
        login: startLogin
    };
});

// Do this last- initialize the marketplace!
console.log('Mozilla(R) FP-MKT (R) 1.0');
console.log('   (C)Copyright Mozilla Corp 1998-2013');
console.log('');
console.log('64K High Memory Area is available.');

require.config({
    enforceDefine: true,
    paths: {
        'flipsnap': 'lib/flipsnap',
        'jquery': 'lib/jquery-1.9',
        'underscore': 'lib/underscore',
        'nunjucks': 'lib/nunjucks',
        'nunjucks.compat': 'lib/nunjucks.compat',
        'templates': '../../templates',
        'settings': ['settings_local', 'settings'],
        'stick': 'lib/stick',
        'format': 'lib/format'
    },
    shim: {
        'flipsnap': {exports: 'Flipsnap'},
        'jquery': {exports: 'jQuery'},
        'underscore': {exports: '_'}
    }
});

(function() {

    define(
        'marketplace',
        [
            'underscore',
            'buttons',
            'capabilities',
            'cat-dropdown',
            'forms',
            'header',
            'helpers',
            'install',
            'l10n',
            'lightbox',
            'login',
            'navigation',
            'outgoing_links',
            'overlay',
            'paginator',
            'previews',
            'ratings',
            'settings',
            'templates',
            'tracking',
            'user',
            'webactivities',
            'z'
        ],
    function(_) {

        console.log('[mkt] Dependencies resolved, starting init');

        var capabilities = require('capabilities');
        var nunjucks = require('templates');
        var settings = require('settings');
        var z = require('z');

        nunjucks.env.dev = true;

        // Get mobile region and carrier information.
        var GET = require('utils').getVars();
        settings.mcc = GET.mcc;
        settings.mnc = GET.mnc;

        z.body.addClass('html-' + require('l10n').getDirection());
        if (settings.body_classes) {
            z.body.addClass(settings.body_classes);
        }

        z.page.one('loaded', function() {
            console.log('[mkt] Hiding splash screen');
            $('#splash-overlay').addClass('hide');
        });

        // This lets you refresh within the app by holding down command + R.
        if (capabilities.chromeless) {
            window.addEventListener('keydown', function(e) {
                if (e.keyCode == 82 && e.metaKey) {
                    window.location.reload();
                }
            });
        }

        z.page.on('loaded', function() {
            z.apps = {};
            z.state.mozApps = {};
            if (capabilities.webApps) {
                // Get list of installed apps and mark as such.
                var r = navigator.mozApps.getInstalled();
                r.onsuccess = function() {
                    _.each(r.result, function(val) {
                        z.apps[val.manifestURL] = z.state.mozApps[val.manifestURL] = val;
                        z.win.trigger('app_install_success',
                                      [val, {'manifest_url': val.manifestURL}, false]);
                    });
                };
            }
        });


        // Do some last minute template compilation.
        z.page.on('reload_chrome', function() {
            console.log('[mkt] Reloading chrome');
            var context = _.extend({z: z}, require('helpers'));

            $('#site-header').html(
                nunjucks.env.getTemplate('header.html').render(context));
            $('#site-footer').html(
                nunjucks.env.getTemplate('footer.html').render(context));

            z.body.toggleClass('logged-in', require('user').logged_in());
            z.page.trigger('reloaded_chrome');
        }).trigger('reload_chrome');

        window.addEventListener(
            'resize',
            _.debounce(function() {z.doc.trigger('saferesize');}, 200),
            false
        );

        // Perform initial navigation.
        console.log('[mkt] Triggering initial navigation');
        z.page.trigger('navigate', [window.location.pathname + window.location.search]);

        // Debug page
        (function() {
            var to = false;
            z.doc.on('touchstart', '.wordmark', function() {
                console.log('[mkt] hold for debug...');
                clearTimeout(to);
                to = setTimeout(function() {
                    console.log('navigating to debug...');
                    z.page.trigger('navigate', ['/debug']);
                }, 5000);
            }).on('touchend', '.wordmark', function() {
                console.log('[mkt] debug hold broken.');
                clearTimeout(to);
            });
        })();

        console.log('[mkt] Initialization complete');
    });

})();

define('models', ['requests', 'underscore'], function(requests, _) {

    // {'type': {'<id>': object}}
    var data_store = {};

    var prototypes = {
        'app': 'slug',
        'category': 'slug',

        // Dummy prototypes to facilitate testing
        'dummy': 'id',
        'dummy2': 'id'
    };

    return function(type) {
        if (!(type in prototypes)) {
            throw new Error('Unknown model "' + type + '"');
        }

        if (!(type in data_store)) {
            // Where's defaultdict when you need it
            data_store[type] = {};
        }

        var key = prototypes[type];

        var cast = function(data) {
            function do_cast(data) {
                var keyed_value = data[key];
                data_store[type][keyed_value] = data;
                console.log('[model] Stored ' + keyed_value + ' as ' + type);
            }
            if (_.isArray(data)) {
                _.each(data, do_cast);
                return;
            }
            return do_cast(data);
        };

        var uncast = function(object) {
            function do_uncast(object) {
                return data_store[type][object[key]];
            }
            if (_.isArray(object)) {
                return object.map(uncast);
            }
            return do_uncast(object);
        };

        var get = function(url, keyed_value, getter) {
            getter = getter || requests.get;

            if (keyed_value) {
                if (keyed_value in data_store[type]) {
                    // Call the `.done()` function back in `request()`.
                    console.log('[model] Found ' + type + ' with key ' + keyed_value);
                    return $.Deferred()
                            .resolve(data_store[type][keyed_value])
                            .promise({__cached: true});
                }

                console.log('[model] ' + type + ' cache miss for key ' + keyed_value);
            }

            return getter(url);
        };

        var lookup = function(keyed_value, by) {
            if (by) {
                for (var key in data_store[type]) {
                    var item = data_store[type][key];
                    if (by in item && item[by] === keyed_value) {
                        return item;
                    }
                }
                return;
            }
            if (keyed_value in data_store[type]) {
                console.log('[model] Found ' + type + ' with lookup key ' + keyed_value);
                return data_store[type][keyed_value];
            }

            console.log('[model] ' + type + ' cache miss for key ' + keyed_value);
        };

        var purge = function() {
            data_store[type] = [];
        }

        return {
            cast: cast,
            uncast: uncast,
            get: get,
            lookup: lookup,
            purge: purge
        };
    };

});

define('navigation',
    ['capabilities', 'l10n', 'notification', 'underscore', 'urls', 'utils', 'views', 'z'],
    function(capabilities, l10n, notification, _, urls, utils, views, z) {
    'use strict';

    var gettext = l10n.gettext;
    var stack = [
        {path: '/', type: 'root'}
    ];
    var param_whitelist = ['q', 'sort', 'cat'];
    var last_bobj = null;

    function extract_nav_url(url) {
        // This function returns the URL that we should use for navigation.
        // It filters and orders the parameters to make sure that they pass
        // equality tests down the road.

        // If there's no URL params, return the original URL.
        if (url.indexOf('?') < 0) {
            return url;
        }

        var url_parts = url.split('?');
        // If there's nothing after the `?`, return the original URL.
        if (!url_parts[1]) {
            return url;
        }

        var used_params = _.pick(utils.getVars(url_parts[1]), param_whitelist);
        // If there are no query params after we filter, just return the path.
        if (!_.keys(used_params).length) {  // If there are no elements in the object...
            return url_parts[0];  // ...just return the path.
        }

        return url_parts[0] + '?' + (
            _.pairs(used_params)
            .sort(function(a, b) {return a[0] < b[0];})
            .map(function(pair) {
                if (typeof pair[1] === 'undefined')
                    return encodeURIComponent(pair[0]);
                else
                    return encodeURIComponent(pair[0]) + '=' +
                           encodeURIComponent(pair[1]);
            }).join('&'));
    }

    function canNavigate() {
        if (!navigator.onLine && !capabilities.phantom) {
            notification.notification({message: gettext('No internet connection')});
            return false;
        }
        return true;
    }

    function navigate(href, popped, state) {
        if (!state) return;

        console.log('[nav] Navigation started: ', href);
        var view = views.match(href);
        if (view === null) {
            return;
        }

        if (last_bobj) {
            z.win.trigger('unloading');  // Tell the world that we're cleaning stuff up.
        }
        last_bobj = views.build(view[0], view[1], state.params);
        z.win.trigger('navigating', [popped]);
        state.type = z.context.type;
        state.title = z.context.title;

        if ((state.preserveScroll || popped) && state.scrollTop) {
            z.page.one('loaded', function() {
                console.log('[nav] Setting scroll: ', state.scrollTop);
                z.doc.scrollTop(state.scrollTop);
            });
        } else {
            console.log('[nav] Resetting scroll');
            // Asynchronously reset scroll position.
            // This works around a bug in B2G/Android where rendering blocks interaction.
            setTimeout(function() {
                z.doc.scrollTop(0);
            }, 0);
        }

        // Clean the path's parameters.
        // /foo/bar?foo=bar&q=blah -> /foo/bar?q=blah
        state.path = extract_nav_url(state.path);

        // Truncate any closed navigational loops.
        for (var i = 0; i < stack.length; i++) {
            if (stack[i].path === state.path ||
                (state.type === 'search' && stack[i].type === state.type)) {
                console.log('[nav] Navigation loop truncated:', stack.slice(0, i));
                stack = stack.slice(i + 1);
                break;
            }
        }

        // Are we home? clear any history.
        if (state.type == 'root') {
            stack = [state];

            // Also clear any search queries living in the search box.
            // Bug 790009
            $('#search-q').val('');
        } else {
            // handle the back and forward buttons.
            if (popped && stack[0].path === state.path) {
                console.log('[nav] Shifting stack (used → or ← button)');
                stack.shift();
            } else {
                console.log('[nav] Pushed state onto stack: ', state.path);
                stack.unshift(state);
            }

            // TODO(fireplace): Make this work with views
            // Does the page have a parent? If so, handle the parent logic.
            if (z.context.parent) {
                var parent = _.indexOf(_.pluck(stack, 'path'), z.context.parent);

                if (parent > 1) {
                    // The parent is in the stack and it's not immediately
                    // behind the current page in the stack.
                    stack.splice(1, parent - 1);
                    console.log('[nav] Closing navigation loop to parent (1 to ' + (parent - 1) + ')');
                } else if (parent == -1) {
                    // The parent isn't in the stack. Splice it in just below
                    // where the value we just pushed in is.
                    stack.splice(1, 0, {path: z.context.parent});
                    console.log('[nav] Injecting parent into nav stack at 1');
                }
                console.log('[nav] New stack size: ' + stack.length);
            }
        }

    }

    z.body.on('click', '.site-header .back', utils._pd(function() {
        console.log('[nav] ← button pressed');
        if (!canNavigate()) {
            console.log('[nav] ← button aborted; canNavigate is falsey.');
            return;
        }

        if (stack.length > 1) {
            stack.shift();
            history.replaceState(stack[0], false, stack[0].path);
            navigate(stack[0].path, true, stack[0]);
        } else {
            console.log('[nav] attempted nav.back at root!');
        }
    }));

    z.page.on('search', function(e, params) {
        e.preventDefault();
        return z.page.trigger(
            'navigate', utils.urlparams(urls.reverse('search'), params));
    }).on('navigate divert', function(e, url, params, preserveScroll) {
        console.log('[nav] Received ' + e.type + ' event:', url);
        if (!url) return;

        var divert = e.type === 'divert';
        var newState = {
            params: params,
            path: url
        };
        var scrollTop = z.doc.scrollTop();
        var state_method = history.pushState;

        if (preserveScroll) {
            newState.preserveScroll = preserveScroll;
            newState.scrollTop = scrollTop;
        }

        if (!canNavigate()) {
            console.log('[nav] Navigation aborted; canNavigate is falsey.');
            return;
        }

        // Terminate any outstanding requests.
        if (last_bobj) {
            last_bobj.terminate();
        }

        // Update scrollTop for current history state.
        if (stack.length && scrollTop !== stack[0].scrollTop) {
            stack[0].scrollTop = scrollTop;
            console.log('[nav] Updating scrollTop for path: "' + stack[0].path + '" as: ' + scrollTop);
            history.replaceState(stack[0], false, stack[0].path);
        }

        if (!last_bobj || divert) {
            // If we're redirecting or we've never loaded a page before,
            // use replaceState instead of pushState.
            state_method = history.replaceState;
        }
        if (divert) {
            stack.shift();
        }
        state_method.apply(history, [newState, false, url]);
        navigate(url, false, newState);
    });

    function navigationFilter(el) {
        var href = el.getAttribute('href') || el.getAttribute('action'),
            $el = $(el);
        return !href || href.substr(0, 4) == 'http' ||
                href.substr(0, 7) === 'mailto:' ||
                href.substr(0, 11) === 'javascript:' ||
                href[0] === '#' ||
                href.indexOf('/developers/') !== -1 ||
                href.indexOf('/ecosystem/') !== -1 ||
                href.indexOf('/statistics/') !== -1 ||
                href.indexOf('?modified=') !== -1 ||
                el.getAttribute('target') === '_blank' ||
                el.getAttribute('rel') === 'external' ||
                $el.hasClass('post') || $el.hasClass('sync');
    }

    z.body.on('click', 'a', function(e) {
        var href = this.getAttribute('href');
        var $elm = $(this);
        var preserveScrollData = $elm.data('preserveScroll');
        // Handle both data-preserve-scroll and data-preserve-scroll="true"
        var preserveScroll = typeof preserveScrollData !== 'undefined' && preserveScrollData !== false;
        if (e.metaKey || e.ctrlKey || e.button !== 0) return;
        if (navigationFilter(this)) return;

        // We don't use _pd because we don't want to prevent default for the
        // above situations.
        e.preventDefault();
        e.stopPropagation();
        z.page.trigger('navigate', [href, $elm.data('params') || {path: href}, preserveScroll]);

    }).on('submit', 'form#search', function(e) {
        e.stopPropagation();
        e.preventDefault();
        var $q = $('#search-q');
        var query = $q.val();
        if (query == 'do a barrel roll') {
            z.body.toggleClass('roll');
        }
        $q.blur();
        z.page.trigger('search', {q: query});

    });
    z.win.on('popstate', function(e) {
        var state = e.originalEvent.state;
        if (state) {
            console.log('[nav] popstate navigate');
            navigate(state.path, true, state);
        }
    }).on('submit', 'form', function(e) {
        console.error("We don't allow form submissions.");
        return false;
    });

    return {
        stack: function() {return stack;},
        navigationFilter: navigationFilter
    };

});

define('notification', ['capabilities', 'jquery', 'z'], function(caps, $, z) {
    var notificationEl = $('<div id="notification">');
    var contentEl = $('<div id="notification-content">');
    var def;
    var addedClasses = [];

    function show() {
        notificationEl.addClass('show');
    }

    function hide() {
        notificationEl.removeClass('show');
    }

    // allow *bolding* message text
    var re = /\*([^\*]+)\*/g;
    function fancy(s) {
        if (!s) return;
        return s.replace(re, function(_, match) { return '<b>' + match + '</b>'; });
    }

    function notification(opts) {
        if (def && def.state() === 'pending') {
            def.reject();
        }
        def = $.Deferred();
        def.always(hide);
        notificationEl.removeClass(addedClasses.join(' '));
        contentEl.text('');
        addedClasses = [];

        var message = opts.message;
        if (!message) return;

        if ('classes' in opts) {
            addedClasses = opts.classes.split(/\s+/);
        }

        if (opts.closable) {
            addedClasses.push('closable');
        }
        setTimeout(def.reject, opts.timeout || 5000);

        notificationEl.addClass(addedClasses.join(' '));

        var fancyMessage = fancy(message);
        if (fancyMessage == message) {
            contentEl.text(message);
        } else {
            contentEl.html(fancyMessage);
        }

        notificationEl.addClass('show');

        return def.promise();

    }

    notificationEl.append(contentEl).on('touchstart click', function() {
        def.resolve();
    });
    z.body.append(notificationEl);

    return {notification: notification};
});

define('outgoing_links', ['capabilities', 'z'], function(capabilities, z) {

    // Show the actual URL of outgoing links in the status bar.
    // e.g. http://outgoing.mozilla.org/v1/b2d58f443178ce1de2ef80bb57dcc80211232c8b/http%3A//wvtc.net/
    // ...will display as http://wvtc.net/
    //
    z.win.bind('loaded', function mungeLinks() {

        // Hijack external links if we're within the app.
        if (capabilities.chromeless) {
            $('a[rel=external]').attr('target', '_blank');
        }

        $('a[href^="http://outgoing.mozilla.org"]').each(function(e) {
            var $a = $(this),
                outgoing = $a.attr('href'),
                dest = unescape(outgoing.split('/').slice(5).join('/'));
            // Change it to the real destination:
            $a.attr('href', dest);
            if (capabilities.chromeless) {
                $a.attr('target', '_blank');
            }
            $a.click(function(e) {
                // Change it to the outgoing URL:
                $a.attr('href', outgoing);
                setTimeout(function() {
                    // Put back the real destination:
                    $a.attr('href', dest);
                }, 100);
                return true;
            });
        });
    });

    // If we're inside the Marketplace app, open external links in the Browser.
    z.doc.on('click', 'a.external, a[rel=external]', function() {
        if (capabilities.chromeless) {
            $(this).attr('target', '_blank');
        }
    });
});

// Checks buttons for overflowing text and makes them wider if necessary.
// - Currently only deals with infobox buttons.
define('overflow', [], function() {
    // We need this init. It's not called by marketplace.js, promise.
    return {init: function() {
        // If this happens elsewhere we can target `.button` and use the
        // .closest() parent to apply "overflowing" to.
        var $infobox = $('.infobox.support');

        $infobox.find('ul.c a').each(function() {
            if (this.scrollWidth > $(this).innerWidth()) {
                $infobox.addClass('overflowing');
                return;
            }
        });
    }};
});

define('overlay', ['keys', 'l10n', 'utils', 'z'], function(keys, l10n, utils, z) {
    // Welcome to the world of overlays!
    // To setup your trigger do:
    // function() { z.body.trigger('decloak');doOtherStuff(); }

    var gettext = l10n.gettext;
    var $cloak = $('.cloak');

    function dismiss() {
        if ($cloak.is('.show')) {
            $('.modal').removeClass('show');
            $cloak.removeClass('show').trigger('overlay_dismissed');
        }
    }

    $cloak.on('touchmove', function(e) {
        e.preventDefault();
        e.stopPropagation();
    }).on('click', function(e) {
        if ($(e.target).parent('body').length) {
            dismiss();
        }
    }).on('dismiss', function() {
        dismiss();
    });

    z.body.on('click', function() {
        $('#notification').removeClass('show');
    }).on('keydown.overlayDismiss', function(e) {
        if (!utils.fieldFocused(e) && e.which == keys.ESCAPE) {
            e.preventDefault();
            dismiss();
        }
    }).on('overlay_dismissed', function() {
        z.body.removeClass('overlayed');
    }).on('decloak', function() {
        z.body.addClass('overlayed');
        $cloak.addClass('show');
    }).on('click', '.modal .btn-cancel, .modal .cancel', utils._pd(dismiss));

    z.page.on('loaded', dismiss);
});

define('paginator', ['z'], function(z) {

    z.page.on('click', '.loadmore button', function(e) {
        // Get the button.
        var button = $(this);
        // Get the container.
        var swapEl = button.parents('.loadmore');
        // Show a loading indicator.
        swapEl.addClass('loading');
        swapEl.append('<div class="spinner alt btn-replace">');
    });

});

define('previews',
    ['flipsnap', 'templates', 'capabilities', 'shothandles', 'underscore', 'z'],
    function(Flipsnap, nunjucks, caps, handles, _, z) {

    // magic numbers!
    var THUMB_WIDTH = 150;
    var THUMB_PADDED = 165;

    var slider_pool = [];

    function populateTray() {
        // preview trays expect to immediately follow a .mkt-tile.
        var $tray = $(this);
        var $tile = $tray.prev();
        if (!$tile.hasClass('mkt-tile') || $tray.find('.slider').length) {
            return;
        }
        var product = $tile.data('product');
        var previewsHTML = '';
        if (!product || !product.previews) return;
        _.each(product.previews, function(p) {
            p.typeclass = p.filetype === 'video/webm' ? 'video' : 'img';
            previewsHTML += nunjucks.env.getTemplate('detail/single_preview.html').render(p);
        });

        var dotHTML = '';
        if (product.previews.length > 1) {
            dotHTML = Array(product.previews.length + 1).join('<b class="dot"></b>');
        } else {
            $tray.addClass('single');
        }
        $tray.html(nunjucks.env.getTemplate('detail/preview_tray.html').render({
            previews: previewsHTML,
            dots: dotHTML
        }));

        var numPreviews = $tray.find('li').length;
        var $content = $tray.find('.content');

        var width = numPreviews * THUMB_PADDED - 15;

        $content.css({
            width: width + 'px',
            margin: '0 ' + ($tray.width() - THUMB_WIDTH) / 2 + 'px'
        });

        var slider = Flipsnap(
            $tray.find('.content')[0],
            {distance: THUMB_PADDED,
             disable3d: true}
        );
        var $pointer = $tray.find('.dots .dot');

        slider.element.addEventListener('fsmoveend', setActiveDot, false);

        // Show as many thumbs as possible to start. Using MATH!
        slider.moveToPoint(~~($tray.width() / THUMB_PADDED / 2));

        slider_pool.push(slider);

        function setActiveDot() {
            $pointer.filter('.current').removeClass('current');
            $pointer.eq(slider.currentPoint).addClass('current');
        }
        $tray.on('click.tray', '.dot', function() {
            slider.moveToPoint($(this).index());
        });

        // Tray can fit 3 desktop thumbs before paging is required.
        if (numPreviews > 3 && caps.widescreen) {
            handles.attachHandles(slider, $tray.find('.slider'));
        }

    }

    // Reinitialize Flipsnap positions on resize.
    z.doc.on('saferesize.tray', function() {
        $('.tray').each(function() {
            var $tray = $(this);
            $tray.find('.content').css('margin', '0 ' + ($tray.width() - THUMB_WIDTH) / 2 + 'px');
        });
        for (var i = 0, e; e = slider_pool[i++];) {
            e.refresh();
        }
    });

    // We're leaving the page, so destroy Flipsnap.
    z.win.on('unloading.tray', function() {
        $('.tray').off('click.tray');
        for (var i = 0, e; e = slider_pool[i++];) {
            e.destroy();
        }
        slider_pool = [];
    });

    z.page.on('dragstart dragover', function(e) {
        e.preventDefault();
    }).on('populatetray', function() {
        // TODO: Nuke this logging once we're sure trays work as intended.
        console.log('[previews] Populating trays');
        $('.listing.expanded .mkt-tile + .tray:empty').each(populateTray);
    });

});

define('ratings',
    ['cache', 'capabilities', 'l10n', 'login', 'templates', 'underscore', 'utils', 'urls', 'user', 'z', 'requests', 'notification', 'common/ratingwidget'],
    function(cache, capabilities, l10n, login, nunjucks, _, utils, urls, user, z) {
    'use strict';

    var gettext = l10n.gettext;
    var notify = require('notification').notification;
    var forms = require('forms');

    // Initializes character counters for textareas.
    function initCharCount() {
        var countChars = function(el, cc) {
            var $el = $(el);
            var max = parseInt($el.attr('maxlength'), 10);
            var left = max - $el.val().length;
            // L10n: {n} is the number of characters left.
            cc.html(ngettext('<b>{n}</b> character left.',
                             '<b>{n}</b> characters left.', {n: left}))
              .toggleClass('error', left < 0);
        };
        $('.char-count').each(function() {
            var $cc = $(this);
            $cc.closest('form')
               .find('#' + $cc.data('for'))
               .on('keyup blur', _.throttle(function() {countChars(this, $cc);}, 250))
               .trigger('blur');
        });
    }

    function rewriter(app, rewriter) {
        var unsigned_url = urls.api.unsigned.url('reviews');
        cache.attemptRewrite(
            function(key) {
                if (utils.baseurl(key) !== unsigned_url) {
                    return;
                }
                var kwargs = utils.querystring(key);
                if ('app' in kwargs && kwargs.app === app) {
                    return true;
                }
            },
            rewriter
        );
    }

    function flagReview($reviewEl) {
        var $modal = $('.report-spam');

        if (!$modal.length) {
            z.page.append(
                nunjucks.env.getTemplate('ratings/report.html').render(require('helpers'))
            );
            $modal = $('.report-spam');
        }

        $modal.one('click', '.menu a', utils._pd(function(e) {
            var $actionEl = $reviewEl.find('.actions .flag');
            $('.cloak').trigger('dismiss');
            $actionEl.text(gettext('Sending report...'));
            require('requests').post(
                require('settings').api_url + urls.api.sign($reviewEl.data('report-uri')),
                {flag: $(e.target).attr('href').replace('#', '')}
            ).done(function() {
                notify({message: gettext('Review flagged')});
                $actionEl.remove();
            }).fail(function() {
                notify({message: gettext('Report review operation failed')});
            });
        }));

        z.body.trigger('decloak');
        $modal.addClass('show');
    }

    function deleteReview(reviewEl, uri, app) {
        reviewEl.addClass('deleting');
        require('requests').del(require('settings').api_url + urls.api.sign(uri)).done(function() {
            notify({message: gettext('Your review was deleted')});

            rewriter(app, function(data) {
                data.objects = data.objects.filter(function(obj) {
                    return obj.resource_uri !== uri;
                });
                data.meta.total_count -= 1;
                data.user.has_rated = false;
                return data;
            });
            require('views').reload();

        }).fail(function() {
            notify({message: gettext('There was a problem deleting the review')});
        });
    }

    function addReview($senderEl) {

        // If the user isn't logged in, prompt them to do so.
        if (!user.logged_in()) {
            login.login().done(function() {
                addReview($senderEl);
            });
            return;
        }

        var ctx = _.extend({slug: $senderEl.data('app')}, require('helpers'));
        z.page.append(
            nunjucks.env.getTemplate('ratings/write.html').render(ctx)
        );

        $('.compose-review').find('select[name="rating"]').ratingwidget('large');
        initCharCount();

        z.body.trigger('decloak');
        $('.compose-review.modal').addClass('show');
    }

    z.page.on('click', '.review .actions a, #add-review', utils._pd(function(e) {
        var $this = $(this);

        var action = $this.data('action');
        if (!action) return;
        var $review = $this.closest('.review');
        switch (action) {
            case 'delete':
                deleteReview($review, $this.data('href'), $this.data('app'));
                break;
            case 'add':
                addReview($this);
                break;
            case 'report':
                flagReview($review);
                break;
        }
    })).on('loaded', function() {
        // Hijack <select> with stars.
        $('select[name="rating"]').ratingwidget();
        initCharCount();
    });

    z.body.on('submit', 'form.add-review-form', function(e) {
        e.preventDefault();

        var $this = $(this);
        var app = $this.data('app');


        var data = utils.getVars($this.serialize());
        data.app = app;

        // This must be below `.serialize()`. Disabled form controls aren't posted.
        forms.toggleSubmitFormState($this);

        require('requests').post(
            urls.api.url('reviews'),
            data
        ).done(function(new_review) {

            rewriter(app, function(data) {
                data.objects.unshift(new_review);
                data.meta.total_count += 1;
                data.user.has_rated = true;
                return data;
            });

            notify({message: gettext('Your review was posted')});
            z.page.trigger('navigate', urls.reverse('app', [$this.data('app')]));

        }).fail(function() {
            forms.toggleSubmitFormState($this, true);
            notify({message: gettext('Error while submitting review')});
        });
    });

    return {_rewriter: rewriter};

});

define('requests',
    ['cache', 'jquery', 'user', 'utils'],
    function(cache, $, user, utils) {
    /*
    Methods:

    - get(url, [successCallback, [errorCallback]])
      Makes a GET request to the specified URL.

      Returns a promise object similar to the one returned by jQuery AJAX
      methods. If the response to the request is cached, the returned
      promise will have a property `__cached` set to `true`.

      If you do not want your request intentionally cached, use `_get`
      (which has an identical prototype) instead.

    - post(url, body, [successCallback, [errorCallback]])
      Makes a POST request to the specified URL with the given body.

      Returns a promise object similar to the one returned by jQuery AJAX
      methods. POST requests are never intentionally cached.

    - pool()
      Creates a new request pool and returns the request pool.

      Returns a request pool object. All request pool objects are promises
      which complete when all requests in the pool have completed.


    Request Pool Methods:

    - get(url, [successCallback, [errorCallback]])
      Functionally similar to the root `get()` method.

      If a GET request to that URL has already been made, that request's
      promise is returned instead.

      The initiated request is added to the pool. The request will block the
      pool's promise from resolving or rejecting.

    - post(url, body, [successCallback, [errorCallback]])
      Functionally similar to the root `post()` method.

      The initiated request is added to the pool. The request will block the
      pool's promise from resolving or rejecting.

    - finish()
      Closes the pool (prevents new requests). If no requests have been made
      at this point, the pool's promise will resolve.

    - abort()
      Aborts all requests in the pool. Rejects the pool's promise.

    */

    function get(url) {
        if (cache.has(url)) {
            console.log('[req] GETing from cache', url);
            return $.Deferred()
                    .resolve(cache.get(url))
                    .promise({__cached: true});
        }
        return _get.apply(this, arguments);
    }

    function _get(url) {
        console.log('[req] GETing', url);
        return $.get(url).done(function(data, status, xhr) {
            console.log('[req] GOT', url);
            cache.set(url, data);

            if (!xhr) {
                return;
            }
            var filter_header;
            if ((!user.get_setting('region') || user.get_setting('region') == 'internet') &&
                (filter_header = xhr.getResponseHeader('API-Filter'))) {
                var region = utils.getVars(filter_header).region;
                user.update_settings({region: region});
            }
        });
    }

    function handle_errors(jqxhr, status) {
        console.log('[req] Request failed: ', status);
        if (jqxhr.responseText) {
            try {
                var data = JSON.parse(jqxhr.responseText);
                if ('error_message' in data) {
                    console.log('[req] Error message: ', data.error_message);
                } else {
                    console.log('[req] Response data: ', jqxhr.responseText);
                }
            } catch(e) {}
        }
    }

    function post(url, data) {
        console.log('[req] POSTing', url);
        return $.post(url, data).done(function(data) {
            console.log('[req] POSTed', url);
        }).fail(handle_errors);
    }

    function del(url) {
        console.log('[req] DELETing', url);
        return $.ajax({
            url: url,
            type: 'DELETE'
            // type: 'POST',
            // headers: {'X-HTTP-METHOD-OVERRIDE': 'DELETE'}
        }).fail(handle_errors);
    }

    function put(url, data) {
        console.log('[req] PUTing', url);
        return $.ajax({
            url: url,
            type: 'PUT',
            // type: 'POST',
            // headers: {'X-HTTP-METHOD-OVERRIDE': 'PUT'},
            data: data
        }).fail(handle_errors);
    }

    function patch(url, data) {
        console.log('[req] PATCHing', url);
        return $.ajax({
            url: url,
            type: 'PATCH',
            // type: 'POST',
            // headers: {'X-HTTP-METHOD-OVERRIDE': 'PATCH'},
            data: data
        }).fail(handle_errors);
    }

    function Pool() {
        console.log('[req] Opening pool');
        var requests = [];
        var req_map = {};

        var def = $.Deferred();
        var initiated = 0;
        var closed = false;

        var finish = this.finish = function() {
            if (closed) {
                return;
            }
            if (!initiated) {
                console.log('[req] Closing pool');
                closed = true;
                // Don't allow new requests.
                this.get = null;
                this.post = null;
                this.del = null;

                // Resolve the deferred whenevs.
                if (window.setImmediate) {
                    setImmediate(def.resolve);
                } else {
                    setTimeout(def.resolve, 0);
                }
            }
        };

        function make(func, args) {
            var req = func.apply(this, args);
            initiated++;
            requests.push(req);
            req.always(function() {
                initiated--;
                // Prevent race condition causing early
                // closing of pool.
                setTimeout(finish, 0);
            });
            return req;
        }

        this.get = function(url) {
            if (url in req_map) {
                return req_map[url];
            }
            var req = make(get, arguments);
            req_map[url] = req;
            return req;
        };
        this.post = function() {return make(post, arguments);};
        this.del = function() {return make(del, arguments);};
        this.put = function() {return make(put, arguments);};
        this.patch = function() {return make(patch, arguments);};

        this.abort = function() {
            for (var i = 0, request; request = requests[i++];) {
                if (request.abort === undefined || request.isSuccess !== false) {
                    return;
                }
                request.abort();
            }
            def.reject();
        };

        def.promise(this);
    }

    return {
        get: get,
        post: post,
        del: del,
        put: put,
        patch: patch,
        pool: function() {return new Pool();}
    };
});

define('rewriters',
    ['underscore', 'urls', 'utils'],
    function(_, urls, utils) {

    function pagination(url) {
        return function(new_key, new_value, c) {

            var new_base = utils.baseurl(new_key);
            if (new_base !== utils.baseurl(url)) {
                return;
            }
            // Don't rewrite if we're only getting the first page.
            var new_qs = utils.querystring(new_key);
            if (!('offset' in new_qs)) {
                return;
            }

            delete new_qs.offset;
            delete new_qs.limit;
            var old_url = utils.urlparams(new_base, new_qs);
            console.log('[rewrite] Attempting to rewrite', old_url);
            if (!(old_url in c)) {
                console.error('[rewrite] Could not find cache entry to rewrite');
                return;
            }

            c[old_url].meta.limit += new_value.meta.limit;
            c[old_url].meta.next = new_value.meta.next;
            c[old_url].objects = c[old_url].objects.concat(new_value.objects);

            // Tell cache.js that we don't want to store the new cache item.
            return null;
        };
    }

    return [
        // Search pagination rewriter
        pagination(urls.api.unsigned.url('search')),

        // Category pagination rewriter
        pagination(urls.api.unsigned.url('category'))
    ];
});

(function() {

var dependencies;
/* dtrace */
var routes = [
    {pattern: '^/$', view_name: 'homepage'},
    {pattern: '^/(index|server).html$', view_name: 'homepage'},
    {pattern: '^/app/([^/<>"\']+)/ratings/add$', view_name: 'app/ratings/add'},
    {pattern: '^/app/([^/<>"\']+)/ratings/edit$', view_name: 'app/ratings/edit'},
    {pattern: '^/app/([^/<>"\']+)/ratings$', view_name: 'app/ratings'},
    {pattern: '^/app/([^/<>"\']+)/abuse$', view_name: 'app/abuse'},
    {pattern: '^/app/([^/<>"\']+)/privacy$', view_name: 'app/privacy'},
    {pattern: '^/app/([^/<>"\']+)$', view_name: 'app'},
    {pattern: '^/app/([^/<>"\']+)/$', view_name: 'app'},  // For the trailing slash
    {pattern: '^/search$', view_name: 'search'},
    {pattern: '^/category/([^/<>"\']+)$', view_name: 'category'},
    {pattern: '^/category/([^/<>"\']+)/featured$', view_name: 'featured'},
    {pattern: '^/settings$', view_name: 'settings'},
    {pattern: '^/feedback$', view_name: 'feedback'},
    {pattern: '^/purchases$', view_name: 'purchases'},

    {pattern: '^/privacy-policy$', view_name: 'privacy'},
    {pattern: '^/terms-of-use$', view_name: 'terms'},

    {pattern: '^/tests$', view_name: 'tests'},
    {pattern: '^/debug$', view_name: 'debug'}
];

dependencies = routes.map(function(i) {return 'views/' + i.view_name;});
/* /dtrace */
window.routes = routes;

define(
    'routes',
    // dynamically import all the view modules form the routes
    dependencies,
    function() {
        for (var i = 0; i < routes.length; i++) {
            var route = routes[i];
            var view = require('views/' + route.view_name);
            route.view = view;
        }
        console.log('[routes] Views loaded')
        return routes;
    }
);

})();

define('settings', ['settings_local', 'underscore'], function(settings_local, _) {
    return _.defaults(settings_local, {
        api_url: 'http://' + window.location.hostname + ':5000',  // No trailing slash, please.

        simulate_nav_pay: false,

        fragment_error_template: 'errors/fragment.html',

        payments_enabled: true,
        tracking_enabled: false,

        // TODO: put real values here.
        REGION_CHOICES_SLUG: {
            '': 'Worldwide',
            'br': 'Brazil',
            'co': 'Colombia',
            'pl': 'Poland',
            'es': 'Spain',
            'uk': 'United Kingdom',
            'us': 'United States',
            've': 'Venezuela'
        },

        timing_url: '',  // TODO: figure this out

        persona_unverified_issuer: null,
        native_persona: 'https://native-persona.org/include.js',
        persona: 'https://login.persona.org/include.js',

        title_suffix: 'Firefox Marketplace',
        carrier: null,

        // `MCC`: Mobile Country Code
        mcc: null,

        // `MNC`: Mobile Network Code
        mnc: null
    });
});

define('settings_local', [], function() {
    var origin = window.location.origin || (
        window.location.protocol + '//' + window.location.host);
    return {
        api_url: origin,
        tracking_enabled: true
    };
});

define('shothandles', ['utils'], function(utils) {
    function attachHandles(slider, $container) {
        $container.find('.prev, .next').remove();

        var $prevHandle = $('<a href="#" class="prev"></a>'),
            $nextHandle = $('<a href="#" class="next"></a>');

        function setHandleState() {
            $prevHandle.hide();
            $nextHandle.hide();

            if (slider.hasNext()) {
                $nextHandle.show();
            }
            if (slider.hasPrev()) {
                $prevHandle.show();
            }
        }

        $prevHandle.click(utils._pd(function() {
            slider.toPrev();
        }));
        $nextHandle.click(utils._pd(function() {
            slider.toNext();
        }));

        slider.element.addEventListener('fsmoveend', setHandleState);

        setHandleState();
        $container.append($prevHandle, $nextHandle);
    }

    return {attachHandles: attachHandles};
});

define('tracking', ['settings', 'z'], function(settings, z) {
    if (!settings.tracking_enabled) {
        return;
    }

    // GA Tracking.
    window._gaq = window._gaq || [];

    _gaq.push(['_setAccount', 'UA-36116321-6']);
    _gaq.push(['_trackPageview']);


    var ga = document.createElement('script');
    ga.type = 'text/javascript';
    ga.async = true;
    ga.src = ('https:' == document.location.protocol ? 'https://ssl' : 'http://www') + '.google-analytics.com/ga.js';
    // GA is the first script element.
    var s = document.getElementsByTagName('script')[0];
    console.log('[tracking] Initializing Google Analytics');
    s.parentNode.insertBefore(ga, s);

    z.win.on('navigating', function(e, popped) {
        // Otherwise we'll track back button hits etc.
        if (!popped) {
            console.log('[tracking] Tracking page view', window.location.href);
            _gaq.push(['_trackPageview', window.location.href]);
        }
    });

});

define('urls',
    ['buckets', 'capabilities', 'format', 'settings', 'underscore', 'user', 'utils'],
    function(buckets, caps, format, settings, _) {

    var group_pattern = /\(.+\)/;
    var reverse = function(view_name, args) {
        args = args || [];
        for (var i in routes) {
            var route = routes[i];
            if (route.view_name != view_name)
                continue;

            // Strip the ^ and $ from the route pattern.
            var url = route.pattern.substring(1, route.pattern.length - 1);

            // TODO: if we get significantly complex routes, it might make
            // sense to _.memoize() or somehow cache the pre-formatted URLs.

            // Replace each matched group with a positional formatting placeholder.
            var i = 0;
            while (group_pattern.test(url)) {
                url = url.replace(group_pattern, '{' + i++ + '}');
            }

            // Check that we got the right number of arguments.
            if (args.length != i) {
                console.error('Expected ' + i + ' args, got ' + args.length);
                throw new Error('Wrong number of arguments passed to reverse(). View: "' + view_name + '", Argument "' + args + '"');
            }

            return format.format(url, args);

        }
        console.error('Could not find the view "' + view_name + '".');
    };

    var api_endpoints = {
        'app': '/api/v1/apps/app/{0}/',
        'category': '/api/v1/apps/search/featured/?cat={0}',
        'categories': '/api/v1/apps/category/',
        'reviews': '/api/v1/apps/rating/',
        'settings': '/api/v1/account/settings/mine/',
        'installed': '/api/v1/account/installed/mine/',
        'login': '/api/v1/account/login/',
        'record': '/api/v1/receipts/install/',
        'app_abuse': '/api/v1/abuse/app/',
        'search': '/api/v1/apps/search/',
        'feedback': '/api/v1/account/feedback/',
        'terms_of_use': '/terms-of-use.html',
        'privacy_policy': '/privacy-policy.html',

        'prepare_nav_pay': '/api/v1/webpay/prepare/',
        'payments_status': '/api/v1/webpay/status/{0}/'
    };

    var _device = function() {
        if (caps.firefoxOS) {
            return 'firefoxos';
        } else if (caps.firefoxAndroid) {
            return 'android';
        } else {
            return 'desktop';
        }
    };

    var user = require('user');
    function _userArgs(func) {
        return function() {
            var out = func.apply(this, arguments);
            var args = {
                format: 'json',
                lang: navigator.language,
                region: user.get_setting('region') || '',
                //scr: caps.widescreen ? 'wide' : 'mobile',
                //tch: caps.touch,
                dev: _device(),
                pro: buckets.get_profile()
            };
            if (user.logged_in()) {
                args._user = user.get_token();
            }
            if (settings.carrier) {
                args.carrier = settings.carrier.slug;
            }
            return require('utils').urlparams(out, args);
        };
    }

    var api = function(endpoint, args, params) {
        if (!(endpoint in api_endpoints)) {
            console.error('Invalid API endpoint: ' + endpoint);
            return '';
        }
        var url = settings.api_url + format.format(api_endpoints[endpoint], args || []);
        if (params) {
            return require('utils').urlparams(url, params);
        }
        return url;
    };

    var apiParams = function(endpoint, params) {
        return api(endpoint, [], params);
    };

    return {
        reverse: reverse,
        api: {
            url: _userArgs(api),
            params: _userArgs(apiParams),
            sign: _userArgs(_.identity),
            unsigned: {
                url: api,
                params: apiParams
            }
        }
    };
});

define('user', ['capabilities'], function(capabilities) {

    var token;
    var settings = {};

    var save_to_ls = !capabilities.phantom;

    if (save_to_ls) {
        token = localStorage.getItem('user');
        settings = JSON.parse(localStorage.getItem('settings') || '{}');
    }

    function clear_token() {
        localStorage.removeItem('user');
        if ('email' in settings) {
            delete settings.email;
            save_settings();
        }
        token = null;
    }

    function get_setting(setting) {
        return settings[setting];
    }

    function set_token(new_token, new_settings) {
        if (!new_token) {
            return;
        }
        token = new_token;
        if (save_to_ls) {
            localStorage.setItem('user', token);
        }
        update_settings(new_settings);
    }

    function save_settings() {
        if (save_to_ls) {
            localStorage.setItem('settings', JSON.stringify(settings));
        }
    }

    function update_settings(data) {
        if (!data) {
            return;
        }
        _.extend(settings, data);
        save_settings();
    }

    return {
        clear_token: clear_token,
        get_setting: get_setting,
        get_token: function() {return token;},
        logged_in: function() {return !!token;},
        set_token: set_token,
        update_settings: update_settings
    };
});

define('utils', ['jquery', 'underscore'], function($, _) {
    _.extend(String.prototype, {
        strip: function(str) {
            // Strip all whitespace.
            return this.replace(/\s/g, '');
        }
    });

    function _pd(func) {
        return function(e) {
            e.preventDefault();
            if (func) {
                func.apply(this, arguments);
            }
        };
    }

    function escape_(s) {
        if (s === undefined) {
            return;
        }
        return s.replace(/&/g, '&amp;').replace(/>/g, '&gt;').replace(/</g, '&lt;')
                .replace(/'/g, '&#39;').replace(/"/g, '&#34;');
    }

    function fieldFocused(e) {
        var tags = /input|keygen|meter|option|output|progress|select|textarea/i;
        return tags.test(e.target.nodeName);
    }

    function querystring(url) {
        var qpos = url.indexOf('?');
        if (qpos === -1) {
            return {};
        } else {
            return getVars(url.substr(qpos + 1));
        }
    }

    function baseurl(url) {
        return url.split('?')[0];
    }

    function encodeURIComponent() {
        return window.encodeURIComponent.apply(this, arguments).replace(/%20/g, '+');
    }

    function decodeURIComponent() {
        return window.decodeURIComponent.apply(this, arguments).replace(/\+/g, ' ');
    }

    function urlencode(kwargs) {
        var params = [];
        if ('__keywords' in kwargs) {
            delete kwargs.__keywords;
        }
        var keys = _.keys(kwargs).sort();
        for (var i = 0; i < keys.length; i++) {
            var key = keys[i];
            var value = kwargs[key];
            if (value === undefined) {
                params.push(encodeURIComponent(key));
            } else {
                params.push(encodeURIComponent(key) + '=' +
                            encodeURIComponent(value));
            }
        }
        return params.join('&');
    }

    function urlparams(url, kwargs) {
        return baseurl(url) + '?' + urlencode(_.defaults(kwargs, querystring(url)));
    }

    function urlunparam(url, params) {
        var qs = querystring(url);
        for (var i = 0, p; p = params[i++];) {
            if (!(p in qs)) {
                continue;
            }
            delete qs[p];
        }
        var base = baseurl(url);
        if (_.isEmpty(qs)) {
            return base;
        }
        return base + '?' + urlencode(qs);
    }

    function getVars(qs, excl_undefined) {
        if (typeof qs === 'undefined') {
            qs = location.search;
        }
        if (qs && qs[0] == '?') {
            qs = qs.substr(1);  // Filter off the leading ? if it's there.
        }
        if (!qs) return {};

        return _.chain(qs.split('&'))  // ['a=b', 'c=d']
                .map(function(c) {return c.split('=').map(decodeURIComponent);}) //  [['a', 'b'], ['c', 'd']]
                .filter(function(p) {  // [['a', 'b'], ['c', undefined]] -> [['a', 'b']]
                    return !!p[0] && (!excl_undefined || !_.isUndefined(p[1]));
                }).object()  // {'a': 'b', 'c': 'd'}
                .value();
    }

    return {
        '_pd': _pd,
        'escape_': escape_,
        'fieldFocused': fieldFocused,
        'getVars': getVars,
        'urlparams': urlparams,
        'urlunparam': urlunparam,
        'baseurl': baseurl,
        'querystring': querystring,
        'urlencode': urlencode
    };

});

define('views',
    ['builder', 'routes', 'underscore', 'utils', 'views/not_found', 'z'],
    function(builder, routes, _, utils, not_found, z) {

    routes = routes.map(function(route) {
        route.regexp = new RegExp(route.pattern);
        return route;
    });

    function match_route(url) {
        // Returns a 2-tuple: (view, [args]) or null

        var hashpos, qspos;
        // Strip the hash string
        if ((hashpos = url.indexOf('#')) >= 0) {
            url = url.substr(0, hashpos);
        }

        // Strip the query string
        if ((qspos = url.indexOf('?')) >= 0) {
            url = url.substr(0, qspos);
        }

        // Force a leading slash
        if (url[0] != '/') {
            url = '/' + url;
        }

        console.log('[views] Routing', url);
        for (var i in routes) {
            var route = routes[i];
            if (route === undefined) continue;

            // console.log('Testing route', route.regexp);
            var matches = route.regexp.exec(url);
            if (!matches)
                continue;

            // console.log('Found route: ', route.view_name);
            try {
                return [route.view, _.rest(matches)];
            } catch (e) {
                console.error('Route matched but view not initialized!', e);
                return null;
            }

        }

        console.warn('Failed to match route for ' + url);
        return [not_found, null];
    }

    var last_args;
    function build(view, args, params) {
        last_args = arguments;  // Save the arguments in case we reload.

        var bobj = builder.getBuilder();
        view(bobj, args, utils.getVars(), params);

        // If there were no requests, the page is ready immediately.
        bobj.finish();

        return bobj;
    }

    function reload() {
        z.win.trigger('unloading');
        return build.apply(this, last_args);
    }

    return {
        build: build,
        match: match_route,
        reload: reload,
        routes: routes
    };

});

define('webactivities',
    ['capabilities', 'urls', 'z'],
    function(capabilities, urls, z) {

    if (!capabilities.webactivities) {
        return;
    }

    // Load up an app
    navigator.mozSetMessageHandler('marketplace-app', function(req) {
        var slug = req.source.data.slug;
        z.page.trigger('navigate', [urls.reverse('app', [slug])]);
    });

    // Load up the page to leave a rating for the app.
    navigator.mozSetMessageHandler('marketplace-app-rating', function(req) {
        var slug = req.source.data.slug;
        z.page.trigger('navigate', [urls.reverse('app/ratings/add', [slug])]);
    });

    // Load up a category page
    navigator.mozSetMessageHandler('marketplace-category', function(req) {
        var slug = req.source.data.slug;
        z.page.trigger('navigate', [urls.reverse('category', [slug])]);
    });

    // Load up a search
    navigator.mozSetMessageHandler('marketplace-search', function(req) {
        var query = req.source.data.query;
        z.page.trigger('search', {q: query});
    });
});

define('z', ['jquery', 'underscore'], function($, _) {
    var z = {
        win: $(window),
        doc: $(document),
        body: $(document.body),
        container: $('main'),
        page: $('#page'),
        canInstallApps: true,
        state: {},
        apps: {}
    };

    var data_user = z.body.data('user');

    _.extend(z, {
        allowAnonInstalls: !!z.body.data('allow-anon-installs'),
        enableSearchSuggestions: !!z.body.data('enable-search-suggestions'),
        anonymous: data_user ? data_user.anonymous : false,
        pre_auth: data_user ? data_user.pre_auth : false
    });

    return z;
});

define('common/ratingwidget', ['jquery'], function($) {
    // Replaces rating selectboxes with the rating widget
    $.fn.ratingwidget = function(classes) {
        this.each(function(n, el) {
            if (!classes) {
                classes = '';
            }
            var $el = $(el);
            var allClasses = 'ratingwidget stars stars-0 ' + classes;
            var $widget = $('<span class="' + allClasses + '"></span>');
            var rs = '';
            var showStars = function(n) {
                $widget.removeClass('stars-0 stars-1 stars-2 stars-3 stars-4 stars-5').addClass('stars-' + n);
            };
            var setStars = function(n) {
                if (rating == n) return;
                var e = $widget.find(format('[value="{0}"]', n));
                e.click();
                showStars(n);
                rating = n;
            };
            var rating;

            // Existing rating found so initialize the widget.
            if ($('option[selected]', $el).length) {
                var temp_rating = $el.val();
                setStars(temp_rating);
                rating = parseInt(temp_rating, 10);
            }
            for (var i = 1; i <= 5; i++) {
                var checked = rating === i ? ' checked' : '';
                rs += format('<label data-stars="{0}">{1}<input required type="radio" name="rating"{2} value="{3}"></label>',
                             [i, ngettext('{n} star', '{n} stars', {n: i}), checked, i]);
            }
            $widget.click(function(evt) {
                var t = $(evt.target);
                if (t.is('input[type=radio]')) {
                    showStars(rating = t.attr('value'));
                    if (!t.val()) {
                        // If the user caused a radio button to become unchecked,
                        // re-check it because that shouldn't happen.
                        t.attr('checked', true);
                    }
                }
            }).mouseover(function(evt) {
                var t = $(evt.target);
                if (t.attr('data-stars')) {
                    showStars(t.attr('data-stars'));
                }
            }).mouseout(function(evt) {
                showStars(rating || 0);
            }).bind('touchmove touchend', function(e) {
                var wid = $widget.width();
                var left = $widget.offset().left;
                var r = (e.originalEvent.touches[0].clientX - left) / wid * 5 + 1;
                r = Math.min(Math.max(r, 1), 5) | 0;
                setStars(r);
            });
            $widget.html(rs);
            $el.before($widget).detach();
        });
        return this;
    };
});

/**
 * flipsnap.js
 *
 * @version  0.3.0
 * @url http://pxgrid.github.com/js-flipsnap/
 *
 * Copyright 2011 PixelGrid, Inc.
 * Licensed under the MIT License:
 * http://www.opensource.org/licenses/mit-license.php
 */

(function(window, document, undefined) {

var div = document.createElement('div');
var prefix = ['webkit', 'moz', 'o', 'ms'];
var saveProp = {};
var support = {};

support.transform3d = hasProp([
	'perspectiveProperty',
	'WebkitPerspective',
	'MozPerspective',
	'OPerspective',
	'msPerspective'
]);

support.transform = hasProp([
	'transformProperty',
	'WebkitTransform',
	'MozTransform',
	'OTransform',
	'msTransform'
]);

support.transition = hasProp([
	'transitionProperty',
	'WebkitTransitionProperty',
	'MozTransitionProperty',
	'OTransitionProperty',
	'msTransitionProperty'
]);

support.touch = 'ontouchstart' in window;

support.cssAnimation = (support.transform3d || support.transform) && support.transition;

var touchStartEvent = support.touch ? 'touchstart' : 'mousedown';
var touchMoveEvent = support.touch ? 'touchmove' : 'mousemove';
var touchEndEvent = support.touch ? 'touchend' : 'mouseup';

function Flipsnap(element, opts) {
	return (this instanceof Flipsnap)
		? this.init(element, opts)
		: new Flipsnap(element, opts);
}

Flipsnap.prototype.init = function(element, opts) {
	var self = this;

	// set element
	self.element = element;
	if (typeof element === 'string') {
		self.element = document.querySelector(element);
	}

	if (!self.element) {
		throw new Error('element not found');
	}

	// set opts
	opts = opts || {};
	self.distance = (opts.distance === undefined) ? null : opts.distance;
	self.maxPoint = (opts.maxPoint === undefined) ? null : opts.maxPoint;
	self.disableTouch = (opts.disableTouch === undefined) ? false : opts.disableTouch;
	self.disable3d = (opts.disable3d === undefined) ? false : opts.disable3d;

	// set property
	self.currentPoint = 0;
	self.currentX = 0;
	self.animation = false;
	self.use3d = support.transform3d;
	if (self.disable3d === true) {
		self.use3d = false;
	}

	// set default style
	if (support.cssAnimation) {
		self._setStyle({
			transitionProperty: getCSSVal('transform'),
			transitionTimingFunction: 'cubic-bezier(0,0,0.25,1)',
			transitionDuration: '0ms',
			transform: self._getTranslate(0)
		});
	}
	else {
		self._setStyle({
			position: 'relative',
			left: '0px'
		});
	}

	// initilize
	self.refresh();

	self.element.addEventListener(touchStartEvent, self, false);
	window.addEventListener(touchMoveEvent, self, false);
	window.addEventListener(touchEndEvent, self, false);

	return self;
};

Flipsnap.prototype.handleEvent = function(event) {
	var self = this;

	switch (event.type) {
		case touchStartEvent:
			self._touchStart(event);
			break;
		case touchMoveEvent:
			self._touchMove(event);
			break;
		case touchEndEvent:
			self._touchEnd(event);
			break;
		case 'click':
			self._click(event);
			break;
	}
};

Flipsnap.prototype.refresh = function() {
	var self = this;

	// setting max point
	self._maxPoint = self.maxPoint || (function() {
		var childNodes = self.element.childNodes,
			itemLength = 0,
			i = 0,
			len = childNodes.length,
			node;
		for(; i < len; i++) {
			node = childNodes[i];
			if (node.nodeType === 1) {
				itemLength++;
			}
		}
		if (itemLength > 0) {
			itemLength--;
		}

		return itemLength;
	})();

	// setting distance
	self._distance = self.distance || self.element.scrollWidth / (self._maxPoint + 1);

	// setting maxX
	self._maxX = -self._distance * self._maxPoint;

	self.moveToPoint();
};

Flipsnap.prototype.hasNext = function() {
	var self = this;

	return self.currentPoint < self._maxPoint;
};

Flipsnap.prototype.hasPrev = function() {
	var self = this;

	return self.currentPoint > 0;
};

Flipsnap.prototype.toNext = function() {
	var self = this;

	if (!self.hasNext()) {
		return;
	}

	self.moveToPoint(self.currentPoint + 1);
};

Flipsnap.prototype.toPrev = function() {
	var self = this;

	if (!self.hasPrev()) {
		return;
	}

	self.moveToPoint(self.currentPoint - 1);
};

Flipsnap.prototype.moveToPoint = function(point) {
	var self = this;

	var beforePoint = self.currentPoint;

	// not called from `refresh()`
	if (point === undefined) {
		point = self.currentPoint;
	}

	if (point < 0) {
		self.currentPoint = 0;
	}
	else if (point > self._maxPoint) {
		self.currentPoint = self._maxPoint;
	}
	else {
		self.currentPoint = parseInt(point, 10);
	}

	if (support.cssAnimation) {
		self._setStyle({ transitionDuration: '350ms' });
	}
	else {
		self.animation = true;
	}
	self._setX(- self.currentPoint * self._distance);

	if (beforePoint !== self.currentPoint) { // is move?
		triggerEvent(self.element, 'fsmoveend', true, false);
	}
};

Flipsnap.prototype._setX = function(x) {
	var self = this;

	self.currentX = x;
	if (support.cssAnimation) {
		self.element.style[ saveProp.transform ] = self._getTranslate(x);
	}
	else {
		if (self.animation) {
			self._animate(x);
		}
		else {
			self.element.style.left = x + 'px';
		}
	}
};

Flipsnap.prototype._touchStart = function(event) {
	var self = this;

	if (self.disableTouch) {
		return;
	}

	if (support.cssAnimation) {
		self._setStyle({ transitionDuration: '0ms' });
	}
	else {
		self.animation = false;
	}
	self.scrolling = true;
	self.moveReady = false;
	self.startPageX = getPage(event, 'pageX');
	self.startPageY = getPage(event, 'pageY');
	self.basePageX = self.startPageX;
	self.directionX = 0;
	self.startTime = event.timeStamp;
};

Flipsnap.prototype._touchMove = function(event) {
	var self = this;

	if (!self.scrolling) {
		return;
	}

	var pageX = getPage(event, 'pageX'),
		pageY = getPage(event, 'pageY'),
		distX,
		newX,
		deltaX,
		deltaY;

	if (self.moveReady) {
		// event.preventDefault();
		event.stopPropagation();

		distX = pageX - self.basePageX;
		newX = self.currentX + distX;
		if (newX >= 0 || newX < self._maxX) {
			newX = Math.round(self.currentX + distX / 3);
		}
		self._setX(newX);

		// When distX is 0, use one previous value.
		// For android firefox. When touchend fired, touchmove also
		// fired and distX is certainly set to 0.
		self.directionX =
			distX === 0 ? self.directionX :
			distX > 0 ? -1 : 1;
	}
	else {
		deltaX = Math.abs(pageX - self.startPageX);
		deltaY = Math.abs(pageY - self.startPageY);
		if (deltaX > 5) {
			// event.preventDefault();
			event.stopPropagation();
			self.moveReady = true;
			self.element.addEventListener('click', self, true);
		}
		else if (deltaY > 5) {
			self.scrolling = false;
		}
	}

	self.basePageX = pageX;
};

Flipsnap.prototype._touchEnd = function(event) {
	var self = this;

	if (!self.scrolling) {
		return;
	}

	self.scrolling = false;

	var newPoint = -self.currentX / self._distance;
	newPoint =
		(self.directionX > 0) ? Math.ceil(newPoint) :
		(self.directionX < 0) ? Math.floor(newPoint) :
		Math.round(newPoint);

	self.moveToPoint(newPoint);

	setTimeout(function() {
		self.element.removeEventListener('click', self, true);
	}, 200);
};

Flipsnap.prototype._click = function(event) {
	var self = this;

	event.stopPropagation();
	event.preventDefault();
};

Flipsnap.prototype._setStyle = function(styles) {
	var self = this;
	var style = self.element.style;

	for (var prop in styles) {
		setStyle(style, prop, styles[prop]);
	}
};

Flipsnap.prototype._animate = function(x) {
	var self = this;

	var elem = self.element;
	var begin = +new Date();
	var from = parseInt(elem.style.left, 10);
	var to = x;
	var duration = 350;
	var easing = function(time, duration) {
		return -(time /= duration) * (time - 2);
	};
	var timer = setInterval(function() {
		var time = new Date() - begin;
		var pos, now;
		if (time > duration) {
			clearInterval(timer);
			now = to;
		}
		else {
			pos = easing(time, duration);
			now = pos * (to - from) + from;
		}
		elem.style.left = now + "px";
	}, 10);
};

Flipsnap.prototype.destroy = function() {
	var self = this;

	self.element.removeEventListener(touchStartEvent, self);
	self.element.removeEventListener(touchMoveEvent, self);
	self.element.removeEventListener(touchEndEvent, self);
};

Flipsnap.prototype._getTranslate = function(x) {
	var self = this;

	return self.use3d
		? 'translate3d(' + x + 'px, 0, 0)'
		: 'translate(' + x + 'px, 0)';
};

function getPage(event, page) {
	return support.touch ? event.changedTouches[0][page] : event[page];
}

function hasProp(props) {
	return some(props, function(prop) {
		return div.style[ prop ] !== undefined;
	});
}

function setStyle(style, prop, val) {
	var _saveProp = saveProp[ prop ];
	if (_saveProp) {
		style[ _saveProp ] = val;
	}
	else if (style[ prop ] !== undefined) {
		saveProp[ prop ] = prop;
		style[ prop ] = val;
	}
	else {
		some(prefix, function(_prefix) {
			var _prop = ucFirst(_prefix) + ucFirst(prop);
			if (style[ _prop ] !== undefined) {
				saveProp[ prop ] = _prop;
				style[ _prop ] = val;
				return true;
			}
		});
	}
}

function getCSSVal(prop) {
	if (div.style[ prop ] !== undefined) {
		return prop;
	}
	else {
		var ret;
		some(prefix, function(_prefix) {
			var _prop = ucFirst(_prefix) + ucFirst(prop);
			if (div.style[ _prop ] !== undefined) {
				ret = '-' + _prefix + '-' + prop;
				return true;
			}
		});
		return ret;
	}
}

function ucFirst(str) {
	return str.charAt(0).toUpperCase() + str.substr(1);
}

function some(ary, callback) {
	for (var i = 0, len = ary.length; i < len; i++) {
		if (callback(ary[i], i)) {
			return true;
		}
	}
	return false;
}

function triggerEvent(element, type, bubbles, cancelable) {
	var ev = document.createEvent('Event');
	ev.initEvent(type, bubbles, cancelable);
	element.dispatchEvent(ev);
}

window.Flipsnap = Flipsnap;

define('flipsnap', [], function() {return Flipsnap;});

})(window, window.document);

/* Python(ish) string formatting:
 * >>> format('{0}', ['zzz'])
 * "zzz"
 * >>> format('{0}{1}', 1, 2)
 * "12"
 * >>> format('{x}', {x: 1})
 * "1"
 */
var format = (function() {
    var re = /\{([^}]+)\}/g;
    return function(s, args) {
        if (!s) {
            throw "Format string is empty!";
        }
        if (!args) return;
        if (!(args instanceof Array || args instanceof Object))
            args = Array.prototype.slice.call(arguments, 1);
        return s.replace(re, function(_, match){ return args[match]; });
    };
})();
function template(s) {
    if (!s) {
        throw "Template string is empty!";
    }
    return function(args) { return format(s, args); };
}

define('format', [], function() {
    return {
        format: format,
        template: template
    };
});

/*!
 * jQuery JavaScript Library v1.9.1
 * http://jquery.com/
 *
 * Includes Sizzle.js
 * http://sizzlejs.com/
 *
 * Copyright 2005, 2012 jQuery Foundation, Inc. and other contributors
 * Released under the MIT license
 * http://jquery.org/license
 *
 * Date: 2013-2-4
 */
(function( window, undefined ) {

// Can't do this because several apps including ASP.NET trace
// the stack via arguments.caller.callee and Firefox dies if
// you try to trace through "use strict" call chains. (#13335)
// Support: Firefox 18+
//"use strict";
var
    // The deferred used on DOM ready
    readyList,

    // A central reference to the root jQuery(document)
    rootjQuery,

    // Support: IE<9
    // For `typeof node.method` instead of `node.method !== undefined`
    core_strundefined = typeof undefined,

    // Use the correct document accordingly with window argument (sandbox)
    document = window.document,
    location = window.location,

    // Map over jQuery in case of overwrite
    _jQuery = window.jQuery,

    // Map over the $ in case of overwrite
    _$ = window.$,

    // [[Class]] -> type pairs
    class2type = {},

    // List of deleted data cache ids, so we can reuse them
    core_deletedIds = [],

    core_version = "1.9.1",

    // Save a reference to some core methods
    core_concat = core_deletedIds.concat,
    core_push = core_deletedIds.push,
    core_slice = core_deletedIds.slice,
    core_indexOf = core_deletedIds.indexOf,
    core_toString = class2type.toString,
    core_hasOwn = class2type.hasOwnProperty,
    core_trim = core_version.trim,

    // Define a local copy of jQuery
    jQuery = function( selector, context ) {
        // The jQuery object is actually just the init constructor 'enhanced'
        return new jQuery.fn.init( selector, context, rootjQuery );
    },

    // Used for matching numbers
    core_pnum = /[+-]?(?:\d*\.|)\d+(?:[eE][+-]?\d+|)/.source,

    // Used for splitting on whitespace
    core_rnotwhite = /\S+/g,

    // Make sure we trim BOM and NBSP (here's looking at you, Safari 5.0 and IE)
    rtrim = /^[\s\uFEFF\xA0]+|[\s\uFEFF\xA0]+$/g,

    // A simple way to check for HTML strings
    // Prioritize #id over <tag> to avoid XSS via location.hash (#9521)
    // Strict HTML recognition (#11290: must start with <)
    rquickExpr = /^(?:(<[\w\W]+>)[^>]*|#([\w-]*))$/,

    // Match a standalone tag
    rsingleTag = /^<(\w+)\s*\/?>(?:<\/\1>|)$/,

    // JSON RegExp
    rvalidchars = /^[\],:{}\s]*$/,
    rvalidbraces = /(?:^|:|,)(?:\s*\[)+/g,
    rvalidescape = /\\(?:["\\\/bfnrt]|u[\da-fA-F]{4})/g,
    rvalidtokens = /"[^"\\\r\n]*"|true|false|null|-?(?:\d+\.|)\d+(?:[eE][+-]?\d+|)/g,

    // Matches dashed string for camelizing
    rmsPrefix = /^-ms-/,
    rdashAlpha = /-([\da-z])/gi,

    // Used by jQuery.camelCase as callback to replace()
    fcamelCase = function( all, letter ) {
        return letter.toUpperCase();
    },

    // The ready event handler
    completed = function( event ) {

        // readyState === "complete" is good enough for us to call the dom ready in oldIE
        if ( document.addEventListener || event.type === "load" || document.readyState === "complete" ) {
            detach();
            jQuery.ready();
        }
    },
    // Clean-up method for dom ready events
    detach = function() {
        if ( document.addEventListener ) {
            document.removeEventListener( "DOMContentLoaded", completed, false );
            window.removeEventListener( "load", completed, false );

        } else {
            document.detachEvent( "onreadystatechange", completed );
            window.detachEvent( "onload", completed );
        }
    };

jQuery.fn = jQuery.prototype = {
    // The current version of jQuery being used
    jquery: core_version,

    constructor: jQuery,
    init: function( selector, context, rootjQuery ) {
        var match, elem;

        // HANDLE: $(""), $(null), $(undefined), $(false)
        if ( !selector ) {
            return this;
        }

        // Handle HTML strings
        if ( typeof selector === "string" ) {
            if ( selector.charAt(0) === "<" && selector.charAt( selector.length - 1 ) === ">" && selector.length >= 3 ) {
                // Assume that strings that start and end with <> are HTML and skip the regex check
                match = [ null, selector, null ];

            } else {
                match = rquickExpr.exec( selector );
            }

            // Match html or make sure no context is specified for #id
            if ( match && (match[1] || !context) ) {

                // HANDLE: $(html) -> $(array)
                if ( match[1] ) {
                    context = context instanceof jQuery ? context[0] : context;

                    // scripts is true for back-compat
                    jQuery.merge( this, jQuery.parseHTML(
                        match[1],
                        context && context.nodeType ? context.ownerDocument || context : document,
                        true
                    ) );

                    // HANDLE: $(html, props)
                    if ( rsingleTag.test( match[1] ) && jQuery.isPlainObject( context ) ) {
                        for ( match in context ) {
                            // Properties of context are called as methods if possible
                            if ( jQuery.isFunction( this[ match ] ) ) {
                                this[ match ]( context[ match ] );

                            // ...and otherwise set as attributes
                            } else {
                                this.attr( match, context[ match ] );
                            }
                        }
                    }

                    return this;

                // HANDLE: $(#id)
                } else {
                    elem = document.getElementById( match[2] );

                    // Check parentNode to catch when Blackberry 4.6 returns
                    // nodes that are no longer in the document #6963
                    if ( elem && elem.parentNode ) {
                        // Handle the case where IE and Opera return items
                        // by name instead of ID
                        if ( elem.id !== match[2] ) {
                            return rootjQuery.find( selector );
                        }

                        // Otherwise, we inject the element directly into the jQuery object
                        this.length = 1;
                        this[0] = elem;
                    }

                    this.context = document;
                    this.selector = selector;
                    return this;
                }

            // HANDLE: $(expr, $(...))
            } else if ( !context || context.jquery ) {
                return ( context || rootjQuery ).find( selector );

            // HANDLE: $(expr, context)
            // (which is just equivalent to: $(context).find(expr)
            } else {
                return this.constructor( context ).find( selector );
            }

        // HANDLE: $(DOMElement)
        } else if ( selector.nodeType ) {
            this.context = this[0] = selector;
            this.length = 1;
            return this;

        // HANDLE: $(function)
        // Shortcut for document ready
        } else if ( jQuery.isFunction( selector ) ) {
            return rootjQuery.ready( selector );
        }

        if ( selector.selector !== undefined ) {
            this.selector = selector.selector;
            this.context = selector.context;
        }

        return jQuery.makeArray( selector, this );
    },

    // Start with an empty selector
    selector: "",

    // The default length of a jQuery object is 0
    length: 0,

    // The number of elements contained in the matched element set
    size: function() {
        return this.length;
    },

    toArray: function() {
        return core_slice.call( this );
    },

    // Get the Nth element in the matched element set OR
    // Get the whole matched element set as a clean array
    get: function( num ) {
        return num == null ?

            // Return a 'clean' array
            this.toArray() :

            // Return just the object
            ( num < 0 ? this[ this.length + num ] : this[ num ] );
    },

    // Take an array of elements and push it onto the stack
    // (returning the new matched element set)
    pushStack: function( elems ) {

        // Build a new jQuery matched element set
        var ret = jQuery.merge( this.constructor(), elems );

        // Add the old object onto the stack (as a reference)
        ret.prevObject = this;
        ret.context = this.context;

        // Return the newly-formed element set
        return ret;
    },

    // Execute a callback for every element in the matched set.
    // (You can seed the arguments with an array of args, but this is
    // only used internally.)
    each: function( callback, args ) {
        return jQuery.each( this, callback, args );
    },

    ready: function( fn ) {
        // Add the callback
        jQuery.ready.promise().done( fn );

        return this;
    },

    slice: function() {
        return this.pushStack( core_slice.apply( this, arguments ) );
    },

    first: function() {
        return this.eq( 0 );
    },

    last: function() {
        return this.eq( -1 );
    },

    eq: function( i ) {
        var len = this.length,
            j = +i + ( i < 0 ? len : 0 );
        return this.pushStack( j >= 0 && j < len ? [ this[j] ] : [] );
    },

    map: function( callback ) {
        return this.pushStack( jQuery.map(this, function( elem, i ) {
            return callback.call( elem, i, elem );
        }));
    },

    end: function() {
        return this.prevObject || this.constructor(null);
    },

    // For internal use only.
    // Behaves like an Array's method, not like a jQuery method.
    push: core_push,
    sort: [].sort,
    splice: [].splice
};

// Give the init function the jQuery prototype for later instantiation
jQuery.fn.init.prototype = jQuery.fn;

jQuery.extend = jQuery.fn.extend = function() {
    var src, copyIsArray, copy, name, options, clone,
        target = arguments[0] || {},
        i = 1,
        length = arguments.length,
        deep = false;

    // Handle a deep copy situation
    if ( typeof target === "boolean" ) {
        deep = target;
        target = arguments[1] || {};
        // skip the boolean and the target
        i = 2;
    }

    // Handle case when target is a string or something (possible in deep copy)
    if ( typeof target !== "object" && !jQuery.isFunction(target) ) {
        target = {};
    }

    // extend jQuery itself if only one argument is passed
    if ( length === i ) {
        target = this;
        --i;
    }

    for ( ; i < length; i++ ) {
        // Only deal with non-null/undefined values
        if ( (options = arguments[ i ]) != null ) {
            // Extend the base object
            for ( name in options ) {
                src = target[ name ];
                copy = options[ name ];

                // Prevent never-ending loop
                if ( target === copy ) {
                    continue;
                }

                // Recurse if we're merging plain objects or arrays
                if ( deep && copy && ( jQuery.isPlainObject(copy) || (copyIsArray = jQuery.isArray(copy)) ) ) {
                    if ( copyIsArray ) {
                        copyIsArray = false;
                        clone = src && jQuery.isArray(src) ? src : [];

                    } else {
                        clone = src && jQuery.isPlainObject(src) ? src : {};
                    }

                    // Never move original objects, clone them
                    target[ name ] = jQuery.extend( deep, clone, copy );

                // Don't bring in undefined values
                } else if ( copy !== undefined ) {
                    target[ name ] = copy;
                }
            }
        }
    }

    // Return the modified object
    return target;
};

jQuery.extend({
    noConflict: function( deep ) {
        if ( window.$ === jQuery ) {
            window.$ = _$;
        }

        if ( deep && window.jQuery === jQuery ) {
            window.jQuery = _jQuery;
        }

        return jQuery;
    },

    // Is the DOM ready to be used? Set to true once it occurs.
    isReady: false,

    // A counter to track how many items to wait for before
    // the ready event fires. See #6781
    readyWait: 1,

    // Hold (or release) the ready event
    holdReady: function( hold ) {
        if ( hold ) {
            jQuery.readyWait++;
        } else {
            jQuery.ready( true );
        }
    },

    // Handle when the DOM is ready
    ready: function( wait ) {

        // Abort if there are pending holds or we're already ready
        if ( wait === true ? --jQuery.readyWait : jQuery.isReady ) {
            return;
        }

        // Make sure body exists, at least, in case IE gets a little overzealous (ticket #5443).
        if ( !document.body ) {
            return setTimeout( jQuery.ready );
        }

        // Remember that the DOM is ready
        jQuery.isReady = true;

        // If a normal DOM Ready event fired, decrement, and wait if need be
        if ( wait !== true && --jQuery.readyWait > 0 ) {
            return;
        }

        // If there are functions bound, to execute
        readyList.resolveWith( document, [ jQuery ] );

        // Trigger any bound ready events
        if ( jQuery.fn.trigger ) {
            jQuery( document ).trigger("ready").off("ready");
        }
    },

    // See test/unit/core.js for details concerning isFunction.
    // Since version 1.3, DOM methods and functions like alert
    // aren't supported. They return false on IE (#2968).
    isFunction: function( obj ) {
        return jQuery.type(obj) === "function";
    },

    isArray: Array.isArray || function( obj ) {
        return jQuery.type(obj) === "array";
    },

    isWindow: function( obj ) {
        return obj != null && obj == obj.window;
    },

    isNumeric: function( obj ) {
        return !isNaN( parseFloat(obj) ) && isFinite( obj );
    },

    type: function( obj ) {
        if ( obj == null ) {
            return String( obj );
        }
        return typeof obj === "object" || typeof obj === "function" ?
            class2type[ core_toString.call(obj) ] || "object" :
            typeof obj;
    },

    isPlainObject: function( obj ) {
        // Must be an Object.
        // Because of IE, we also have to check the presence of the constructor property.
        // Make sure that DOM nodes and window objects don't pass through, as well
        if ( !obj || jQuery.type(obj) !== "object" || obj.nodeType || jQuery.isWindow( obj ) ) {
            return false;
        }

        try {
            // Not own constructor property must be Object
            if ( obj.constructor &&
                !core_hasOwn.call(obj, "constructor") &&
                !core_hasOwn.call(obj.constructor.prototype, "isPrototypeOf") ) {
                return false;
            }
        } catch ( e ) {
            // IE8,9 Will throw exceptions on certain host objects #9897
            return false;
        }

        // Own properties are enumerated firstly, so to speed up,
        // if last one is own, then all properties are own.

        var key;
        for ( key in obj ) {}

        return key === undefined || core_hasOwn.call( obj, key );
    },

    isEmptyObject: function( obj ) {
        var name;
        for ( name in obj ) {
            return false;
        }
        return true;
    },

    error: function( msg ) {
        throw new Error( msg );
    },

    // data: string of html
    // context (optional): If specified, the fragment will be created in this context, defaults to document
    // keepScripts (optional): If true, will include scripts passed in the html string
    parseHTML: function( data, context, keepScripts ) {
        if ( !data || typeof data !== "string" ) {
            return null;
        }
        if ( typeof context === "boolean" ) {
            keepScripts = context;
            context = false;
        }
        context = context || document;

        var parsed = rsingleTag.exec( data ),
            scripts = !keepScripts && [];

        // Single tag
        if ( parsed ) {
            return [ context.createElement( parsed[1] ) ];
        }

        parsed = jQuery.buildFragment( [ data ], context, scripts );
        if ( scripts ) {
            jQuery( scripts ).remove();
        }
        return jQuery.merge( [], parsed.childNodes );
    },

    parseJSON: function( data ) {
        // Attempt to parse using the native JSON parser first
        if ( window.JSON && window.JSON.parse ) {
            return window.JSON.parse( data );
        }

        if ( data === null ) {
            return data;
        }

        if ( typeof data === "string" ) {

            // Make sure leading/trailing whitespace is removed (IE can't handle it)
            data = jQuery.trim( data );

            if ( data ) {
                // Make sure the incoming data is actual JSON
                // Logic borrowed from http://json.org/json2.js
                if ( rvalidchars.test( data.replace( rvalidescape, "@" )
                    .replace( rvalidtokens, "]" )
                    .replace( rvalidbraces, "")) ) {

                    return ( new Function( "return " + data ) )();
                }
            }
        }

        jQuery.error( "Invalid JSON: " + data );
    },

    // Cross-browser xml parsing
    parseXML: function( data ) {
        var xml, tmp;
        if ( !data || typeof data !== "string" ) {
            return null;
        }
        try {
            if ( window.DOMParser ) { // Standard
                tmp = new DOMParser();
                xml = tmp.parseFromString( data , "text/xml" );
            } else { // IE
                xml = new ActiveXObject( "Microsoft.XMLDOM" );
                xml.async = "false";
                xml.loadXML( data );
            }
        } catch( e ) {
            xml = undefined;
        }
        if ( !xml || !xml.documentElement || xml.getElementsByTagName( "parsererror" ).length ) {
            jQuery.error( "Invalid XML: " + data );
        }
        return xml;
    },

    noop: function() {},

    // Evaluates a script in a global context
    // Workarounds based on findings by Jim Driscoll
    // http://weblogs.java.net/blog/driscoll/archive/2009/09/08/eval-javascript-global-context
    globalEval: function( data ) {
        if ( data && jQuery.trim( data ) ) {
            // We use execScript on Internet Explorer
            // We use an anonymous function so that context is window
            // rather than jQuery in Firefox
            ( window.execScript || function( data ) {
                window[ "eval" ].call( window, data );
            } )( data );
        }
    },

    // Convert dashed to camelCase; used by the css and data modules
    // Microsoft forgot to hump their vendor prefix (#9572)
    camelCase: function( string ) {
        return string.replace( rmsPrefix, "ms-" ).replace( rdashAlpha, fcamelCase );
    },

    nodeName: function( elem, name ) {
        return elem.nodeName && elem.nodeName.toLowerCase() === name.toLowerCase();
    },

    // args is for internal usage only
    each: function( obj, callback, args ) {
        var value,
            i = 0,
            length = obj.length,
            isArray = isArraylike( obj );

        if ( args ) {
            if ( isArray ) {
                for ( ; i < length; i++ ) {
                    value = callback.apply( obj[ i ], args );

                    if ( value === false ) {
                        break;
                    }
                }
            } else {
                for ( i in obj ) {
                    value = callback.apply( obj[ i ], args );

                    if ( value === false ) {
                        break;
                    }
                }
            }

        // A special, fast, case for the most common use of each
        } else {
            if ( isArray ) {
                for ( ; i < length; i++ ) {
                    value = callback.call( obj[ i ], i, obj[ i ] );

                    if ( value === false ) {
                        break;
                    }
                }
            } else {
                for ( i in obj ) {
                    value = callback.call( obj[ i ], i, obj[ i ] );

                    if ( value === false ) {
                        break;
                    }
                }
            }
        }

        return obj;
    },

    // Use native String.trim function wherever possible
    trim: core_trim && !core_trim.call("\uFEFF\xA0") ?
        function( text ) {
            return text == null ?
                "" :
                core_trim.call( text );
        } :

        // Otherwise use our own trimming functionality
        function( text ) {
            return text == null ?
                "" :
                ( text + "" ).replace( rtrim, "" );
        },

    // results is for internal usage only
    makeArray: function( arr, results ) {
        var ret = results || [];

        if ( arr != null ) {
            if ( isArraylike( Object(arr) ) ) {
                jQuery.merge( ret,
                    typeof arr === "string" ?
                    [ arr ] : arr
                );
            } else {
                core_push.call( ret, arr );
            }
        }

        return ret;
    },

    inArray: function( elem, arr, i ) {
        var len;

        if ( arr ) {
            if ( core_indexOf ) {
                return core_indexOf.call( arr, elem, i );
            }

            len = arr.length;
            i = i ? i < 0 ? Math.max( 0, len + i ) : i : 0;

            for ( ; i < len; i++ ) {
                // Skip accessing in sparse arrays
                if ( i in arr && arr[ i ] === elem ) {
                    return i;
                }
            }
        }

        return -1;
    },

    merge: function( first, second ) {
        var l = second.length,
            i = first.length,
            j = 0;

        if ( typeof l === "number" ) {
            for ( ; j < l; j++ ) {
                first[ i++ ] = second[ j ];
            }
        } else {
            while ( second[j] !== undefined ) {
                first[ i++ ] = second[ j++ ];
            }
        }

        first.length = i;

        return first;
    },

    grep: function( elems, callback, inv ) {
        var retVal,
            ret = [],
            i = 0,
            length = elems.length;
        inv = !!inv;

        // Go through the array, only saving the items
        // that pass the validator function
        for ( ; i < length; i++ ) {
            retVal = !!callback( elems[ i ], i );
            if ( inv !== retVal ) {
                ret.push( elems[ i ] );
            }
        }

        return ret;
    },

    // arg is for internal usage only
    map: function( elems, callback, arg ) {
        var value,
            i = 0,
            length = elems.length,
            isArray = isArraylike( elems ),
            ret = [];

        // Go through the array, translating each of the items to their
        if ( isArray ) {
            for ( ; i < length; i++ ) {
                value = callback( elems[ i ], i, arg );

                if ( value != null ) {
                    ret[ ret.length ] = value;
                }
            }

        // Go through every key on the object,
        } else {
            for ( i in elems ) {
                value = callback( elems[ i ], i, arg );

                if ( value != null ) {
                    ret[ ret.length ] = value;
                }
            }
        }

        // Flatten any nested arrays
        return core_concat.apply( [], ret );
    },

    // A global GUID counter for objects
    guid: 1,

    // Bind a function to a context, optionally partially applying any
    // arguments.
    proxy: function( fn, context ) {
        var args, proxy, tmp;

        if ( typeof context === "string" ) {
            tmp = fn[ context ];
            context = fn;
            fn = tmp;
        }

        // Quick check to determine if target is callable, in the spec
        // this throws a TypeError, but we will just return undefined.
        if ( !jQuery.isFunction( fn ) ) {
            return undefined;
        }

        // Simulated bind
        args = core_slice.call( arguments, 2 );
        proxy = function() {
            return fn.apply( context || this, args.concat( core_slice.call( arguments ) ) );
        };

        // Set the guid of unique handler to the same of original handler, so it can be removed
        proxy.guid = fn.guid = fn.guid || jQuery.guid++;

        return proxy;
    },

    // Multifunctional method to get and set values of a collection
    // The value/s can optionally be executed if it's a function
    access: function( elems, fn, key, value, chainable, emptyGet, raw ) {
        var i = 0,
            length = elems.length,
            bulk = key == null;

        // Sets many values
        if ( jQuery.type( key ) === "object" ) {
            chainable = true;
            for ( i in key ) {
                jQuery.access( elems, fn, i, key[i], true, emptyGet, raw );
            }

        // Sets one value
        } else if ( value !== undefined ) {
            chainable = true;

            if ( !jQuery.isFunction( value ) ) {
                raw = true;
            }

            if ( bulk ) {
                // Bulk operations run against the entire set
                if ( raw ) {
                    fn.call( elems, value );
                    fn = null;

                // ...except when executing function values
                } else {
                    bulk = fn;
                    fn = function( elem, key, value ) {
                        return bulk.call( jQuery( elem ), value );
                    };
                }
            }

            if ( fn ) {
                for ( ; i < length; i++ ) {
                    fn( elems[i], key, raw ? value : value.call( elems[i], i, fn( elems[i], key ) ) );
                }
            }
        }

        return chainable ?
            elems :

            // Gets
            bulk ?
                fn.call( elems ) :
                length ? fn( elems[0], key ) : emptyGet;
    },

    now: function() {
        return ( new Date() ).getTime();
    }
});

jQuery.ready.promise = function( obj ) {
    if ( !readyList ) {

        readyList = jQuery.Deferred();

        // Catch cases where $(document).ready() is called after the browser event has already occurred.
        // we once tried to use readyState "interactive" here, but it caused issues like the one
        // discovered by ChrisS here: http://bugs.jquery.com/ticket/12282#comment:15
        if ( document.readyState === "complete" ) {
            // Handle it asynchronously to allow scripts the opportunity to delay ready
            setTimeout( jQuery.ready );

        // Standards-based browsers support DOMContentLoaded
        } else if ( document.addEventListener ) {
            // Use the handy event callback
            document.addEventListener( "DOMContentLoaded", completed, false );

            // A fallback to window.onload, that will always work
            window.addEventListener( "load", completed, false );

        // If IE event model is used
        } else {
            // Ensure firing before onload, maybe late but safe also for iframes
            document.attachEvent( "onreadystatechange", completed );

            // A fallback to window.onload, that will always work
            window.attachEvent( "onload", completed );

            // If IE and not a frame
            // continually check to see if the document is ready
            var top = false;

            try {
                top = window.frameElement == null && document.documentElement;
            } catch(e) {}

            if ( top && top.doScroll ) {
                (function doScrollCheck() {
                    if ( !jQuery.isReady ) {

                        try {
                            // Use the trick by Diego Perini
                            // http://javascript.nwbox.com/IEContentLoaded/
                            top.doScroll("left");
                        } catch(e) {
                            return setTimeout( doScrollCheck, 50 );
                        }

                        // detach all dom ready events
                        detach();

                        // and execute any waiting functions
                        jQuery.ready();
                    }
                })();
            }
        }
    }
    return readyList.promise( obj );
};

// Populate the class2type map
jQuery.each("Boolean Number String Function Array Date RegExp Object Error".split(" "), function(i, name) {
    class2type[ "[object " + name + "]" ] = name.toLowerCase();
});

function isArraylike( obj ) {
    var length = obj.length,
        type = jQuery.type( obj );

    if ( jQuery.isWindow( obj ) ) {
        return false;
    }

    if ( obj.nodeType === 1 && length ) {
        return true;
    }

    return type === "array" || type !== "function" &&
        ( length === 0 ||
        typeof length === "number" && length > 0 && ( length - 1 ) in obj );
}

// All jQuery objects should point back to these
rootjQuery = jQuery(document);
// String to Object options format cache
var optionsCache = {};

// Convert String-formatted options into Object-formatted ones and store in cache
function createOptions( options ) {
    var object = optionsCache[ options ] = {};
    jQuery.each( options.match( core_rnotwhite ) || [], function( _, flag ) {
        object[ flag ] = true;
    });
    return object;
}

/*
 * Create a callback list using the following parameters:
 *
 *  options: an optional list of space-separated options that will change how
 *          the callback list behaves or a more traditional option object
 *
 * By default a callback list will act like an event callback list and can be
 * "fired" multiple times.
 *
 * Possible options:
 *
 *  once:           will ensure the callback list can only be fired once (like a Deferred)
 *
 *  memory:         will keep track of previous values and will call any callback added
 *                  after the list has been fired right away with the latest "memorized"
 *                  values (like a Deferred)
 *
 *  unique:         will ensure a callback can only be added once (no duplicate in the list)
 *
 *  stopOnFalse:    interrupt callings when a callback returns false
 *
 */
jQuery.Callbacks = function( options ) {

    // Convert options from String-formatted to Object-formatted if needed
    // (we check in cache first)
    options = typeof options === "string" ?
        ( optionsCache[ options ] || createOptions( options ) ) :
        jQuery.extend( {}, options );

    var // Flag to know if list is currently firing
        firing,
        // Last fire value (for non-forgettable lists)
        memory,
        // Flag to know if list was already fired
        fired,
        // End of the loop when firing
        firingLength,
        // Index of currently firing callback (modified by remove if needed)
        firingIndex,
        // First callback to fire (used internally by add and fireWith)
        firingStart,
        // Actual callback list
        list = [],
        // Stack of fire calls for repeatable lists
        stack = !options.once && [],
        // Fire callbacks
        fire = function( data ) {
            memory = options.memory && data;
            fired = true;
            firingIndex = firingStart || 0;
            firingStart = 0;
            firingLength = list.length;
            firing = true;
            for ( ; list && firingIndex < firingLength; firingIndex++ ) {
                if ( list[ firingIndex ].apply( data[ 0 ], data[ 1 ] ) === false && options.stopOnFalse ) {
                    memory = false; // To prevent further calls using add
                    break;
                }
            }
            firing = false;
            if ( list ) {
                if ( stack ) {
                    if ( stack.length ) {
                        fire( stack.shift() );
                    }
                } else if ( memory ) {
                    list = [];
                } else {
                    self.disable();
                }
            }
        },
        // Actual Callbacks object
        self = {
            // Add a callback or a collection of callbacks to the list
            add: function() {
                if ( list ) {
                    // First, we save the current length
                    var start = list.length;
                    (function add( args ) {
                        jQuery.each( args, function( _, arg ) {
                            var type = jQuery.type( arg );
                            if ( type === "function" ) {
                                if ( !options.unique || !self.has( arg ) ) {
                                    list.push( arg );
                                }
                            } else if ( arg && arg.length && type !== "string" ) {
                                // Inspect recursively
                                add( arg );
                            }
                        });
                    })( arguments );
                    // Do we need to add the callbacks to the
                    // current firing batch?
                    if ( firing ) {
                        firingLength = list.length;
                    // With memory, if we're not firing then
                    // we should call right away
                    } else if ( memory ) {
                        firingStart = start;
                        fire( memory );
                    }
                }
                return this;
            },
            // Remove a callback from the list
            remove: function() {
                if ( list ) {
                    jQuery.each( arguments, function( _, arg ) {
                        var index;
                        while( ( index = jQuery.inArray( arg, list, index ) ) > -1 ) {
                            list.splice( index, 1 );
                            // Handle firing indexes
                            if ( firing ) {
                                if ( index <= firingLength ) {
                                    firingLength--;
                                }
                                if ( index <= firingIndex ) {
                                    firingIndex--;
                                }
                            }
                        }
                    });
                }
                return this;
            },
            // Check if a given callback is in the list.
            // If no argument is given, return whether or not list has callbacks attached.
            has: function( fn ) {
                return fn ? jQuery.inArray( fn, list ) > -1 : !!( list && list.length );
            },
            // Remove all callbacks from the list
            empty: function() {
                list = [];
                return this;
            },
            // Have the list do nothing anymore
            disable: function() {
                list = stack = memory = undefined;
                return this;
            },
            // Is it disabled?
            disabled: function() {
                return !list;
            },
            // Lock the list in its current state
            lock: function() {
                stack = undefined;
                if ( !memory ) {
                    self.disable();
                }
                return this;
            },
            // Is it locked?
            locked: function() {
                return !stack;
            },
            // Call all callbacks with the given context and arguments
            fireWith: function( context, args ) {
                args = args || [];
                args = [ context, args.slice ? args.slice() : args ];
                if ( list && ( !fired || stack ) ) {
                    if ( firing ) {
                        stack.push( args );
                    } else {
                        fire( args );
                    }
                }
                return this;
            },
            // Call all the callbacks with the given arguments
            fire: function() {
                self.fireWith( this, arguments );
                return this;
            },
            // To know if the callbacks have already been called at least once
            fired: function() {
                return !!fired;
            }
        };

    return self;
};
jQuery.extend({

    Deferred: function( func ) {
        var tuples = [
                // action, add listener, listener list, final state
                [ "resolve", "done", jQuery.Callbacks("once memory"), "resolved" ],
                [ "reject", "fail", jQuery.Callbacks("once memory"), "rejected" ],
                [ "notify", "progress", jQuery.Callbacks("memory") ]
            ],
            state = "pending",
            promise = {
                state: function() {
                    return state;
                },
                always: function() {
                    deferred.done( arguments ).fail( arguments );
                    return this;
                },
                then: function( /* fnDone, fnFail, fnProgress */ ) {
                    var fns = arguments;
                    return jQuery.Deferred(function( newDefer ) {
                        jQuery.each( tuples, function( i, tuple ) {
                            var action = tuple[ 0 ],
                                fn = jQuery.isFunction( fns[ i ] ) && fns[ i ];
                            // deferred[ done | fail | progress ] for forwarding actions to newDefer
                            deferred[ tuple[1] ](function() {
                                var returned = fn && fn.apply( this, arguments );
                                if ( returned && jQuery.isFunction( returned.promise ) ) {
                                    returned.promise()
                                        .done( newDefer.resolve )
                                        .fail( newDefer.reject )
                                        .progress( newDefer.notify );
                                } else {
                                    newDefer[ action + "With" ]( this === promise ? newDefer.promise() : this, fn ? [ returned ] : arguments );
                                }
                            });
                        });
                        fns = null;
                    }).promise();
                },
                // Get a promise for this deferred
                // If obj is provided, the promise aspect is added to the object
                promise: function( obj ) {
                    return obj != null ? jQuery.extend( obj, promise ) : promise;
                }
            },
            deferred = {};

        // Keep pipe for back-compat
        promise.pipe = promise.then;

        // Add list-specific methods
        jQuery.each( tuples, function( i, tuple ) {
            var list = tuple[ 2 ],
                stateString = tuple[ 3 ];

            // promise[ done | fail | progress ] = list.add
            promise[ tuple[1] ] = list.add;

            // Handle state
            if ( stateString ) {
                list.add(function() {
                    // state = [ resolved | rejected ]
                    state = stateString;

                // [ reject_list | resolve_list ].disable; progress_list.lock
                }, tuples[ i ^ 1 ][ 2 ].disable, tuples[ 2 ][ 2 ].lock );
            }

            // deferred[ resolve | reject | notify ]
            deferred[ tuple[0] ] = function() {
                deferred[ tuple[0] + "With" ]( this === deferred ? promise : this, arguments );
                return this;
            };
            deferred[ tuple[0] + "With" ] = list.fireWith;
        });

        // Make the deferred a promise
        promise.promise( deferred );

        // Call given func if any
        if ( func ) {
            func.call( deferred, deferred );
        }

        // All done!
        return deferred;
    },

    // Deferred helper
    when: function( subordinate /* , ..., subordinateN */ ) {
        var i = 0,
            resolveValues = core_slice.call( arguments ),
            length = resolveValues.length,

            // the count of uncompleted subordinates
            remaining = length !== 1 || ( subordinate && jQuery.isFunction( subordinate.promise ) ) ? length : 0,

            // the master Deferred. If resolveValues consist of only a single Deferred, just use that.
            deferred = remaining === 1 ? subordinate : jQuery.Deferred(),

            // Update function for both resolve and progress values
            updateFunc = function( i, contexts, values ) {
                return function( value ) {
                    contexts[ i ] = this;
                    values[ i ] = arguments.length > 1 ? core_slice.call( arguments ) : value;
                    if( values === progressValues ) {
                        deferred.notifyWith( contexts, values );
                    } else if ( !( --remaining ) ) {
                        deferred.resolveWith( contexts, values );
                    }
                };
            },

            progressValues, progressContexts, resolveContexts;

        // add listeners to Deferred subordinates; treat others as resolved
        if ( length > 1 ) {
            progressValues = new Array( length );
            progressContexts = new Array( length );
            resolveContexts = new Array( length );
            for ( ; i < length; i++ ) {
                if ( resolveValues[ i ] && jQuery.isFunction( resolveValues[ i ].promise ) ) {
                    resolveValues[ i ].promise()
                        .done( updateFunc( i, resolveContexts, resolveValues ) )
                        .fail( deferred.reject )
                        .progress( updateFunc( i, progressContexts, progressValues ) );
                } else {
                    --remaining;
                }
            }
        }

        // if we're not waiting on anything, resolve the master
        if ( !remaining ) {
            deferred.resolveWith( resolveContexts, resolveValues );
        }

        return deferred.promise();
    }
});
jQuery.support = (function() {

    var support, all, a,
        input, select, fragment,
        opt, eventName, isSupported, i,
        div = document.createElement("div");

    // Setup
    div.setAttribute( "className", "t" );
    div.innerHTML = "  <link/><table></table><a href='/a'>a</a><input type='checkbox'/>";

    // Support tests won't run in some limited or non-browser environments
    all = div.getElementsByTagName("*");
    a = div.getElementsByTagName("a")[ 0 ];
    if ( !all || !a || !all.length ) {
        return {};
    }

    // First batch of tests
    select = document.createElement("select");
    opt = select.appendChild( document.createElement("option") );
    input = div.getElementsByTagName("input")[ 0 ];

    a.style.cssText = "top:1px;float:left;opacity:.5";
    support = {
        // Test setAttribute on camelCase class. If it works, we need attrFixes when doing get/setAttribute (ie6/7)
        getSetAttribute: div.className !== "t",

        // IE strips leading whitespace when .innerHTML is used
        leadingWhitespace: div.firstChild.nodeType === 3,

        // Make sure that tbody elements aren't automatically inserted
        // IE will insert them into empty tables
        tbody: !div.getElementsByTagName("tbody").length,

        // Make sure that link elements get serialized correctly by innerHTML
        // This requires a wrapper element in IE
        htmlSerialize: !!div.getElementsByTagName("link").length,

        // Get the style information from getAttribute
        // (IE uses .cssText instead)
        style: /top/.test( a.getAttribute("style") ),

        // Make sure that URLs aren't manipulated
        // (IE normalizes it by default)
        hrefNormalized: a.getAttribute("href") === "/a",

        // Make sure that element opacity exists
        // (IE uses filter instead)
        // Use a regex to work around a WebKit issue. See #5145
        opacity: /^0.5/.test( a.style.opacity ),

        // Verify style float existence
        // (IE uses styleFloat instead of cssFloat)
        cssFloat: !!a.style.cssFloat,

        // Check the default checkbox/radio value ("" on WebKit; "on" elsewhere)
        checkOn: !!input.value,

        // Make sure that a selected-by-default option has a working selected property.
        // (WebKit defaults to false instead of true, IE too, if it's in an optgroup)
        optSelected: opt.selected,

        // Tests for enctype support on a form (#6743)
        enctype: !!document.createElement("form").enctype,

        // Makes sure cloning an html5 element does not cause problems
        // Where outerHTML is undefined, this still works
        html5Clone: document.createElement("nav").cloneNode( true ).outerHTML !== "<:nav></:nav>",

        // jQuery.support.boxModel DEPRECATED in 1.8 since we don't support Quirks Mode
        boxModel: document.compatMode === "CSS1Compat",

        // Will be defined later
        deleteExpando: true,
        noCloneEvent: true,
        inlineBlockNeedsLayout: false,
        shrinkWrapBlocks: false,
        reliableMarginRight: true,
        boxSizingReliable: true,
        pixelPosition: false
    };

    // Make sure checked status is properly cloned
    input.checked = true;
    support.noCloneChecked = input.cloneNode( true ).checked;

    // Make sure that the options inside disabled selects aren't marked as disabled
    // (WebKit marks them as disabled)
    select.disabled = true;
    support.optDisabled = !opt.disabled;

    // Support: IE<9
    try {
        delete div.test;
    } catch( e ) {
        support.deleteExpando = false;
    }

    // Check if we can trust getAttribute("value")
    input = document.createElement("input");
    input.setAttribute( "value", "" );
    support.input = input.getAttribute( "value" ) === "";

    // Check if an input maintains its value after becoming a radio
    input.value = "t";
    input.setAttribute( "type", "radio" );
    support.radioValue = input.value === "t";

    // #11217 - WebKit loses check when the name is after the checked attribute
    input.setAttribute( "checked", "t" );
    input.setAttribute( "name", "t" );

    fragment = document.createDocumentFragment();
    fragment.appendChild( input );

    // Check if a disconnected checkbox will retain its checked
    // value of true after appended to the DOM (IE6/7)
    support.appendChecked = input.checked;

    // WebKit doesn't clone checked state correctly in fragments
    support.checkClone = fragment.cloneNode( true ).cloneNode( true ).lastChild.checked;

    // Support: IE<9
    // Opera does not clone events (and typeof div.attachEvent === undefined).
    // IE9-10 clones events bound via attachEvent, but they don't trigger with .click()
    if ( div.attachEvent ) {
        div.attachEvent( "onclick", function() {
            support.noCloneEvent = false;
        });

        div.cloneNode( true ).click();
    }

    // Support: IE<9 (lack submit/change bubble), Firefox 17+ (lack focusin event)
    // Beware of CSP restrictions (https://developer.mozilla.org/en/Security/CSP), test/csp.php
    for ( i in { submit: true, change: true, focusin: true }) {
        div.setAttribute( eventName = "on" + i, "t" );

        support[ i + "Bubbles" ] = eventName in window || div.attributes[ eventName ].expando === false;
    }

    div.style.backgroundClip = "content-box";
    div.cloneNode( true ).style.backgroundClip = "";
    support.clearCloneStyle = div.style.backgroundClip === "content-box";

    // Run tests that need a body at doc ready
    jQuery(function() {
        var container, marginDiv, tds,
            divReset = "padding:0;margin:0;border:0;display:block;box-sizing:content-box;-moz-box-sizing:content-box;-webkit-box-sizing:content-box;",
            body = document.getElementsByTagName("body")[0];

        if ( !body ) {
            // Return for frameset docs that don't have a body
            return;
        }

        container = document.createElement("div");
        container.style.cssText = "border:0;width:0;height:0;position:absolute;top:0;left:-9999px;margin-top:1px";

        body.appendChild( container ).appendChild( div );

        // Support: IE8
        // Check if table cells still have offsetWidth/Height when they are set
        // to display:none and there are still other visible table cells in a
        // table row; if so, offsetWidth/Height are not reliable for use when
        // determining if an element has been hidden directly using
        // display:none (it is still safe to use offsets if a parent element is
        // hidden; don safety goggles and see bug #4512 for more information).
        div.innerHTML = "<table><tr><td></td><td>t</td></tr></table>";
        tds = div.getElementsByTagName("td");
        tds[ 0 ].style.cssText = "padding:0;margin:0;border:0;display:none";
        isSupported = ( tds[ 0 ].offsetHeight === 0 );

        tds[ 0 ].style.display = "";
        tds[ 1 ].style.display = "none";

        // Support: IE8
        // Check if empty table cells still have offsetWidth/Height
        support.reliableHiddenOffsets = isSupported && ( tds[ 0 ].offsetHeight === 0 );

        // Check box-sizing and margin behavior
        div.innerHTML = "";
        div.style.cssText = "box-sizing:border-box;-moz-box-sizing:border-box;-webkit-box-sizing:border-box;padding:1px;border:1px;display:block;width:4px;margin-top:1%;position:absolute;top:1%;";
        support.boxSizing = ( div.offsetWidth === 4 );
        support.doesNotIncludeMarginInBodyOffset = ( body.offsetTop !== 1 );

        // Use window.getComputedStyle because jsdom on node.js will break without it.
        if ( window.getComputedStyle ) {
            support.pixelPosition = ( window.getComputedStyle( div, null ) || {} ).top !== "1%";
            support.boxSizingReliable = ( window.getComputedStyle( div, null ) || { width: "4px" } ).width === "4px";

            // Check if div with explicit width and no margin-right incorrectly
            // gets computed margin-right based on width of container. (#3333)
            // Fails in WebKit before Feb 2011 nightlies
            // WebKit Bug 13343 - getComputedStyle returns wrong value for margin-right
            marginDiv = div.appendChild( document.createElement("div") );
            marginDiv.style.cssText = div.style.cssText = divReset;
            marginDiv.style.marginRight = marginDiv.style.width = "0";
            div.style.width = "1px";

            support.reliableMarginRight =
                !parseFloat( ( window.getComputedStyle( marginDiv, null ) || {} ).marginRight );
        }

        if ( typeof div.style.zoom !== core_strundefined ) {
            // Support: IE<8
            // Check if natively block-level elements act like inline-block
            // elements when setting their display to 'inline' and giving
            // them layout
            div.innerHTML = "";
            div.style.cssText = divReset + "width:1px;padding:1px;display:inline;zoom:1";
            support.inlineBlockNeedsLayout = ( div.offsetWidth === 3 );

            // Support: IE6
            // Check if elements with layout shrink-wrap their children
            div.style.display = "block";
            div.innerHTML = "<div></div>";
            div.firstChild.style.width = "5px";
            support.shrinkWrapBlocks = ( div.offsetWidth !== 3 );

            if ( support.inlineBlockNeedsLayout ) {
                // Prevent IE 6 from affecting layout for positioned elements #11048
                // Prevent IE from shrinking the body in IE 7 mode #12869
                // Support: IE<8
                body.style.zoom = 1;
            }
        }

        body.removeChild( container );

        // Null elements to avoid leaks in IE
        container = div = tds = marginDiv = null;
    });

    // Null elements to avoid leaks in IE
    all = select = fragment = opt = a = input = null;

    return support;
})();

var rbrace = /(?:\{[\s\S]*\}|\[[\s\S]*\])$/,
    rmultiDash = /([A-Z])/g;

function internalData( elem, name, data, pvt /* Internal Use Only */ ){
    if ( !jQuery.acceptData( elem ) ) {
        return;
    }

    var thisCache, ret,
        internalKey = jQuery.expando,
        getByName = typeof name === "string",

        // We have to handle DOM nodes and JS objects differently because IE6-7
        // can't GC object references properly across the DOM-JS boundary
        isNode = elem.nodeType,

        // Only DOM nodes need the global jQuery cache; JS object data is
        // attached directly to the object so GC can occur automatically
        cache = isNode ? jQuery.cache : elem,

        // Only defining an ID for JS objects if its cache already exists allows
        // the code to shortcut on the same path as a DOM node with no cache
        id = isNode ? elem[ internalKey ] : elem[ internalKey ] && internalKey;

    // Avoid doing any more work than we need to when trying to get data on an
    // object that has no data at all
    if ( (!id || !cache[id] || (!pvt && !cache[id].data)) && getByName && data === undefined ) {
        return;
    }

    if ( !id ) {
        // Only DOM nodes need a new unique ID for each element since their data
        // ends up in the global cache
        if ( isNode ) {
            elem[ internalKey ] = id = core_deletedIds.pop() || jQuery.guid++;
        } else {
            id = internalKey;
        }
    }

    if ( !cache[ id ] ) {
        cache[ id ] = {};

        // Avoids exposing jQuery metadata on plain JS objects when the object
        // is serialized using JSON.stringify
        if ( !isNode ) {
            cache[ id ].toJSON = jQuery.noop;
        }
    }

    // An object can be passed to jQuery.data instead of a key/value pair; this gets
    // shallow copied over onto the existing cache
    if ( typeof name === "object" || typeof name === "function" ) {
        if ( pvt ) {
            cache[ id ] = jQuery.extend( cache[ id ], name );
        } else {
            cache[ id ].data = jQuery.extend( cache[ id ].data, name );
        }
    }

    thisCache = cache[ id ];

    // jQuery data() is stored in a separate object inside the object's internal data
    // cache in order to avoid key collisions between internal data and user-defined
    // data.
    if ( !pvt ) {
        if ( !thisCache.data ) {
            thisCache.data = {};
        }

        thisCache = thisCache.data;
    }

    if ( data !== undefined ) {
        thisCache[ jQuery.camelCase( name ) ] = data;
    }

    // Check for both converted-to-camel and non-converted data property names
    // If a data property was specified
    if ( getByName ) {

        // First Try to find as-is property data
        ret = thisCache[ name ];

        // Test for null|undefined property data
        if ( ret == null ) {

            // Try to find the camelCased property
            ret = thisCache[ jQuery.camelCase( name ) ];
        }
    } else {
        ret = thisCache;
    }

    return ret;
}

function internalRemoveData( elem, name, pvt ) {
    if ( !jQuery.acceptData( elem ) ) {
        return;
    }

    var i, l, thisCache,
        isNode = elem.nodeType,

        // See jQuery.data for more information
        cache = isNode ? jQuery.cache : elem,
        id = isNode ? elem[ jQuery.expando ] : jQuery.expando;

    // If there is already no cache entry for this object, there is no
    // purpose in continuing
    if ( !cache[ id ] ) {
        return;
    }

    if ( name ) {

        thisCache = pvt ? cache[ id ] : cache[ id ].data;

        if ( thisCache ) {

            // Support array or space separated string names for data keys
            if ( !jQuery.isArray( name ) ) {

                // try the string as a key before any manipulation
                if ( name in thisCache ) {
                    name = [ name ];
                } else {

                    // split the camel cased version by spaces unless a key with the spaces exists
                    name = jQuery.camelCase( name );
                    if ( name in thisCache ) {
                        name = [ name ];
                    } else {
                        name = name.split(" ");
                    }
                }
            } else {
                // If "name" is an array of keys...
                // When data is initially created, via ("key", "val") signature,
                // keys will be converted to camelCase.
                // Since there is no way to tell _how_ a key was added, remove
                // both plain key and camelCase key. #12786
                // This will only penalize the array argument path.
                name = name.concat( jQuery.map( name, jQuery.camelCase ) );
            }

            for ( i = 0, l = name.length; i < l; i++ ) {
                delete thisCache[ name[i] ];
            }

            // If there is no data left in the cache, we want to continue
            // and let the cache object itself get destroyed
            if ( !( pvt ? isEmptyDataObject : jQuery.isEmptyObject )( thisCache ) ) {
                return;
            }
        }
    }

    // See jQuery.data for more information
    if ( !pvt ) {
        delete cache[ id ].data;

        // Don't destroy the parent cache unless the internal data object
        // had been the only thing left in it
        if ( !isEmptyDataObject( cache[ id ] ) ) {
            return;
        }
    }

    // Destroy the cache
    if ( isNode ) {
        jQuery.cleanData( [ elem ], true );

    // Use delete when supported for expandos or `cache` is not a window per isWindow (#10080)
    } else if ( jQuery.support.deleteExpando || cache != cache.window ) {
        delete cache[ id ];

    // When all else fails, null
    } else {
        cache[ id ] = null;
    }
}

jQuery.extend({
    cache: {},

    // Unique for each copy of jQuery on the page
    // Non-digits removed to match rinlinejQuery
    expando: "jQuery" + ( core_version + Math.random() ).replace( /\D/g, "" ),

    // The following elements throw uncatchable exceptions if you
    // attempt to add expando properties to them.
    noData: {
        "embed": true,
        // Ban all objects except for Flash (which handle expandos)
        "object": "clsid:D27CDB6E-AE6D-11cf-96B8-444553540000",
        "applet": true
    },

    hasData: function( elem ) {
        elem = elem.nodeType ? jQuery.cache[ elem[jQuery.expando] ] : elem[ jQuery.expando ];
        return !!elem && !isEmptyDataObject( elem );
    },

    data: function( elem, name, data ) {
        return internalData( elem, name, data );
    },

    removeData: function( elem, name ) {
        return internalRemoveData( elem, name );
    },

    // For internal use only.
    _data: function( elem, name, data ) {
        return internalData( elem, name, data, true );
    },

    _removeData: function( elem, name ) {
        return internalRemoveData( elem, name, true );
    },

    // A method for determining if a DOM node can handle the data expando
    acceptData: function( elem ) {
        // Do not set data on non-element because it will not be cleared (#8335).
        if ( elem.nodeType && elem.nodeType !== 1 && elem.nodeType !== 9 ) {
            return false;
        }

        var noData = elem.nodeName && jQuery.noData[ elem.nodeName.toLowerCase() ];

        // nodes accept data unless otherwise specified; rejection can be conditional
        return !noData || noData !== true && elem.getAttribute("classid") === noData;
    }
});

jQuery.fn.extend({
    data: function( key, value ) {
        var attrs, name,
            elem = this[0],
            i = 0,
            data = null;

        // Gets all values
        if ( key === undefined ) {
            if ( this.length ) {
                data = jQuery.data( elem );

                if ( elem.nodeType === 1 && !jQuery._data( elem, "parsedAttrs" ) ) {
                    attrs = elem.attributes;
                    for ( ; i < attrs.length; i++ ) {
                        name = attrs[i].name;

                        if ( !name.indexOf( "data-" ) ) {
                            name = jQuery.camelCase( name.slice(5) );

                            dataAttr( elem, name, data[ name ] );
                        }
                    }
                    jQuery._data( elem, "parsedAttrs", true );
                }
            }

            return data;
        }

        // Sets multiple values
        if ( typeof key === "object" ) {
            return this.each(function() {
                jQuery.data( this, key );
            });
        }

        return jQuery.access( this, function( value ) {

            if ( value === undefined ) {
                // Try to fetch any internally stored data first
                return elem ? dataAttr( elem, key, jQuery.data( elem, key ) ) : null;
            }

            this.each(function() {
                jQuery.data( this, key, value );
            });
        }, null, value, arguments.length > 1, null, true );
    },

    removeData: function( key ) {
        return this.each(function() {
            jQuery.removeData( this, key );
        });
    }
});

function dataAttr( elem, key, data ) {
    // If nothing was found internally, try to fetch any
    // data from the HTML5 data-* attribute
    if ( data === undefined && elem.nodeType === 1 ) {

        var name = "data-" + key.replace( rmultiDash, "-$1" ).toLowerCase();

        data = elem.getAttribute( name );

        if ( typeof data === "string" ) {
            try {
                data = data === "true" ? true :
                    data === "false" ? false :
                    data === "null" ? null :
                    // Only convert to a number if it doesn't change the string
                    +data + "" === data ? +data :
                    rbrace.test( data ) ? jQuery.parseJSON( data ) :
                        data;
            } catch( e ) {}

            // Make sure we set the data so it isn't changed later
            jQuery.data( elem, key, data );

        } else {
            data = undefined;
        }
    }

    return data;
}

// checks a cache object for emptiness
function isEmptyDataObject( obj ) {
    var name;
    for ( name in obj ) {

        // if the public data object is empty, the private is still empty
        if ( name === "data" && jQuery.isEmptyObject( obj[name] ) ) {
            continue;
        }
        if ( name !== "toJSON" ) {
            return false;
        }
    }

    return true;
}
jQuery.extend({
    queue: function( elem, type, data ) {
        var queue;

        if ( elem ) {
            type = ( type || "fx" ) + "queue";
            queue = jQuery._data( elem, type );

            // Speed up dequeue by getting out quickly if this is just a lookup
            if ( data ) {
                if ( !queue || jQuery.isArray(data) ) {
                    queue = jQuery._data( elem, type, jQuery.makeArray(data) );
                } else {
                    queue.push( data );
                }
            }
            return queue || [];
        }
    },

    dequeue: function( elem, type ) {
        type = type || "fx";

        var queue = jQuery.queue( elem, type ),
            startLength = queue.length,
            fn = queue.shift(),
            hooks = jQuery._queueHooks( elem, type ),
            next = function() {
                jQuery.dequeue( elem, type );
            };

        // If the fx queue is dequeued, always remove the progress sentinel
        if ( fn === "inprogress" ) {
            fn = queue.shift();
            startLength--;
        }

        hooks.cur = fn;
        if ( fn ) {

            // Add a progress sentinel to prevent the fx queue from being
            // automatically dequeued
            if ( type === "fx" ) {
                queue.unshift( "inprogress" );
            }

            // clear up the last queue stop function
            delete hooks.stop;
            fn.call( elem, next, hooks );
        }

        if ( !startLength && hooks ) {
            hooks.empty.fire();
        }
    },

    // not intended for public consumption - generates a queueHooks object, or returns the current one
    _queueHooks: function( elem, type ) {
        var key = type + "queueHooks";
        return jQuery._data( elem, key ) || jQuery._data( elem, key, {
            empty: jQuery.Callbacks("once memory").add(function() {
                jQuery._removeData( elem, type + "queue" );
                jQuery._removeData( elem, key );
            })
        });
    }
});

jQuery.fn.extend({
    queue: function( type, data ) {
        var setter = 2;

        if ( typeof type !== "string" ) {
            data = type;
            type = "fx";
            setter--;
        }

        if ( arguments.length < setter ) {
            return jQuery.queue( this[0], type );
        }

        return data === undefined ?
            this :
            this.each(function() {
                var queue = jQuery.queue( this, type, data );

                // ensure a hooks for this queue
                jQuery._queueHooks( this, type );

                if ( type === "fx" && queue[0] !== "inprogress" ) {
                    jQuery.dequeue( this, type );
                }
            });
    },
    dequeue: function( type ) {
        return this.each(function() {
            jQuery.dequeue( this, type );
        });
    },
    // Based off of the plugin by Clint Helfers, with permission.
    // http://blindsignals.com/index.php/2009/07/jquery-delay/
    delay: function( time, type ) {
        time = jQuery.fx ? jQuery.fx.speeds[ time ] || time : time;
        type = type || "fx";

        return this.queue( type, function( next, hooks ) {
            var timeout = setTimeout( next, time );
            hooks.stop = function() {
                clearTimeout( timeout );
            };
        });
    },
    clearQueue: function( type ) {
        return this.queue( type || "fx", [] );
    },
    // Get a promise resolved when queues of a certain type
    // are emptied (fx is the type by default)
    promise: function( type, obj ) {
        var tmp,
            count = 1,
            defer = jQuery.Deferred(),
            elements = this,
            i = this.length,
            resolve = function() {
                if ( !( --count ) ) {
                    defer.resolveWith( elements, [ elements ] );
                }
            };

        if ( typeof type !== "string" ) {
            obj = type;
            type = undefined;
        }
        type = type || "fx";

        while( i-- ) {
            tmp = jQuery._data( elements[ i ], type + "queueHooks" );
            if ( tmp && tmp.empty ) {
                count++;
                tmp.empty.add( resolve );
            }
        }
        resolve();
        return defer.promise( obj );
    }
});
var nodeHook, boolHook,
    rclass = /[\t\r\n]/g,
    rreturn = /\r/g,
    rfocusable = /^(?:input|select|textarea|button|object)$/i,
    rclickable = /^(?:a|area)$/i,
    rboolean = /^(?:checked|selected|autofocus|autoplay|async|controls|defer|disabled|hidden|loop|multiple|open|readonly|required|scoped)$/i,
    ruseDefault = /^(?:checked|selected)$/i,
    getSetAttribute = jQuery.support.getSetAttribute,
    getSetInput = jQuery.support.input;

jQuery.fn.extend({
    attr: function( name, value ) {
        return jQuery.access( this, jQuery.attr, name, value, arguments.length > 1 );
    },

    removeAttr: function( name ) {
        return this.each(function() {
            jQuery.removeAttr( this, name );
        });
    },

    prop: function( name, value ) {
        return jQuery.access( this, jQuery.prop, name, value, arguments.length > 1 );
    },

    removeProp: function( name ) {
        name = jQuery.propFix[ name ] || name;
        return this.each(function() {
            // try/catch handles cases where IE balks (such as removing a property on window)
            try {
                this[ name ] = undefined;
                delete this[ name ];
            } catch( e ) {}
        });
    },

    addClass: function( value ) {
        var classes, elem, cur, clazz, j,
            i = 0,
            len = this.length,
            proceed = typeof value === "string" && value;

        if ( jQuery.isFunction( value ) ) {
            return this.each(function( j ) {
                jQuery( this ).addClass( value.call( this, j, this.className ) );
            });
        }

        if ( proceed ) {
            // The disjunction here is for better compressibility (see removeClass)
            classes = ( value || "" ).match( core_rnotwhite ) || [];

            for ( ; i < len; i++ ) {
                elem = this[ i ];
                cur = elem.nodeType === 1 && ( elem.className ?
                    ( " " + elem.className + " " ).replace( rclass, " " ) :
                    " "
                );

                if ( cur ) {
                    j = 0;
                    while ( (clazz = classes[j++]) ) {
                        if ( cur.indexOf( " " + clazz + " " ) < 0 ) {
                            cur += clazz + " ";
                        }
                    }
                    elem.className = jQuery.trim( cur );

                }
            }
        }

        return this;
    },

    removeClass: function( value ) {
        var classes, elem, cur, clazz, j,
            i = 0,
            len = this.length,
            proceed = arguments.length === 0 || typeof value === "string" && value;

        if ( jQuery.isFunction( value ) ) {
            return this.each(function( j ) {
                jQuery( this ).removeClass( value.call( this, j, this.className ) );
            });
        }
        if ( proceed ) {
            classes = ( value || "" ).match( core_rnotwhite ) || [];

            for ( ; i < len; i++ ) {
                elem = this[ i ];
                // This expression is here for better compressibility (see addClass)
                cur = elem.nodeType === 1 && ( elem.className ?
                    ( " " + elem.className + " " ).replace( rclass, " " ) :
                    ""
                );

                if ( cur ) {
                    j = 0;
                    while ( (clazz = classes[j++]) ) {
                        // Remove *all* instances
                        while ( cur.indexOf( " " + clazz + " " ) >= 0 ) {
                            cur = cur.replace( " " + clazz + " ", " " );
                        }
                    }
                    elem.className = value ? jQuery.trim( cur ) : "";
                }
            }
        }

        return this;
    },

    toggleClass: function( value, stateVal ) {
        var type = typeof value,
            isBool = typeof stateVal === "boolean";

        if ( jQuery.isFunction( value ) ) {
            return this.each(function( i ) {
                jQuery( this ).toggleClass( value.call(this, i, this.className, stateVal), stateVal );
            });
        }

        return this.each(function() {
            if ( type === "string" ) {
                // toggle individual class names
                var className,
                    i = 0,
                    self = jQuery( this ),
                    state = stateVal,
                    classNames = value.match( core_rnotwhite ) || [];

                while ( (className = classNames[ i++ ]) ) {
                    // check each className given, space separated list
                    state = isBool ? state : !self.hasClass( className );
                    self[ state ? "addClass" : "removeClass" ]( className );
                }

            // Toggle whole class name
            } else if ( type === core_strundefined || type === "boolean" ) {
                if ( this.className ) {
                    // store className if set
                    jQuery._data( this, "__className__", this.className );
                }

                // If the element has a class name or if we're passed "false",
                // then remove the whole classname (if there was one, the above saved it).
                // Otherwise bring back whatever was previously saved (if anything),
                // falling back to the empty string if nothing was stored.
                this.className = this.className || value === false ? "" : jQuery._data( this, "__className__" ) || "";
            }
        });
    },

    hasClass: function( selector ) {
        var className = " " + selector + " ",
            i = 0,
            l = this.length;
        for ( ; i < l; i++ ) {
            if ( this[i].nodeType === 1 && (" " + this[i].className + " ").replace(rclass, " ").indexOf( className ) >= 0 ) {
                return true;
            }
        }

        return false;
    },

    val: function( value ) {
        var ret, hooks, isFunction,
            elem = this[0];

        if ( !arguments.length ) {
            if ( elem ) {
                hooks = jQuery.valHooks[ elem.type ] || jQuery.valHooks[ elem.nodeName.toLowerCase() ];

                if ( hooks && "get" in hooks && (ret = hooks.get( elem, "value" )) !== undefined ) {
                    return ret;
                }

                ret = elem.value;

                return typeof ret === "string" ?
                    // handle most common string cases
                    ret.replace(rreturn, "") :
                    // handle cases where value is null/undef or number
                    ret == null ? "" : ret;
            }

            return;
        }

        isFunction = jQuery.isFunction( value );

        return this.each(function( i ) {
            var val,
                self = jQuery(this);

            if ( this.nodeType !== 1 ) {
                return;
            }

            if ( isFunction ) {
                val = value.call( this, i, self.val() );
            } else {
                val = value;
            }

            // Treat null/undefined as ""; convert numbers to string
            if ( val == null ) {
                val = "";
            } else if ( typeof val === "number" ) {
                val += "";
            } else if ( jQuery.isArray( val ) ) {
                val = jQuery.map(val, function ( value ) {
                    return value == null ? "" : value + "";
                });
            }

            hooks = jQuery.valHooks[ this.type ] || jQuery.valHooks[ this.nodeName.toLowerCase() ];

            // If set returns undefined, fall back to normal setting
            if ( !hooks || !("set" in hooks) || hooks.set( this, val, "value" ) === undefined ) {
                this.value = val;
            }
        });
    }
});

jQuery.extend({
    valHooks: {
        option: {
            get: function( elem ) {
                // attributes.value is undefined in Blackberry 4.7 but
                // uses .value. See #6932
                var val = elem.attributes.value;
                return !val || val.specified ? elem.value : elem.text;
            }
        },
        select: {
            get: function( elem ) {
                var value, option,
                    options = elem.options,
                    index = elem.selectedIndex,
                    one = elem.type === "select-one" || index < 0,
                    values = one ? null : [],
                    max = one ? index + 1 : options.length,
                    i = index < 0 ?
                        max :
                        one ? index : 0;

                // Loop through all the selected options
                for ( ; i < max; i++ ) {
                    option = options[ i ];

                    // oldIE doesn't update selected after form reset (#2551)
                    if ( ( option.selected || i === index ) &&
                            // Don't return options that are disabled or in a disabled optgroup
                            ( jQuery.support.optDisabled ? !option.disabled : option.getAttribute("disabled") === null ) &&
                            ( !option.parentNode.disabled || !jQuery.nodeName( option.parentNode, "optgroup" ) ) ) {

                        // Get the specific value for the option
                        value = jQuery( option ).val();

                        // We don't need an array for one selects
                        if ( one ) {
                            return value;
                        }

                        // Multi-Selects return an array
                        values.push( value );
                    }
                }

                return values;
            },

            set: function( elem, value ) {
                var values = jQuery.makeArray( value );

                jQuery(elem).find("option").each(function() {
                    this.selected = jQuery.inArray( jQuery(this).val(), values ) >= 0;
                });

                if ( !values.length ) {
                    elem.selectedIndex = -1;
                }
                return values;
            }
        }
    },

    attr: function( elem, name, value ) {
        var hooks, notxml, ret,
            nType = elem.nodeType;

        // don't get/set attributes on text, comment and attribute nodes
        if ( !elem || nType === 3 || nType === 8 || nType === 2 ) {
            return;
        }

        // Fallback to prop when attributes are not supported
        if ( typeof elem.getAttribute === core_strundefined ) {
            return jQuery.prop( elem, name, value );
        }

        notxml = nType !== 1 || !jQuery.isXMLDoc( elem );

        // All attributes are lowercase
        // Grab necessary hook if one is defined
        if ( notxml ) {
            name = name.toLowerCase();
            hooks = jQuery.attrHooks[ name ] || ( rboolean.test( name ) ? boolHook : nodeHook );
        }

        if ( value !== undefined ) {

            if ( value === null ) {
                jQuery.removeAttr( elem, name );

            } else if ( hooks && notxml && "set" in hooks && (ret = hooks.set( elem, value, name )) !== undefined ) {
                return ret;

            } else {
                elem.setAttribute( name, value + "" );
                return value;
            }

        } else if ( hooks && notxml && "get" in hooks && (ret = hooks.get( elem, name )) !== null ) {
            return ret;

        } else {

            // In IE9+, Flash objects don't have .getAttribute (#12945)
            // Support: IE9+
            if ( typeof elem.getAttribute !== core_strundefined ) {
                ret =  elem.getAttribute( name );
            }

            // Non-existent attributes return null, we normalize to undefined
            return ret == null ?
                undefined :
                ret;
        }
    },

    removeAttr: function( elem, value ) {
        var name, propName,
            i = 0,
            attrNames = value && value.match( core_rnotwhite );

        if ( attrNames && elem.nodeType === 1 ) {
            while ( (name = attrNames[i++]) ) {
                propName = jQuery.propFix[ name ] || name;

                // Boolean attributes get special treatment (#10870)
                if ( rboolean.test( name ) ) {
                    // Set corresponding property to false for boolean attributes
                    // Also clear defaultChecked/defaultSelected (if appropriate) for IE<8
                    if ( !getSetAttribute && ruseDefault.test( name ) ) {
                        elem[ jQuery.camelCase( "default-" + name ) ] =
                            elem[ propName ] = false;
                    } else {
                        elem[ propName ] = false;
                    }

                // See #9699 for explanation of this approach (setting first, then removal)
                } else {
                    jQuery.attr( elem, name, "" );
                }

                elem.removeAttribute( getSetAttribute ? name : propName );
            }
        }
    },

    attrHooks: {
        type: {
            set: function( elem, value ) {
                if ( !jQuery.support.radioValue && value === "radio" && jQuery.nodeName(elem, "input") ) {
                    // Setting the type on a radio button after the value resets the value in IE6-9
                    // Reset value to default in case type is set after value during creation
                    var val = elem.value;
                    elem.setAttribute( "type", value );
                    if ( val ) {
                        elem.value = val;
                    }
                    return value;
                }
            }
        }
    },

    propFix: {
        tabindex: "tabIndex",
        readonly: "readOnly",
        "for": "htmlFor",
        "class": "className",
        maxlength: "maxLength",
        cellspacing: "cellSpacing",
        cellpadding: "cellPadding",
        rowspan: "rowSpan",
        colspan: "colSpan",
        usemap: "useMap",
        frameborder: "frameBorder",
        contenteditable: "contentEditable"
    },

    prop: function( elem, name, value ) {
        var ret, hooks, notxml,
            nType = elem.nodeType;

        // don't get/set properties on text, comment and attribute nodes
        if ( !elem || nType === 3 || nType === 8 || nType === 2 ) {
            return;
        }

        notxml = nType !== 1 || !jQuery.isXMLDoc( elem );

        if ( notxml ) {
            // Fix name and attach hooks
            name = jQuery.propFix[ name ] || name;
            hooks = jQuery.propHooks[ name ];
        }

        if ( value !== undefined ) {
            if ( hooks && "set" in hooks && (ret = hooks.set( elem, value, name )) !== undefined ) {
                return ret;

            } else {
                return ( elem[ name ] = value );
            }

        } else {
            if ( hooks && "get" in hooks && (ret = hooks.get( elem, name )) !== null ) {
                return ret;

            } else {
                return elem[ name ];
            }
        }
    },

    propHooks: {
        tabIndex: {
            get: function( elem ) {
                // elem.tabIndex doesn't always return the correct value when it hasn't been explicitly set
                // http://fluidproject.org/blog/2008/01/09/getting-setting-and-removing-tabindex-values-with-javascript/
                var attributeNode = elem.getAttributeNode("tabindex");

                return attributeNode && attributeNode.specified ?
                    parseInt( attributeNode.value, 10 ) :
                    rfocusable.test( elem.nodeName ) || rclickable.test( elem.nodeName ) && elem.href ?
                        0 :
                        undefined;
            }
        }
    }
});

// Hook for boolean attributes
boolHook = {
    get: function( elem, name ) {
        var
            // Use .prop to determine if this attribute is understood as boolean
            prop = jQuery.prop( elem, name ),

            // Fetch it accordingly
            attr = typeof prop === "boolean" && elem.getAttribute( name ),
            detail = typeof prop === "boolean" ?

                getSetInput && getSetAttribute ?
                    attr != null :
                    // oldIE fabricates an empty string for missing boolean attributes
                    // and conflates checked/selected into attroperties
                    ruseDefault.test( name ) ?
                        elem[ jQuery.camelCase( "default-" + name ) ] :
                        !!attr :

                // fetch an attribute node for properties not recognized as boolean
                elem.getAttributeNode( name );

        return detail && detail.value !== false ?
            name.toLowerCase() :
            undefined;
    },
    set: function( elem, value, name ) {
        if ( value === false ) {
            // Remove boolean attributes when set to false
            jQuery.removeAttr( elem, name );
        } else if ( getSetInput && getSetAttribute || !ruseDefault.test( name ) ) {
            // IE<8 needs the *property* name
            elem.setAttribute( !getSetAttribute && jQuery.propFix[ name ] || name, name );

        // Use defaultChecked and defaultSelected for oldIE
        } else {
            elem[ jQuery.camelCase( "default-" + name ) ] = elem[ name ] = true;
        }

        return name;
    }
};

// fix oldIE value attroperty
if ( !getSetInput || !getSetAttribute ) {
    jQuery.attrHooks.value = {
        get: function( elem, name ) {
            var ret = elem.getAttributeNode( name );
            return jQuery.nodeName( elem, "input" ) ?

                // Ignore the value *property* by using defaultValue
                elem.defaultValue :

                ret && ret.specified ? ret.value : undefined;
        },
        set: function( elem, value, name ) {
            if ( jQuery.nodeName( elem, "input" ) ) {
                // Does not return so that setAttribute is also used
                elem.defaultValue = value;
            } else {
                // Use nodeHook if defined (#1954); otherwise setAttribute is fine
                return nodeHook && nodeHook.set( elem, value, name );
            }
        }
    };
}

// IE6/7 do not support getting/setting some attributes with get/setAttribute
if ( !getSetAttribute ) {

    // Use this for any attribute in IE6/7
    // This fixes almost every IE6/7 issue
    nodeHook = jQuery.valHooks.button = {
        get: function( elem, name ) {
            var ret = elem.getAttributeNode( name );
            return ret && ( name === "id" || name === "name" || name === "coords" ? ret.value !== "" : ret.specified ) ?
                ret.value :
                undefined;
        },
        set: function( elem, value, name ) {
            // Set the existing or create a new attribute node
            var ret = elem.getAttributeNode( name );
            if ( !ret ) {
                elem.setAttributeNode(
                    (ret = elem.ownerDocument.createAttribute( name ))
                );
            }

            ret.value = value += "";

            // Break association with cloned elements by also using setAttribute (#9646)
            return name === "value" || value === elem.getAttribute( name ) ?
                value :
                undefined;
        }
    };

    // Set contenteditable to false on removals(#10429)
    // Setting to empty string throws an error as an invalid value
    jQuery.attrHooks.contenteditable = {
        get: nodeHook.get,
        set: function( elem, value, name ) {
            nodeHook.set( elem, value === "" ? false : value, name );
        }
    };

    // Set width and height to auto instead of 0 on empty string( Bug #8150 )
    // This is for removals
    jQuery.each([ "width", "height" ], function( i, name ) {
        jQuery.attrHooks[ name ] = jQuery.extend( jQuery.attrHooks[ name ], {
            set: function( elem, value ) {
                if ( value === "" ) {
                    elem.setAttribute( name, "auto" );
                    return value;
                }
            }
        });
    });
}


// Some attributes require a special call on IE
// http://msdn.microsoft.com/en-us/library/ms536429%28VS.85%29.aspx
if ( !jQuery.support.hrefNormalized ) {
    jQuery.each([ "href", "src", "width", "height" ], function( i, name ) {
        jQuery.attrHooks[ name ] = jQuery.extend( jQuery.attrHooks[ name ], {
            get: function( elem ) {
                var ret = elem.getAttribute( name, 2 );
                return ret == null ? undefined : ret;
            }
        });
    });

    // href/src property should get the full normalized URL (#10299/#12915)
    jQuery.each([ "href", "src" ], function( i, name ) {
        jQuery.propHooks[ name ] = {
            get: function( elem ) {
                return elem.getAttribute( name, 4 );
            }
        };
    });
}

if ( !jQuery.support.style ) {
    jQuery.attrHooks.style = {
        get: function( elem ) {
            // Return undefined in the case of empty string
            // Note: IE uppercases css property names, but if we were to .toLowerCase()
            // .cssText, that would destroy case senstitivity in URL's, like in "background"
            return elem.style.cssText || undefined;
        },
        set: function( elem, value ) {
            return ( elem.style.cssText = value + "" );
        }
    };
}

// Safari mis-reports the default selected property of an option
// Accessing the parent's selectedIndex property fixes it
if ( !jQuery.support.optSelected ) {
    jQuery.propHooks.selected = jQuery.extend( jQuery.propHooks.selected, {
        get: function( elem ) {
            var parent = elem.parentNode;

            if ( parent ) {
                parent.selectedIndex;

                // Make sure that it also works with optgroups, see #5701
                if ( parent.parentNode ) {
                    parent.parentNode.selectedIndex;
                }
            }
            return null;
        }
    });
}

// IE6/7 call enctype encoding
if ( !jQuery.support.enctype ) {
    jQuery.propFix.enctype = "encoding";
}

// Radios and checkboxes getter/setter
if ( !jQuery.support.checkOn ) {
    jQuery.each([ "radio", "checkbox" ], function() {
        jQuery.valHooks[ this ] = {
            get: function( elem ) {
                // Handle the case where in Webkit "" is returned instead of "on" if a value isn't specified
                return elem.getAttribute("value") === null ? "on" : elem.value;
            }
        };
    });
}
jQuery.each([ "radio", "checkbox" ], function() {
    jQuery.valHooks[ this ] = jQuery.extend( jQuery.valHooks[ this ], {
        set: function( elem, value ) {
            if ( jQuery.isArray( value ) ) {
                return ( elem.checked = jQuery.inArray( jQuery(elem).val(), value ) >= 0 );
            }
        }
    });
});
var rformElems = /^(?:input|select|textarea)$/i,
    rkeyEvent = /^key/,
    rmouseEvent = /^(?:mouse|contextmenu)|click/,
    rfocusMorph = /^(?:focusinfocus|focusoutblur)$/,
    rtypenamespace = /^([^.]*)(?:\.(.+)|)$/;

function returnTrue() {
    return true;
}

function returnFalse() {
    return false;
}

/*
 * Helper functions for managing events -- not part of the public interface.
 * Props to Dean Edwards' addEvent library for many of the ideas.
 */
jQuery.event = {

    global: {},

    add: function( elem, types, handler, data, selector ) {
        var tmp, events, t, handleObjIn,
            special, eventHandle, handleObj,
            handlers, type, namespaces, origType,
            elemData = jQuery._data( elem );

        // Don't attach events to noData or text/comment nodes (but allow plain objects)
        if ( !elemData ) {
            return;
        }

        // Caller can pass in an object of custom data in lieu of the handler
        if ( handler.handler ) {
            handleObjIn = handler;
            handler = handleObjIn.handler;
            selector = handleObjIn.selector;
        }

        // Make sure that the handler has a unique ID, used to find/remove it later
        if ( !handler.guid ) {
            handler.guid = jQuery.guid++;
        }

        // Init the element's event structure and main handler, if this is the first
        if ( !(events = elemData.events) ) {
            events = elemData.events = {};
        }
        if ( !(eventHandle = elemData.handle) ) {
            eventHandle = elemData.handle = function( e ) {
                // Discard the second event of a jQuery.event.trigger() and
                // when an event is called after a page has unloaded
                return typeof jQuery !== core_strundefined && (!e || jQuery.event.triggered !== e.type) ?
                    jQuery.event.dispatch.apply( eventHandle.elem, arguments ) :
                    undefined;
            };
            // Add elem as a property of the handle fn to prevent a memory leak with IE non-native events
            eventHandle.elem = elem;
        }

        // Handle multiple events separated by a space
        // jQuery(...).bind("mouseover mouseout", fn);
        types = ( types || "" ).match( core_rnotwhite ) || [""];
        t = types.length;
        while ( t-- ) {
            tmp = rtypenamespace.exec( types[t] ) || [];
            type = origType = tmp[1];
            namespaces = ( tmp[2] || "" ).split( "." ).sort();

            // If event changes its type, use the special event handlers for the changed type
            special = jQuery.event.special[ type ] || {};

            // If selector defined, determine special event api type, otherwise given type
            type = ( selector ? special.delegateType : special.bindType ) || type;

            // Update special based on newly reset type
            special = jQuery.event.special[ type ] || {};

            // handleObj is passed to all event handlers
            handleObj = jQuery.extend({
                type: type,
                origType: origType,
                data: data,
                handler: handler,
                guid: handler.guid,
                selector: selector,
                needsContext: selector && jQuery.expr.match.needsContext.test( selector ),
                namespace: namespaces.join(".")
            }, handleObjIn );

            // Init the event handler queue if we're the first
            if ( !(handlers = events[ type ]) ) {
                handlers = events[ type ] = [];
                handlers.delegateCount = 0;

                // Only use addEventListener/attachEvent if the special events handler returns false
                if ( !special.setup || special.setup.call( elem, data, namespaces, eventHandle ) === false ) {
                    // Bind the global event handler to the element
                    if ( elem.addEventListener ) {
                        elem.addEventListener( type, eventHandle, false );

                    } else if ( elem.attachEvent ) {
                        elem.attachEvent( "on" + type, eventHandle );
                    }
                }
            }

            if ( special.add ) {
                special.add.call( elem, handleObj );

                if ( !handleObj.handler.guid ) {
                    handleObj.handler.guid = handler.guid;
                }
            }

            // Add to the element's handler list, delegates in front
            if ( selector ) {
                handlers.splice( handlers.delegateCount++, 0, handleObj );
            } else {
                handlers.push( handleObj );
            }

            // Keep track of which events have ever been used, for event optimization
            jQuery.event.global[ type ] = true;
        }

        // Nullify elem to prevent memory leaks in IE
        elem = null;
    },

    // Detach an event or set of events from an element
    remove: function( elem, types, handler, selector, mappedTypes ) {
        var j, handleObj, tmp,
            origCount, t, events,
            special, handlers, type,
            namespaces, origType,
            elemData = jQuery.hasData( elem ) && jQuery._data( elem );

        if ( !elemData || !(events = elemData.events) ) {
            return;
        }

        // Once for each type.namespace in types; type may be omitted
        types = ( types || "" ).match( core_rnotwhite ) || [""];
        t = types.length;
        while ( t-- ) {
            tmp = rtypenamespace.exec( types[t] ) || [];
            type = origType = tmp[1];
            namespaces = ( tmp[2] || "" ).split( "." ).sort();

            // Unbind all events (on this namespace, if provided) for the element
            if ( !type ) {
                for ( type in events ) {
                    jQuery.event.remove( elem, type + types[ t ], handler, selector, true );
                }
                continue;
            }

            special = jQuery.event.special[ type ] || {};
            type = ( selector ? special.delegateType : special.bindType ) || type;
            handlers = events[ type ] || [];
            tmp = tmp[2] && new RegExp( "(^|\\.)" + namespaces.join("\\.(?:.*\\.|)") + "(\\.|$)" );

            // Remove matching events
            origCount = j = handlers.length;
            while ( j-- ) {
                handleObj = handlers[ j ];

                if ( ( mappedTypes || origType === handleObj.origType ) &&
                    ( !handler || handler.guid === handleObj.guid ) &&
                    ( !tmp || tmp.test( handleObj.namespace ) ) &&
                    ( !selector || selector === handleObj.selector || selector === "**" && handleObj.selector ) ) {
                    handlers.splice( j, 1 );

                    if ( handleObj.selector ) {
                        handlers.delegateCount--;
                    }
                    if ( special.remove ) {
                        special.remove.call( elem, handleObj );
                    }
                }
            }

            // Remove generic event handler if we removed something and no more handlers exist
            // (avoids potential for endless recursion during removal of special event handlers)
            if ( origCount && !handlers.length ) {
                if ( !special.teardown || special.teardown.call( elem, namespaces, elemData.handle ) === false ) {
                    jQuery.removeEvent( elem, type, elemData.handle );
                }

                delete events[ type ];
            }
        }

        // Remove the expando if it's no longer used
        if ( jQuery.isEmptyObject( events ) ) {
            delete elemData.handle;

            // removeData also checks for emptiness and clears the expando if empty
            // so use it instead of delete
            jQuery._removeData( elem, "events" );
        }
    },

    trigger: function( event, data, elem, onlyHandlers ) {
        var handle, ontype, cur,
            bubbleType, special, tmp, i,
            eventPath = [ elem || document ],
            type = core_hasOwn.call( event, "type" ) ? event.type : event,
            namespaces = core_hasOwn.call( event, "namespace" ) ? event.namespace.split(".") : [];

        cur = tmp = elem = elem || document;

        // Don't do events on text and comment nodes
        if ( elem.nodeType === 3 || elem.nodeType === 8 ) {
            return;
        }

        // focus/blur morphs to focusin/out; ensure we're not firing them right now
        if ( rfocusMorph.test( type + jQuery.event.triggered ) ) {
            return;
        }

        if ( type.indexOf(".") >= 0 ) {
            // Namespaced trigger; create a regexp to match event type in handle()
            namespaces = type.split(".");
            type = namespaces.shift();
            namespaces.sort();
        }
        ontype = type.indexOf(":") < 0 && "on" + type;

        // Caller can pass in a jQuery.Event object, Object, or just an event type string
        event = event[ jQuery.expando ] ?
            event :
            new jQuery.Event( type, typeof event === "object" && event );

        event.isTrigger = true;
        event.namespace = namespaces.join(".");
        event.namespace_re = event.namespace ?
            new RegExp( "(^|\\.)" + namespaces.join("\\.(?:.*\\.|)") + "(\\.|$)" ) :
            null;

        // Clean up the event in case it is being reused
        event.result = undefined;
        if ( !event.target ) {
            event.target = elem;
        }

        // Clone any incoming data and prepend the event, creating the handler arg list
        data = data == null ?
            [ event ] :
            jQuery.makeArray( data, [ event ] );

        // Allow special events to draw outside the lines
        special = jQuery.event.special[ type ] || {};
        if ( !onlyHandlers && special.trigger && special.trigger.apply( elem, data ) === false ) {
            return;
        }

        // Determine event propagation path in advance, per W3C events spec (#9951)
        // Bubble up to document, then to window; watch for a global ownerDocument var (#9724)
        if ( !onlyHandlers && !special.noBubble && !jQuery.isWindow( elem ) ) {

            bubbleType = special.delegateType || type;
            if ( !rfocusMorph.test( bubbleType + type ) ) {
                cur = cur.parentNode;
            }
            for ( ; cur; cur = cur.parentNode ) {
                eventPath.push( cur );
                tmp = cur;
            }

            // Only add window if we got to document (e.g., not plain obj or detached DOM)
            if ( tmp === (elem.ownerDocument || document) ) {
                eventPath.push( tmp.defaultView || tmp.parentWindow || window );
            }
        }

        // Fire handlers on the event path
        i = 0;
        while ( (cur = eventPath[i++]) && !event.isPropagationStopped() ) {

            event.type = i > 1 ?
                bubbleType :
                special.bindType || type;

            // jQuery handler
            handle = ( jQuery._data( cur, "events" ) || {} )[ event.type ] && jQuery._data( cur, "handle" );
            if ( handle ) {
                handle.apply( cur, data );
            }

            // Native handler
            handle = ontype && cur[ ontype ];
            if ( handle && jQuery.acceptData( cur ) && handle.apply && handle.apply( cur, data ) === false ) {
                event.preventDefault();
            }
        }
        event.type = type;

        // If nobody prevented the default action, do it now
        if ( !onlyHandlers && !event.isDefaultPrevented() ) {

            if ( (!special._default || special._default.apply( elem.ownerDocument, data ) === false) &&
                !(type === "click" && jQuery.nodeName( elem, "a" )) && jQuery.acceptData( elem ) ) {

                // Call a native DOM method on the target with the same name name as the event.
                // Can't use an .isFunction() check here because IE6/7 fails that test.
                // Don't do default actions on window, that's where global variables be (#6170)
                if ( ontype && elem[ type ] && !jQuery.isWindow( elem ) ) {

                    // Don't re-trigger an onFOO event when we call its FOO() method
                    tmp = elem[ ontype ];

                    if ( tmp ) {
                        elem[ ontype ] = null;
                    }

                    // Prevent re-triggering of the same event, since we already bubbled it above
                    jQuery.event.triggered = type;
                    try {
                        elem[ type ]();
                    } catch ( e ) {
                        // IE<9 dies on focus/blur to hidden element (#1486,#12518)
                        // only reproducible on winXP IE8 native, not IE9 in IE8 mode
                    }
                    jQuery.event.triggered = undefined;

                    if ( tmp ) {
                        elem[ ontype ] = tmp;
                    }
                }
            }
        }

        return event.result;
    },

    dispatch: function( event ) {

        // Make a writable jQuery.Event from the native event object
        event = jQuery.event.fix( event );

        var i, ret, handleObj, matched, j,
            handlerQueue = [],
            args = core_slice.call( arguments ),
            handlers = ( jQuery._data( this, "events" ) || {} )[ event.type ] || [],
            special = jQuery.event.special[ event.type ] || {};

        // Use the fix-ed jQuery.Event rather than the (read-only) native event
        args[0] = event;
        event.delegateTarget = this;

        // Call the preDispatch hook for the mapped type, and let it bail if desired
        if ( special.preDispatch && special.preDispatch.call( this, event ) === false ) {
            return;
        }

        // Determine handlers
        handlerQueue = jQuery.event.handlers.call( this, event, handlers );

        // Run delegates first; they may want to stop propagation beneath us
        i = 0;
        while ( (matched = handlerQueue[ i++ ]) && !event.isPropagationStopped() ) {
            event.currentTarget = matched.elem;

            j = 0;
            while ( (handleObj = matched.handlers[ j++ ]) && !event.isImmediatePropagationStopped() ) {

                // Triggered event must either 1) have no namespace, or
                // 2) have namespace(s) a subset or equal to those in the bound event (both can have no namespace).
                if ( !event.namespace_re || event.namespace_re.test( handleObj.namespace ) ) {

                    event.handleObj = handleObj;
                    event.data = handleObj.data;

                    ret = ( (jQuery.event.special[ handleObj.origType ] || {}).handle || handleObj.handler )
                            .apply( matched.elem, args );

                    if ( ret !== undefined ) {
                        if ( (event.result = ret) === false ) {
                            event.preventDefault();
                            event.stopPropagation();
                        }
                    }
                }
            }
        }

        // Call the postDispatch hook for the mapped type
        if ( special.postDispatch ) {
            special.postDispatch.call( this, event );
        }

        return event.result;
    },

    handlers: function( event, handlers ) {
        var sel, handleObj, matches, i,
            handlerQueue = [],
            delegateCount = handlers.delegateCount,
            cur = event.target;

        // Find delegate handlers
        // Black-hole SVG <use> instance trees (#13180)
        // Avoid non-left-click bubbling in Firefox (#3861)
        if ( delegateCount && cur.nodeType && (!event.button || event.type !== "click") ) {

            for ( ; cur != this; cur = cur.parentNode || this ) {

                // Don't check non-elements (#13208)
                // Don't process clicks on disabled elements (#6911, #8165, #11382, #11764)
                if ( cur.nodeType === 1 && (cur.disabled !== true || event.type !== "click") ) {
                    matches = [];
                    for ( i = 0; i < delegateCount; i++ ) {
                        handleObj = handlers[ i ];

                        // Don't conflict with Object.prototype properties (#13203)
                        sel = handleObj.selector + " ";

                        if ( matches[ sel ] === undefined ) {
                            matches[ sel ] = handleObj.needsContext ?
                                jQuery( sel, this ).index( cur ) >= 0 :
                                jQuery.find( sel, this, null, [ cur ] ).length;
                        }
                        if ( matches[ sel ] ) {
                            matches.push( handleObj );
                        }
                    }
                    if ( matches.length ) {
                        handlerQueue.push({ elem: cur, handlers: matches });
                    }
                }
            }
        }

        // Add the remaining (directly-bound) handlers
        if ( delegateCount < handlers.length ) {
            handlerQueue.push({ elem: this, handlers: handlers.slice( delegateCount ) });
        }

        return handlerQueue;
    },

    fix: function( event ) {
        if ( event[ jQuery.expando ] ) {
            return event;
        }

        // Create a writable copy of the event object and normalize some properties
        var i, prop, copy,
            type = event.type,
            originalEvent = event,
            fixHook = this.fixHooks[ type ];

        if ( !fixHook ) {
            this.fixHooks[ type ] = fixHook =
                rmouseEvent.test( type ) ? this.mouseHooks :
                rkeyEvent.test( type ) ? this.keyHooks :
                {};
        }
        copy = fixHook.props ? this.props.concat( fixHook.props ) : this.props;

        event = new jQuery.Event( originalEvent );

        i = copy.length;
        while ( i-- ) {
            prop = copy[ i ];
            event[ prop ] = originalEvent[ prop ];
        }

        // Support: IE<9
        // Fix target property (#1925)
        if ( !event.target ) {
            event.target = originalEvent.srcElement || document;
        }

        // Support: Chrome 23+, Safari?
        // Target should not be a text node (#504, #13143)
        if ( event.target.nodeType === 3 ) {
            event.target = event.target.parentNode;
        }

        // Support: IE<9
        // For mouse/key events, metaKey==false if it's undefined (#3368, #11328)
        event.metaKey = !!event.metaKey;

        return fixHook.filter ? fixHook.filter( event, originalEvent ) : event;
    },

    // Includes some event props shared by KeyEvent and MouseEvent
    props: "altKey bubbles cancelable ctrlKey currentTarget eventPhase metaKey relatedTarget shiftKey target timeStamp view which".split(" "),

    fixHooks: {},

    keyHooks: {
        props: "char charCode key keyCode".split(" "),
        filter: function( event, original ) {

            // Add which for key events
            if ( event.which == null ) {
                event.which = original.charCode != null ? original.charCode : original.keyCode;
            }

            return event;
        }
    },

    mouseHooks: {
        props: "button buttons clientX clientY fromElement offsetX offsetY pageX pageY screenX screenY toElement".split(" "),
        filter: function( event, original ) {
            var body, eventDoc, doc,
                button = original.button,
                fromElement = original.fromElement;

            // Calculate pageX/Y if missing and clientX/Y available
            if ( event.pageX == null && original.clientX != null ) {
                eventDoc = event.target.ownerDocument || document;
                doc = eventDoc.documentElement;
                body = eventDoc.body;

                event.pageX = original.clientX + ( doc && doc.scrollLeft || body && body.scrollLeft || 0 ) - ( doc && doc.clientLeft || body && body.clientLeft || 0 );
                event.pageY = original.clientY + ( doc && doc.scrollTop  || body && body.scrollTop  || 0 ) - ( doc && doc.clientTop  || body && body.clientTop  || 0 );
            }

            // Add relatedTarget, if necessary
            if ( !event.relatedTarget && fromElement ) {
                event.relatedTarget = fromElement === event.target ? original.toElement : fromElement;
            }

            // Add which for click: 1 === left; 2 === middle; 3 === right
            // Note: button is not normalized, so don't use it
            if ( !event.which && button !== undefined ) {
                event.which = ( button & 1 ? 1 : ( button & 2 ? 3 : ( button & 4 ? 2 : 0 ) ) );
            }

            return event;
        }
    },

    special: {
        load: {
            // Prevent triggered image.load events from bubbling to window.load
            noBubble: true
        },
        click: {
            // For checkbox, fire native event so checked state will be right
            trigger: function() {
                if ( jQuery.nodeName( this, "input" ) && this.type === "checkbox" && this.click ) {
                    this.click();
                    return false;
                }
            }
        },
        focus: {
            // Fire native event if possible so blur/focus sequence is correct
            trigger: function() {
                if ( this !== document.activeElement && this.focus ) {
                    try {
                        this.focus();
                        return false;
                    } catch ( e ) {
                        // Support: IE<9
                        // If we error on focus to hidden element (#1486, #12518),
                        // let .trigger() run the handlers
                    }
                }
            },
            delegateType: "focusin"
        },
        blur: {
            trigger: function() {
                if ( this === document.activeElement && this.blur ) {
                    this.blur();
                    return false;
                }
            },
            delegateType: "focusout"
        },

        beforeunload: {
            postDispatch: function( event ) {

                // Even when returnValue equals to undefined Firefox will still show alert
                if ( event.result !== undefined ) {
                    event.originalEvent.returnValue = event.result;
                }
            }
        }
    },

    simulate: function( type, elem, event, bubble ) {
        // Piggyback on a donor event to simulate a different one.
        // Fake originalEvent to avoid donor's stopPropagation, but if the
        // simulated event prevents default then we do the same on the donor.
        var e = jQuery.extend(
            new jQuery.Event(),
            event,
            { type: type,
                isSimulated: true,
                originalEvent: {}
            }
        );
        if ( bubble ) {
            jQuery.event.trigger( e, null, elem );
        } else {
            jQuery.event.dispatch.call( elem, e );
        }
        if ( e.isDefaultPrevented() ) {
            event.preventDefault();
        }
    }
};

jQuery.removeEvent = document.removeEventListener ?
    function( elem, type, handle ) {
        if ( elem.removeEventListener ) {
            elem.removeEventListener( type, handle, false );
        }
    } :
    function( elem, type, handle ) {
        var name = "on" + type;

        if ( elem.detachEvent ) {

            // #8545, #7054, preventing memory leaks for custom events in IE6-8
            // detachEvent needed property on element, by name of that event, to properly expose it to GC
            if ( typeof elem[ name ] === core_strundefined ) {
                elem[ name ] = null;
            }

            elem.detachEvent( name, handle );
        }
    };

jQuery.Event = function( src, props ) {
    // Allow instantiation without the 'new' keyword
    if ( !(this instanceof jQuery.Event) ) {
        return new jQuery.Event( src, props );
    }

    // Event object
    if ( src && src.type ) {
        this.originalEvent = src;
        this.type = src.type;

        // Events bubbling up the document may have been marked as prevented
        // by a handler lower down the tree; reflect the correct value.
        this.isDefaultPrevented = ( src.defaultPrevented || src.returnValue === false ||
            src.getPreventDefault && src.getPreventDefault() ) ? returnTrue : returnFalse;

    // Event type
    } else {
        this.type = src;
    }

    // Put explicitly provided properties onto the event object
    if ( props ) {
        jQuery.extend( this, props );
    }

    // Create a timestamp if incoming event doesn't have one
    this.timeStamp = src && src.timeStamp || jQuery.now();

    // Mark it as fixed
    this[ jQuery.expando ] = true;
};

// jQuery.Event is based on DOM3 Events as specified by the ECMAScript Language Binding
// http://www.w3.org/TR/2003/WD-DOM-Level-3-Events-20030331/ecma-script-binding.html
jQuery.Event.prototype = {
    isDefaultPrevented: returnFalse,
    isPropagationStopped: returnFalse,
    isImmediatePropagationStopped: returnFalse,

    preventDefault: function() {
        var e = this.originalEvent;

        this.isDefaultPrevented = returnTrue;
        if ( !e ) {
            return;
        }

        // If preventDefault exists, run it on the original event
        if ( e.preventDefault ) {
            e.preventDefault();

        // Support: IE
        // Otherwise set the returnValue property of the original event to false
        } else {
            e.returnValue = false;
        }
    },
    stopPropagation: function() {
        var e = this.originalEvent;

        this.isPropagationStopped = returnTrue;
        if ( !e ) {
            return;
        }
        // If stopPropagation exists, run it on the original event
        if ( e.stopPropagation ) {
            e.stopPropagation();
        }

        // Support: IE
        // Set the cancelBubble property of the original event to true
        e.cancelBubble = true;
    },
    stopImmediatePropagation: function() {
        this.isImmediatePropagationStopped = returnTrue;
        this.stopPropagation();
    }
};

// Create mouseenter/leave events using mouseover/out and event-time checks
jQuery.each({
    mouseenter: "mouseover",
    mouseleave: "mouseout"
}, function( orig, fix ) {
    jQuery.event.special[ orig ] = {
        delegateType: fix,
        bindType: fix,

        handle: function( event ) {
            var ret,
                target = this,
                related = event.relatedTarget,
                handleObj = event.handleObj;

            // For mousenter/leave call the handler if related is outside the target.
            // NB: No relatedTarget if the mouse left/entered the browser window
            if ( !related || (related !== target && !jQuery.contains( target, related )) ) {
                event.type = handleObj.origType;
                ret = handleObj.handler.apply( this, arguments );
                event.type = fix;
            }
            return ret;
        }
    };
});

// IE submit delegation
if ( !jQuery.support.submitBubbles ) {

    jQuery.event.special.submit = {
        setup: function() {
            // Only need this for delegated form submit events
            if ( jQuery.nodeName( this, "form" ) ) {
                return false;
            }

            // Lazy-add a submit handler when a descendant form may potentially be submitted
            jQuery.event.add( this, "click._submit keypress._submit", function( e ) {
                // Node name check avoids a VML-related crash in IE (#9807)
                var elem = e.target,
                    form = jQuery.nodeName( elem, "input" ) || jQuery.nodeName( elem, "button" ) ? elem.form : undefined;
                if ( form && !jQuery._data( form, "submitBubbles" ) ) {
                    jQuery.event.add( form, "submit._submit", function( event ) {
                        event._submit_bubble = true;
                    });
                    jQuery._data( form, "submitBubbles", true );
                }
            });
            // return undefined since we don't need an event listener
        },

        postDispatch: function( event ) {
            // If form was submitted by the user, bubble the event up the tree
            if ( event._submit_bubble ) {
                delete event._submit_bubble;
                if ( this.parentNode && !event.isTrigger ) {
                    jQuery.event.simulate( "submit", this.parentNode, event, true );
                }
            }
        },

        teardown: function() {
            // Only need this for delegated form submit events
            if ( jQuery.nodeName( this, "form" ) ) {
                return false;
            }

            // Remove delegated handlers; cleanData eventually reaps submit handlers attached above
            jQuery.event.remove( this, "._submit" );
        }
    };
}

// IE change delegation and checkbox/radio fix
if ( !jQuery.support.changeBubbles ) {

    jQuery.event.special.change = {

        setup: function() {

            if ( rformElems.test( this.nodeName ) ) {
                // IE doesn't fire change on a check/radio until blur; trigger it on click
                // after a propertychange. Eat the blur-change in special.change.handle.
                // This still fires onchange a second time for check/radio after blur.
                if ( this.type === "checkbox" || this.type === "radio" ) {
                    jQuery.event.add( this, "propertychange._change", function( event ) {
                        if ( event.originalEvent.propertyName === "checked" ) {
                            this._just_changed = true;
                        }
                    });
                    jQuery.event.add( this, "click._change", function( event ) {
                        if ( this._just_changed && !event.isTrigger ) {
                            this._just_changed = false;
                        }
                        // Allow triggered, simulated change events (#11500)
                        jQuery.event.simulate( "change", this, event, true );
                    });
                }
                return false;
            }
            // Delegated event; lazy-add a change handler on descendant inputs
            jQuery.event.add( this, "beforeactivate._change", function( e ) {
                var elem = e.target;

                if ( rformElems.test( elem.nodeName ) && !jQuery._data( elem, "changeBubbles" ) ) {
                    jQuery.event.add( elem, "change._change", function( event ) {
                        if ( this.parentNode && !event.isSimulated && !event.isTrigger ) {
                            jQuery.event.simulate( "change", this.parentNode, event, true );
                        }
                    });
                    jQuery._data( elem, "changeBubbles", true );
                }
            });
        },

        handle: function( event ) {
            var elem = event.target;

            // Swallow native change events from checkbox/radio, we already triggered them above
            if ( this !== elem || event.isSimulated || event.isTrigger || (elem.type !== "radio" && elem.type !== "checkbox") ) {
                return event.handleObj.handler.apply( this, arguments );
            }
        },

        teardown: function() {
            jQuery.event.remove( this, "._change" );

            return !rformElems.test( this.nodeName );
        }
    };
}

// Create "bubbling" focus and blur events
if ( !jQuery.support.focusinBubbles ) {
    jQuery.each({ focus: "focusin", blur: "focusout" }, function( orig, fix ) {

        // Attach a single capturing handler while someone wants focusin/focusout
        var attaches = 0,
            handler = function( event ) {
                jQuery.event.simulate( fix, event.target, jQuery.event.fix( event ), true );
            };

        jQuery.event.special[ fix ] = {
            setup: function() {
                if ( attaches++ === 0 ) {
                    document.addEventListener( orig, handler, true );
                }
            },
            teardown: function() {
                if ( --attaches === 0 ) {
                    document.removeEventListener( orig, handler, true );
                }
            }
        };
    });
}

jQuery.fn.extend({

    on: function( types, selector, data, fn, /*INTERNAL*/ one ) {
        var type, origFn;

        // Types can be a map of types/handlers
        if ( typeof types === "object" ) {
            // ( types-Object, selector, data )
            if ( typeof selector !== "string" ) {
                // ( types-Object, data )
                data = data || selector;
                selector = undefined;
            }
            for ( type in types ) {
                this.on( type, selector, data, types[ type ], one );
            }
            return this;
        }

        if ( data == null && fn == null ) {
            // ( types, fn )
            fn = selector;
            data = selector = undefined;
        } else if ( fn == null ) {
            if ( typeof selector === "string" ) {
                // ( types, selector, fn )
                fn = data;
                data = undefined;
            } else {
                // ( types, data, fn )
                fn = data;
                data = selector;
                selector = undefined;
            }
        }
        if ( fn === false ) {
            fn = returnFalse;
        } else if ( !fn ) {
            return this;
        }

        if ( one === 1 ) {
            origFn = fn;
            fn = function( event ) {
                // Can use an empty set, since event contains the info
                jQuery().off( event );
                return origFn.apply( this, arguments );
            };
            // Use same guid so caller can remove using origFn
            fn.guid = origFn.guid || ( origFn.guid = jQuery.guid++ );
        }
        return this.each( function() {
            jQuery.event.add( this, types, fn, data, selector );
        });
    },
    one: function( types, selector, data, fn ) {
        return this.on( types, selector, data, fn, 1 );
    },
    off: function( types, selector, fn ) {
        var handleObj, type;
        if ( types && types.preventDefault && types.handleObj ) {
            // ( event )  dispatched jQuery.Event
            handleObj = types.handleObj;
            jQuery( types.delegateTarget ).off(
                handleObj.namespace ? handleObj.origType + "." + handleObj.namespace : handleObj.origType,
                handleObj.selector,
                handleObj.handler
            );
            return this;
        }
        if ( typeof types === "object" ) {
            // ( types-object [, selector] )
            for ( type in types ) {
                this.off( type, selector, types[ type ] );
            }
            return this;
        }
        if ( selector === false || typeof selector === "function" ) {
            // ( types [, fn] )
            fn = selector;
            selector = undefined;
        }
        if ( fn === false ) {
            fn = returnFalse;
        }
        return this.each(function() {
            jQuery.event.remove( this, types, fn, selector );
        });
    },

    bind: function( types, data, fn ) {
        return this.on( types, null, data, fn );
    },
    unbind: function( types, fn ) {
        return this.off( types, null, fn );
    },

    delegate: function( selector, types, data, fn ) {
        return this.on( types, selector, data, fn );
    },
    undelegate: function( selector, types, fn ) {
        // ( namespace ) or ( selector, types [, fn] )
        return arguments.length === 1 ? this.off( selector, "**" ) : this.off( types, selector || "**", fn );
    },

    trigger: function( type, data ) {
        return this.each(function() {
            jQuery.event.trigger( type, data, this );
        });
    },
    triggerHandler: function( type, data ) {
        var elem = this[0];
        if ( elem ) {
            return jQuery.event.trigger( type, data, elem, true );
        }
    }
});
/*!
 * Sizzle CSS Selector Engine
 * Copyright 2012 jQuery Foundation and other contributors
 * Released under the MIT license
 * http://sizzlejs.com/
 */
(function( window, undefined ) {

var i,
    cachedruns,
    Expr,
    getText,
    isXML,
    compile,
    hasDuplicate,
    outermostContext,

    // Local document vars
    setDocument,
    document,
    docElem,
    documentIsXML,
    rbuggyQSA,
    rbuggyMatches,
    matches,
    contains,
    sortOrder,

    // Instance-specific data
    expando = "sizzle" + -(new Date()),
    preferredDoc = window.document,
    support = {},
    dirruns = 0,
    done = 0,
    classCache = createCache(),
    tokenCache = createCache(),
    compilerCache = createCache(),

    // General-purpose constants
    strundefined = typeof undefined,
    MAX_NEGATIVE = 1 << 31,

    // Array methods
    arr = [],
    pop = arr.pop,
    push = arr.push,
    slice = arr.slice,
    // Use a stripped-down indexOf if we can't use a native one
    indexOf = arr.indexOf || function( elem ) {
        var i = 0,
            len = this.length;
        for ( ; i < len; i++ ) {
            if ( this[i] === elem ) {
                return i;
            }
        }
        return -1;
    },


    // Regular expressions

    // Whitespace characters http://www.w3.org/TR/css3-selectors/#whitespace
    whitespace = "[\\x20\\t\\r\\n\\f]",
    // http://www.w3.org/TR/css3-syntax/#characters
    characterEncoding = "(?:\\\\.|[\\w-]|[^\\x00-\\xa0])+",

    // Loosely modeled on CSS identifier characters
    // An unquoted value should be a CSS identifier http://www.w3.org/TR/css3-selectors/#attribute-selectors
    // Proper syntax: http://www.w3.org/TR/CSS21/syndata.html#value-def-identifier
    identifier = characterEncoding.replace( "w", "w#" ),

    // Acceptable operators http://www.w3.org/TR/selectors/#attribute-selectors
    operators = "([*^$|!~]?=)",
    attributes = "\\[" + whitespace + "*(" + characterEncoding + ")" + whitespace +
        "*(?:" + operators + whitespace + "*(?:(['\"])((?:\\\\.|[^\\\\])*?)\\3|(" + identifier + ")|)|)" + whitespace + "*\\]",

    // Prefer arguments quoted,
    //   then not containing pseudos/brackets,
    //   then attribute selectors/non-parenthetical expressions,
    //   then anything else
    // These preferences are here to reduce the number of selectors
    //   needing tokenize in the PSEUDO preFilter
    pseudos = ":(" + characterEncoding + ")(?:\\(((['\"])((?:\\\\.|[^\\\\])*?)\\3|((?:\\\\.|[^\\\\()[\\]]|" + attributes.replace( 3, 8 ) + ")*)|.*)\\)|)",

    // Leading and non-escaped trailing whitespace, capturing some non-whitespace characters preceding the latter
    rtrim = new RegExp( "^" + whitespace + "+|((?:^|[^\\\\])(?:\\\\.)*)" + whitespace + "+$", "g" ),

    rcomma = new RegExp( "^" + whitespace + "*," + whitespace + "*" ),
    rcombinators = new RegExp( "^" + whitespace + "*([\\x20\\t\\r\\n\\f>+~])" + whitespace + "*" ),
    rpseudo = new RegExp( pseudos ),
    ridentifier = new RegExp( "^" + identifier + "$" ),

    matchExpr = {
        "ID": new RegExp( "^#(" + characterEncoding + ")" ),
        "CLASS": new RegExp( "^\\.(" + characterEncoding + ")" ),
        "NAME": new RegExp( "^\\[name=['\"]?(" + characterEncoding + ")['\"]?\\]" ),
        "TAG": new RegExp( "^(" + characterEncoding.replace( "w", "w*" ) + ")" ),
        "ATTR": new RegExp( "^" + attributes ),
        "PSEUDO": new RegExp( "^" + pseudos ),
        "CHILD": new RegExp( "^:(only|first|last|nth|nth-last)-(child|of-type)(?:\\(" + whitespace +
            "*(even|odd|(([+-]|)(\\d*)n|)" + whitespace + "*(?:([+-]|)" + whitespace +
            "*(\\d+)|))" + whitespace + "*\\)|)", "i" ),
        // For use in libraries implementing .is()
        // We use this for POS matching in `select`
        "needsContext": new RegExp( "^" + whitespace + "*[>+~]|:(even|odd|eq|gt|lt|nth|first|last)(?:\\(" +
            whitespace + "*((?:-\\d)?\\d*)" + whitespace + "*\\)|)(?=[^-]|$)", "i" )
    },

    rsibling = /[\x20\t\r\n\f]*[+~]/,

    rnative = /^[^{]+\{\s*\[native code/,

    // Easily-parseable/retrievable ID or TAG or CLASS selectors
    rquickExpr = /^(?:#([\w-]+)|(\w+)|\.([\w-]+))$/,

    rinputs = /^(?:input|select|textarea|button)$/i,
    rheader = /^h\d$/i,

    rescape = /'|\\/g,
    rattributeQuotes = /\=[\x20\t\r\n\f]*([^'"\]]*)[\x20\t\r\n\f]*\]/g,

    // CSS escapes http://www.w3.org/TR/CSS21/syndata.html#escaped-characters
    runescape = /\\([\da-fA-F]{1,6}[\x20\t\r\n\f]?|.)/g,
    funescape = function( _, escaped ) {
        var high = "0x" + escaped - 0x10000;
        // NaN means non-codepoint
        return high !== high ?
            escaped :
            // BMP codepoint
            high < 0 ?
                String.fromCharCode( high + 0x10000 ) :
                // Supplemental Plane codepoint (surrogate pair)
                String.fromCharCode( high >> 10 | 0xD800, high & 0x3FF | 0xDC00 );
    };

// Use a stripped-down slice if we can't use a native one
try {
    slice.call( preferredDoc.documentElement.childNodes, 0 )[0].nodeType;
} catch ( e ) {
    slice = function( i ) {
        var elem,
            results = [];
        while ( (elem = this[i++]) ) {
            results.push( elem );
        }
        return results;
    };
}

/**
 * For feature detection
 * @param {Function} fn The function to test for native support
 */
function isNative( fn ) {
    return rnative.test( fn + "" );
}

/**
 * Create key-value caches of limited size
 * @returns {Function(string, Object)} Returns the Object data after storing it on itself with
 *  property name the (space-suffixed) string and (if the cache is larger than Expr.cacheLength)
 *  deleting the oldest entry
 */
function createCache() {
    var cache,
        keys = [];

    return (cache = function( key, value ) {
        // Use (key + " ") to avoid collision with native prototype properties (see Issue #157)
        if ( keys.push( key += " " ) > Expr.cacheLength ) {
            // Only keep the most recent entries
            delete cache[ keys.shift() ];
        }
        return (cache[ key ] = value);
    });
}

/**
 * Mark a function for special use by Sizzle
 * @param {Function} fn The function to mark
 */
function markFunction( fn ) {
    fn[ expando ] = true;
    return fn;
}

/**
 * Support testing using an element
 * @param {Function} fn Passed the created div and expects a boolean result
 */
function assert( fn ) {
    var div = document.createElement("div");

    try {
        return fn( div );
    } catch (e) {
        return false;
    } finally {
        // release memory in IE
        div = null;
    }
}

function Sizzle( selector, context, results, seed ) {
    var match, elem, m, nodeType,
        // QSA vars
        i, groups, old, nid, newContext, newSelector;

    if ( ( context ? context.ownerDocument || context : preferredDoc ) !== document ) {
        setDocument( context );
    }

    context = context || document;
    results = results || [];

    if ( !selector || typeof selector !== "string" ) {
        return results;
    }

    if ( (nodeType = context.nodeType) !== 1 && nodeType !== 9 ) {
        return [];
    }

    if ( !documentIsXML && !seed ) {

        // Shortcuts
        if ( (match = rquickExpr.exec( selector )) ) {
            // Speed-up: Sizzle("#ID")
            if ( (m = match[1]) ) {
                if ( nodeType === 9 ) {
                    elem = context.getElementById( m );
                    // Check parentNode to catch when Blackberry 4.6 returns
                    // nodes that are no longer in the document #6963
                    if ( elem && elem.parentNode ) {
                        // Handle the case where IE, Opera, and Webkit return items
                        // by name instead of ID
                        if ( elem.id === m ) {
                            results.push( elem );
                            return results;
                        }
                    } else {
                        return results;
                    }
                } else {
                    // Context is not a document
                    if ( context.ownerDocument && (elem = context.ownerDocument.getElementById( m )) &&
                        contains( context, elem ) && elem.id === m ) {
                        results.push( elem );
                        return results;
                    }
                }

            // Speed-up: Sizzle("TAG")
            } else if ( match[2] ) {
                push.apply( results, slice.call(context.getElementsByTagName( selector ), 0) );
                return results;

            // Speed-up: Sizzle(".CLASS")
            } else if ( (m = match[3]) && support.getByClassName && context.getElementsByClassName ) {
                push.apply( results, slice.call(context.getElementsByClassName( m ), 0) );
                return results;
            }
        }

        // QSA path
        if ( support.qsa && !rbuggyQSA.test(selector) ) {
            old = true;
            nid = expando;
            newContext = context;
            newSelector = nodeType === 9 && selector;

            // qSA works strangely on Element-rooted queries
            // We can work around this by specifying an extra ID on the root
            // and working up from there (Thanks to Andrew Dupont for the technique)
            // IE 8 doesn't work on object elements
            if ( nodeType === 1 && context.nodeName.toLowerCase() !== "object" ) {
                groups = tokenize( selector );

                if ( (old = context.getAttribute("id")) ) {
                    nid = old.replace( rescape, "\\$&" );
                } else {
                    context.setAttribute( "id", nid );
                }
                nid = "[id='" + nid + "'] ";

                i = groups.length;
                while ( i-- ) {
                    groups[i] = nid + toSelector( groups[i] );
                }
                newContext = rsibling.test( selector ) && context.parentNode || context;
                newSelector = groups.join(",");
            }

            if ( newSelector ) {
                try {
                    push.apply( results, slice.call( newContext.querySelectorAll(
                        newSelector
                    ), 0 ) );
                    return results;
                } catch(qsaError) {
                } finally {
                    if ( !old ) {
                        context.removeAttribute("id");
                    }
                }
            }
        }
    }

    // All others
    return select( selector.replace( rtrim, "$1" ), context, results, seed );
}

/**
 * Detect xml
 * @param {Element|Object} elem An element or a document
 */
isXML = Sizzle.isXML = function( elem ) {
    // documentElement is verified for cases where it doesn't yet exist
    // (such as loading iframes in IE - #4833)
    var documentElement = elem && (elem.ownerDocument || elem).documentElement;
    return documentElement ? documentElement.nodeName !== "HTML" : false;
};

/**
 * Sets document-related variables once based on the current document
 * @param {Element|Object} [doc] An element or document object to use to set the document
 * @returns {Object} Returns the current document
 */
setDocument = Sizzle.setDocument = function( node ) {
    var doc = node ? node.ownerDocument || node : preferredDoc;

    // If no document and documentElement is available, return
    if ( doc === document || doc.nodeType !== 9 || !doc.documentElement ) {
        return document;
    }

    // Set our document
    document = doc;
    docElem = doc.documentElement;

    // Support tests
    documentIsXML = isXML( doc );

    // Check if getElementsByTagName("*") returns only elements
    support.tagNameNoComments = assert(function( div ) {
        div.appendChild( doc.createComment("") );
        return !div.getElementsByTagName("*").length;
    });

    // Check if attributes should be retrieved by attribute nodes
    support.attributes = assert(function( div ) {
        div.innerHTML = "<select></select>";
        var type = typeof div.lastChild.getAttribute("multiple");
        // IE8 returns a string for some attributes even when not present
        return type !== "boolean" && type !== "string";
    });

    // Check if getElementsByClassName can be trusted
    support.getByClassName = assert(function( div ) {
        // Opera can't find a second classname (in 9.6)
        div.innerHTML = "<div class='hidden e'></div><div class='hidden'></div>";
        if ( !div.getElementsByClassName || !div.getElementsByClassName("e").length ) {
            return false;
        }

        // Safari 3.2 caches class attributes and doesn't catch changes
        div.lastChild.className = "e";
        return div.getElementsByClassName("e").length === 2;
    });

    // Check if getElementById returns elements by name
    // Check if getElementsByName privileges form controls or returns elements by ID
    support.getByName = assert(function( div ) {
        // Inject content
        div.id = expando + 0;
        div.innerHTML = "<a name='" + expando + "'></a><div name='" + expando + "'></div>";
        docElem.insertBefore( div, docElem.firstChild );

        // Test
        var pass = doc.getElementsByName &&
            // buggy browsers will return fewer than the correct 2
            doc.getElementsByName( expando ).length === 2 +
            // buggy browsers will return more than the correct 0
            doc.getElementsByName( expando + 0 ).length;
        support.getIdNotName = !doc.getElementById( expando );

        // Cleanup
        docElem.removeChild( div );

        return pass;
    });

    // IE6/7 return modified attributes
    Expr.attrHandle = assert(function( div ) {
        div.innerHTML = "<a href='#'></a>";
        return div.firstChild && typeof div.firstChild.getAttribute !== strundefined &&
            div.firstChild.getAttribute("href") === "#";
    }) ?
        {} :
        {
            "href": function( elem ) {
                return elem.getAttribute( "href", 2 );
            },
            "type": function( elem ) {
                return elem.getAttribute("type");
            }
        };

    // ID find and filter
    if ( support.getIdNotName ) {
        Expr.find["ID"] = function( id, context ) {
            if ( typeof context.getElementById !== strundefined && !documentIsXML ) {
                var m = context.getElementById( id );
                // Check parentNode to catch when Blackberry 4.6 returns
                // nodes that are no longer in the document #6963
                return m && m.parentNode ? [m] : [];
            }
        };
        Expr.filter["ID"] = function( id ) {
            var attrId = id.replace( runescape, funescape );
            return function( elem ) {
                return elem.getAttribute("id") === attrId;
            };
        };
    } else {
        Expr.find["ID"] = function( id, context ) {
            if ( typeof context.getElementById !== strundefined && !documentIsXML ) {
                var m = context.getElementById( id );

                return m ?
                    m.id === id || typeof m.getAttributeNode !== strundefined && m.getAttributeNode("id").value === id ?
                        [m] :
                        undefined :
                    [];
            }
        };
        Expr.filter["ID"] =  function( id ) {
            var attrId = id.replace( runescape, funescape );
            return function( elem ) {
                var node = typeof elem.getAttributeNode !== strundefined && elem.getAttributeNode("id");
                return node && node.value === attrId;
            };
        };
    }

    // Tag
    Expr.find["TAG"] = support.tagNameNoComments ?
        function( tag, context ) {
            if ( typeof context.getElementsByTagName !== strundefined ) {
                return context.getElementsByTagName( tag );
            }
        } :
        function( tag, context ) {
            var elem,
                tmp = [],
                i = 0,
                results = context.getElementsByTagName( tag );

            // Filter out possible comments
            if ( tag === "*" ) {
                while ( (elem = results[i++]) ) {
                    if ( elem.nodeType === 1 ) {
                        tmp.push( elem );
                    }
                }

                return tmp;
            }
            return results;
        };

    // Name
    Expr.find["NAME"] = support.getByName && function( tag, context ) {
        if ( typeof context.getElementsByName !== strundefined ) {
            return context.getElementsByName( name );
        }
    };

    // Class
    Expr.find["CLASS"] = support.getByClassName && function( className, context ) {
        if ( typeof context.getElementsByClassName !== strundefined && !documentIsXML ) {
            return context.getElementsByClassName( className );
        }
    };

    // QSA and matchesSelector support

    // matchesSelector(:active) reports false when true (IE9/Opera 11.5)
    rbuggyMatches = [];

    // qSa(:focus) reports false when true (Chrome 21),
    // no need to also add to buggyMatches since matches checks buggyQSA
    // A support test would require too much code (would include document ready)
    rbuggyQSA = [ ":focus" ];

    if ( (support.qsa = isNative(doc.querySelectorAll)) ) {
        // Build QSA regex
        // Regex strategy adopted from Diego Perini
        assert(function( div ) {
            // Select is set to empty string on purpose
            // This is to test IE's treatment of not explictly
            // setting a boolean content attribute,
            // since its presence should be enough
            // http://bugs.jquery.com/ticket/12359
            div.innerHTML = "<select><option selected=''></option></select>";

            // IE8 - Some boolean attributes are not treated correctly
            if ( !div.querySelectorAll("[selected]").length ) {
                rbuggyQSA.push( "\\[" + whitespace + "*(?:checked|disabled|ismap|multiple|readonly|selected|value)" );
            }

            // Webkit/Opera - :checked should return selected option elements
            // http://www.w3.org/TR/2011/REC-css3-selectors-20110929/#checked
            // IE8 throws error here and will not see later tests
            if ( !div.querySelectorAll(":checked").length ) {
                rbuggyQSA.push(":checked");
            }
        });

        assert(function( div ) {

            // Opera 10-12/IE8 - ^= $= *= and empty values
            // Should not select anything
            div.innerHTML = "<input type='hidden' i=''/>";
            if ( div.querySelectorAll("[i^='']").length ) {
                rbuggyQSA.push( "[*^$]=" + whitespace + "*(?:\"\"|'')" );
            }

            // FF 3.5 - :enabled/:disabled and hidden elements (hidden elements are still enabled)
            // IE8 throws error here and will not see later tests
            if ( !div.querySelectorAll(":enabled").length ) {
                rbuggyQSA.push( ":enabled", ":disabled" );
            }

            // Opera 10-11 does not throw on post-comma invalid pseudos
            div.querySelectorAll("*,:x");
            rbuggyQSA.push(",.*:");
        });
    }

    if ( (support.matchesSelector = isNative( (matches = docElem.matchesSelector ||
        docElem.mozMatchesSelector ||
        docElem.webkitMatchesSelector ||
        docElem.oMatchesSelector ||
        docElem.msMatchesSelector) )) ) {

        assert(function( div ) {
            // Check to see if it's possible to do matchesSelector
            // on a disconnected node (IE 9)
            support.disconnectedMatch = matches.call( div, "div" );

            // This should fail with an exception
            // Gecko does not error, returns false instead
            matches.call( div, "[s!='']:x" );
            rbuggyMatches.push( "!=", pseudos );
        });
    }

    rbuggyQSA = new RegExp( rbuggyQSA.join("|") );
    rbuggyMatches = new RegExp( rbuggyMatches.join("|") );

    // Element contains another
    // Purposefully does not implement inclusive descendent
    // As in, an element does not contain itself
    contains = isNative(docElem.contains) || docElem.compareDocumentPosition ?
        function( a, b ) {
            var adown = a.nodeType === 9 ? a.documentElement : a,
                bup = b && b.parentNode;
            return a === bup || !!( bup && bup.nodeType === 1 && (
                adown.contains ?
                    adown.contains( bup ) :
                    a.compareDocumentPosition && a.compareDocumentPosition( bup ) & 16
            ));
        } :
        function( a, b ) {
            if ( b ) {
                while ( (b = b.parentNode) ) {
                    if ( b === a ) {
                        return true;
                    }
                }
            }
            return false;
        };

    // Document order sorting
    sortOrder = docElem.compareDocumentPosition ?
    function( a, b ) {
        var compare;

        if ( a === b ) {
            hasDuplicate = true;
            return 0;
        }

        if ( (compare = b.compareDocumentPosition && a.compareDocumentPosition && a.compareDocumentPosition( b )) ) {
            if ( compare & 1 || a.parentNode && a.parentNode.nodeType === 11 ) {
                if ( a === doc || contains( preferredDoc, a ) ) {
                    return -1;
                }
                if ( b === doc || contains( preferredDoc, b ) ) {
                    return 1;
                }
                return 0;
            }
            return compare & 4 ? -1 : 1;
        }

        return a.compareDocumentPosition ? -1 : 1;
    } :
    function( a, b ) {
        var cur,
            i = 0,
            aup = a.parentNode,
            bup = b.parentNode,
            ap = [ a ],
            bp = [ b ];

        // Exit early if the nodes are identical
        if ( a === b ) {
            hasDuplicate = true;
            return 0;

        // Parentless nodes are either documents or disconnected
        } else if ( !aup || !bup ) {
            return a === doc ? -1 :
                b === doc ? 1 :
                aup ? -1 :
                bup ? 1 :
                0;

        // If the nodes are siblings, we can do a quick check
        } else if ( aup === bup ) {
            return siblingCheck( a, b );
        }

        // Otherwise we need full lists of their ancestors for comparison
        cur = a;
        while ( (cur = cur.parentNode) ) {
            ap.unshift( cur );
        }
        cur = b;
        while ( (cur = cur.parentNode) ) {
            bp.unshift( cur );
        }

        // Walk down the tree looking for a discrepancy
        while ( ap[i] === bp[i] ) {
            i++;
        }

        return i ?
            // Do a sibling check if the nodes have a common ancestor
            siblingCheck( ap[i], bp[i] ) :

            // Otherwise nodes in our document sort first
            ap[i] === preferredDoc ? -1 :
            bp[i] === preferredDoc ? 1 :
            0;
    };

    // Always assume the presence of duplicates if sort doesn't
    // pass them to our comparison function (as in Google Chrome).
    hasDuplicate = false;
    [0, 0].sort( sortOrder );
    support.detectDuplicates = hasDuplicate;

    return document;
};

Sizzle.matches = function( expr, elements ) {
    return Sizzle( expr, null, null, elements );
};

Sizzle.matchesSelector = function( elem, expr ) {
    // Set document vars if needed
    if ( ( elem.ownerDocument || elem ) !== document ) {
        setDocument( elem );
    }

    // Make sure that attribute selectors are quoted
    expr = expr.replace( rattributeQuotes, "='$1']" );

    // rbuggyQSA always contains :focus, so no need for an existence check
    if ( support.matchesSelector && !documentIsXML && (!rbuggyMatches || !rbuggyMatches.test(expr)) && !rbuggyQSA.test(expr) ) {
        try {
            var ret = matches.call( elem, expr );

            // IE 9's matchesSelector returns false on disconnected nodes
            if ( ret || support.disconnectedMatch ||
                    // As well, disconnected nodes are said to be in a document
                    // fragment in IE 9
                    elem.document && elem.document.nodeType !== 11 ) {
                return ret;
            }
        } catch(e) {}
    }

    return Sizzle( expr, document, null, [elem] ).length > 0;
};

Sizzle.contains = function( context, elem ) {
    // Set document vars if needed
    if ( ( context.ownerDocument || context ) !== document ) {
        setDocument( context );
    }
    return contains( context, elem );
};

Sizzle.attr = function( elem, name ) {
    var val;

    // Set document vars if needed
    if ( ( elem.ownerDocument || elem ) !== document ) {
        setDocument( elem );
    }

    if ( !documentIsXML ) {
        name = name.toLowerCase();
    }
    if ( (val = Expr.attrHandle[ name ]) ) {
        return val( elem );
    }
    if ( documentIsXML || support.attributes ) {
        return elem.getAttribute( name );
    }
    return ( (val = elem.getAttributeNode( name )) || elem.getAttribute( name ) ) && elem[ name ] === true ?
        name :
        val && val.specified ? val.value : null;
};

Sizzle.error = function( msg ) {
    throw new Error( "Syntax error, unrecognized expression: " + msg );
};

// Document sorting and removing duplicates
Sizzle.uniqueSort = function( results ) {
    var elem,
        duplicates = [],
        i = 1,
        j = 0;

    // Unless we *know* we can detect duplicates, assume their presence
    hasDuplicate = !support.detectDuplicates;
    results.sort( sortOrder );

    if ( hasDuplicate ) {
        for ( ; (elem = results[i]); i++ ) {
            if ( elem === results[ i - 1 ] ) {
                j = duplicates.push( i );
            }
        }
        while ( j-- ) {
            results.splice( duplicates[ j ], 1 );
        }
    }

    return results;
};

function siblingCheck( a, b ) {
    var cur = b && a,
        diff = cur && ( ~b.sourceIndex || MAX_NEGATIVE ) - ( ~a.sourceIndex || MAX_NEGATIVE );

    // Use IE sourceIndex if available on both nodes
    if ( diff ) {
        return diff;
    }

    // Check if b follows a
    if ( cur ) {
        while ( (cur = cur.nextSibling) ) {
            if ( cur === b ) {
                return -1;
            }
        }
    }

    return a ? 1 : -1;
}

// Returns a function to use in pseudos for input types
function createInputPseudo( type ) {
    return function( elem ) {
        var name = elem.nodeName.toLowerCase();
        return name === "input" && elem.type === type;
    };
}

// Returns a function to use in pseudos for buttons
function createButtonPseudo( type ) {
    return function( elem ) {
        var name = elem.nodeName.toLowerCase();
        return (name === "input" || name === "button") && elem.type === type;
    };
}

// Returns a function to use in pseudos for positionals
function createPositionalPseudo( fn ) {
    return markFunction(function( argument ) {
        argument = +argument;
        return markFunction(function( seed, matches ) {
            var j,
                matchIndexes = fn( [], seed.length, argument ),
                i = matchIndexes.length;

            // Match elements found at the specified indexes
            while ( i-- ) {
                if ( seed[ (j = matchIndexes[i]) ] ) {
                    seed[j] = !(matches[j] = seed[j]);
                }
            }
        });
    });
}

/**
 * Utility function for retrieving the text value of an array of DOM nodes
 * @param {Array|Element} elem
 */
getText = Sizzle.getText = function( elem ) {
    var node,
        ret = "",
        i = 0,
        nodeType = elem.nodeType;

    if ( !nodeType ) {
        // If no nodeType, this is expected to be an array
        for ( ; (node = elem[i]); i++ ) {
            // Do not traverse comment nodes
            ret += getText( node );
        }
    } else if ( nodeType === 1 || nodeType === 9 || nodeType === 11 ) {
        // Use textContent for elements
        // innerText usage removed for consistency of new lines (see #11153)
        if ( typeof elem.textContent === "string" ) {
            return elem.textContent;
        } else {
            // Traverse its children
            for ( elem = elem.firstChild; elem; elem = elem.nextSibling ) {
                ret += getText( elem );
            }
        }
    } else if ( nodeType === 3 || nodeType === 4 ) {
        return elem.nodeValue;
    }
    // Do not include comment or processing instruction nodes

    return ret;
};

Expr = Sizzle.selectors = {

    // Can be adjusted by the user
    cacheLength: 50,

    createPseudo: markFunction,

    match: matchExpr,

    find: {},

    relative: {
        ">": { dir: "parentNode", first: true },
        " ": { dir: "parentNode" },
        "+": { dir: "previousSibling", first: true },
        "~": { dir: "previousSibling" }
    },

    preFilter: {
        "ATTR": function( match ) {
            match[1] = match[1].replace( runescape, funescape );

            // Move the given value to match[3] whether quoted or unquoted
            match[3] = ( match[4] || match[5] || "" ).replace( runescape, funescape );

            if ( match[2] === "~=" ) {
                match[3] = " " + match[3] + " ";
            }

            return match.slice( 0, 4 );
        },

        "CHILD": function( match ) {
            /* matches from matchExpr["CHILD"]
                1 type (only|nth|...)
                2 what (child|of-type)
                3 argument (even|odd|\d*|\d*n([+-]\d+)?|...)
                4 xn-component of xn+y argument ([+-]?\d*n|)
                5 sign of xn-component
                6 x of xn-component
                7 sign of y-component
                8 y of y-component
            */
            match[1] = match[1].toLowerCase();

            if ( match[1].slice( 0, 3 ) === "nth" ) {
                // nth-* requires argument
                if ( !match[3] ) {
                    Sizzle.error( match[0] );
                }

                // numeric x and y parameters for Expr.filter.CHILD
                // remember that false/true cast respectively to 0/1
                match[4] = +( match[4] ? match[5] + (match[6] || 1) : 2 * ( match[3] === "even" || match[3] === "odd" ) );
                match[5] = +( ( match[7] + match[8] ) || match[3] === "odd" );

            // other types prohibit arguments
            } else if ( match[3] ) {
                Sizzle.error( match[0] );
            }

            return match;
        },

        "PSEUDO": function( match ) {
            var excess,
                unquoted = !match[5] && match[2];

            if ( matchExpr["CHILD"].test( match[0] ) ) {
                return null;
            }

            // Accept quoted arguments as-is
            if ( match[4] ) {
                match[2] = match[4];

            // Strip excess characters from unquoted arguments
            } else if ( unquoted && rpseudo.test( unquoted ) &&
                // Get excess from tokenize (recursively)
                (excess = tokenize( unquoted, true )) &&
                // advance to the next closing parenthesis
                (excess = unquoted.indexOf( ")", unquoted.length - excess ) - unquoted.length) ) {

                // excess is a negative index
                match[0] = match[0].slice( 0, excess );
                match[2] = unquoted.slice( 0, excess );
            }

            // Return only captures needed by the pseudo filter method (type and argument)
            return match.slice( 0, 3 );
        }
    },

    filter: {

        "TAG": function( nodeName ) {
            if ( nodeName === "*" ) {
                return function() { return true; };
            }

            nodeName = nodeName.replace( runescape, funescape ).toLowerCase();
            return function( elem ) {
                return elem.nodeName && elem.nodeName.toLowerCase() === nodeName;
            };
        },

        "CLASS": function( className ) {
            var pattern = classCache[ className + " " ];

            return pattern ||
                (pattern = new RegExp( "(^|" + whitespace + ")" + className + "(" + whitespace + "|$)" )) &&
                classCache( className, function( elem ) {
                    return pattern.test( elem.className || (typeof elem.getAttribute !== strundefined && elem.getAttribute("class")) || "" );
                });
        },

        "ATTR": function( name, operator, check ) {
            return function( elem ) {
                var result = Sizzle.attr( elem, name );

                if ( result == null ) {
                    return operator === "!=";
                }
                if ( !operator ) {
                    return true;
                }

                result += "";

                return operator === "=" ? result === check :
                    operator === "!=" ? result !== check :
                    operator === "^=" ? check && result.indexOf( check ) === 0 :
                    operator === "*=" ? check && result.indexOf( check ) > -1 :
                    operator === "$=" ? check && result.slice( -check.length ) === check :
                    operator === "~=" ? ( " " + result + " " ).indexOf( check ) > -1 :
                    operator === "|=" ? result === check || result.slice( 0, check.length + 1 ) === check + "-" :
                    false;
            };
        },

        "CHILD": function( type, what, argument, first, last ) {
            var simple = type.slice( 0, 3 ) !== "nth",
                forward = type.slice( -4 ) !== "last",
                ofType = what === "of-type";

            return first === 1 && last === 0 ?

                // Shortcut for :nth-*(n)
                function( elem ) {
                    return !!elem.parentNode;
                } :

                function( elem, context, xml ) {
                    var cache, outerCache, node, diff, nodeIndex, start,
                        dir = simple !== forward ? "nextSibling" : "previousSibling",
                        parent = elem.parentNode,
                        name = ofType && elem.nodeName.toLowerCase(),
                        useCache = !xml && !ofType;

                    if ( parent ) {

                        // :(first|last|only)-(child|of-type)
                        if ( simple ) {
                            while ( dir ) {
                                node = elem;
                                while ( (node = node[ dir ]) ) {
                                    if ( ofType ? node.nodeName.toLowerCase() === name : node.nodeType === 1 ) {
                                        return false;
                                    }
                                }
                                // Reverse direction for :only-* (if we haven't yet done so)
                                start = dir = type === "only" && !start && "nextSibling";
                            }
                            return true;
                        }

                        start = [ forward ? parent.firstChild : parent.lastChild ];

                        // non-xml :nth-child(...) stores cache data on `parent`
                        if ( forward && useCache ) {
                            // Seek `elem` from a previously-cached index
                            outerCache = parent[ expando ] || (parent[ expando ] = {});
                            cache = outerCache[ type ] || [];
                            nodeIndex = cache[0] === dirruns && cache[1];
                            diff = cache[0] === dirruns && cache[2];
                            node = nodeIndex && parent.childNodes[ nodeIndex ];

                            while ( (node = ++nodeIndex && node && node[ dir ] ||

                                // Fallback to seeking `elem` from the start
                                (diff = nodeIndex = 0) || start.pop()) ) {

                                // When found, cache indexes on `parent` and break
                                if ( node.nodeType === 1 && ++diff && node === elem ) {
                                    outerCache[ type ] = [ dirruns, nodeIndex, diff ];
                                    break;
                                }
                            }

                        // Use previously-cached element index if available
                        } else if ( useCache && (cache = (elem[ expando ] || (elem[ expando ] = {}))[ type ]) && cache[0] === dirruns ) {
                            diff = cache[1];

                        // xml :nth-child(...) or :nth-last-child(...) or :nth(-last)?-of-type(...)
                        } else {
                            // Use the same loop as above to seek `elem` from the start
                            while ( (node = ++nodeIndex && node && node[ dir ] ||
                                (diff = nodeIndex = 0) || start.pop()) ) {

                                if ( ( ofType ? node.nodeName.toLowerCase() === name : node.nodeType === 1 ) && ++diff ) {
                                    // Cache the index of each encountered element
                                    if ( useCache ) {
                                        (node[ expando ] || (node[ expando ] = {}))[ type ] = [ dirruns, diff ];
                                    }

                                    if ( node === elem ) {
                                        break;
                                    }
                                }
                            }
                        }

                        // Incorporate the offset, then check against cycle size
                        diff -= last;
                        return diff === first || ( diff % first === 0 && diff / first >= 0 );
                    }
                };
        },

        "PSEUDO": function( pseudo, argument ) {
            // pseudo-class names are case-insensitive
            // http://www.w3.org/TR/selectors/#pseudo-classes
            // Prioritize by case sensitivity in case custom pseudos are added with uppercase letters
            // Remember that setFilters inherits from pseudos
            var args,
                fn = Expr.pseudos[ pseudo ] || Expr.setFilters[ pseudo.toLowerCase() ] ||
                    Sizzle.error( "unsupported pseudo: " + pseudo );

            // The user may use createPseudo to indicate that
            // arguments are needed to create the filter function
            // just as Sizzle does
            if ( fn[ expando ] ) {
                return fn( argument );
            }

            // But maintain support for old signatures
            if ( fn.length > 1 ) {
                args = [ pseudo, pseudo, "", argument ];
                return Expr.setFilters.hasOwnProperty( pseudo.toLowerCase() ) ?
                    markFunction(function( seed, matches ) {
                        var idx,
                            matched = fn( seed, argument ),
                            i = matched.length;
                        while ( i-- ) {
                            idx = indexOf.call( seed, matched[i] );
                            seed[ idx ] = !( matches[ idx ] = matched[i] );
                        }
                    }) :
                    function( elem ) {
                        return fn( elem, 0, args );
                    };
            }

            return fn;
        }
    },

    pseudos: {
        // Potentially complex pseudos
        "not": markFunction(function( selector ) {
            // Trim the selector passed to compile
            // to avoid treating leading and trailing
            // spaces as combinators
            var input = [],
                results = [],
                matcher = compile( selector.replace( rtrim, "$1" ) );

            return matcher[ expando ] ?
                markFunction(function( seed, matches, context, xml ) {
                    var elem,
                        unmatched = matcher( seed, null, xml, [] ),
                        i = seed.length;

                    // Match elements unmatched by `matcher`
                    while ( i-- ) {
                        if ( (elem = unmatched[i]) ) {
                            seed[i] = !(matches[i] = elem);
                        }
                    }
                }) :
                function( elem, context, xml ) {
                    input[0] = elem;
                    matcher( input, null, xml, results );
                    return !results.pop();
                };
        }),

        "has": markFunction(function( selector ) {
            return function( elem ) {
                return Sizzle( selector, elem ).length > 0;
            };
        }),

        "contains": markFunction(function( text ) {
            return function( elem ) {
                return ( elem.textContent || elem.innerText || getText( elem ) ).indexOf( text ) > -1;
            };
        }),

        // "Whether an element is represented by a :lang() selector
        // is based solely on the element's language value
        // being equal to the identifier C,
        // or beginning with the identifier C immediately followed by "-".
        // The matching of C against the element's language value is performed case-insensitively.
        // The identifier C does not have to be a valid language name."
        // http://www.w3.org/TR/selectors/#lang-pseudo
        "lang": markFunction( function( lang ) {
            // lang value must be a valid identifider
            if ( !ridentifier.test(lang || "") ) {
                Sizzle.error( "unsupported lang: " + lang );
            }
            lang = lang.replace( runescape, funescape ).toLowerCase();
            return function( elem ) {
                var elemLang;
                do {
                    if ( (elemLang = documentIsXML ?
                        elem.getAttribute("xml:lang") || elem.getAttribute("lang") :
                        elem.lang) ) {

                        elemLang = elemLang.toLowerCase();
                        return elemLang === lang || elemLang.indexOf( lang + "-" ) === 0;
                    }
                } while ( (elem = elem.parentNode) && elem.nodeType === 1 );
                return false;
            };
        }),

        // Miscellaneous
        "target": function( elem ) {
            var hash = window.location && window.location.hash;
            return hash && hash.slice( 1 ) === elem.id;
        },

        "root": function( elem ) {
            return elem === docElem;
        },

        "focus": function( elem ) {
            return elem === document.activeElement && (!document.hasFocus || document.hasFocus()) && !!(elem.type || elem.href || ~elem.tabIndex);
        },

        // Boolean properties
        "enabled": function( elem ) {
            return elem.disabled === false;
        },

        "disabled": function( elem ) {
            return elem.disabled === true;
        },

        "checked": function( elem ) {
            // In CSS3, :checked should return both checked and selected elements
            // http://www.w3.org/TR/2011/REC-css3-selectors-20110929/#checked
            var nodeName = elem.nodeName.toLowerCase();
            return (nodeName === "input" && !!elem.checked) || (nodeName === "option" && !!elem.selected);
        },

        "selected": function( elem ) {
            // Accessing this property makes selected-by-default
            // options in Safari work properly
            if ( elem.parentNode ) {
                elem.parentNode.selectedIndex;
            }

            return elem.selected === true;
        },

        // Contents
        "empty": function( elem ) {
            // http://www.w3.org/TR/selectors/#empty-pseudo
            // :empty is only affected by element nodes and content nodes(including text(3), cdata(4)),
            //   not comment, processing instructions, or others
            // Thanks to Diego Perini for the nodeName shortcut
            //   Greater than "@" means alpha characters (specifically not starting with "#" or "?")
            for ( elem = elem.firstChild; elem; elem = elem.nextSibling ) {
                if ( elem.nodeName > "@" || elem.nodeType === 3 || elem.nodeType === 4 ) {
                    return false;
                }
            }
            return true;
        },

        "parent": function( elem ) {
            return !Expr.pseudos["empty"]( elem );
        },

        // Element/input types
        "header": function( elem ) {
            return rheader.test( elem.nodeName );
        },

        "input": function( elem ) {
            return rinputs.test( elem.nodeName );
        },

        "button": function( elem ) {
            var name = elem.nodeName.toLowerCase();
            return name === "input" && elem.type === "button" || name === "button";
        },

        "text": function( elem ) {
            var attr;
            // IE6 and 7 will map elem.type to 'text' for new HTML5 types (search, etc)
            // use getAttribute instead to test this case
            return elem.nodeName.toLowerCase() === "input" &&
                elem.type === "text" &&
                ( (attr = elem.getAttribute("type")) == null || attr.toLowerCase() === elem.type );
        },

        // Position-in-collection
        "first": createPositionalPseudo(function() {
            return [ 0 ];
        }),

        "last": createPositionalPseudo(function( matchIndexes, length ) {
            return [ length - 1 ];
        }),

        "eq": createPositionalPseudo(function( matchIndexes, length, argument ) {
            return [ argument < 0 ? argument + length : argument ];
        }),

        "even": createPositionalPseudo(function( matchIndexes, length ) {
            var i = 0;
            for ( ; i < length; i += 2 ) {
                matchIndexes.push( i );
            }
            return matchIndexes;
        }),

        "odd": createPositionalPseudo(function( matchIndexes, length ) {
            var i = 1;
            for ( ; i < length; i += 2 ) {
                matchIndexes.push( i );
            }
            return matchIndexes;
        }),

        "lt": createPositionalPseudo(function( matchIndexes, length, argument ) {
            var i = argument < 0 ? argument + length : argument;
            for ( ; --i >= 0; ) {
                matchIndexes.push( i );
            }
            return matchIndexes;
        }),

        "gt": createPositionalPseudo(function( matchIndexes, length, argument ) {
            var i = argument < 0 ? argument + length : argument;
            for ( ; ++i < length; ) {
                matchIndexes.push( i );
            }
            return matchIndexes;
        })
    }
};

// Add button/input type pseudos
for ( i in { radio: true, checkbox: true, file: true, password: true, image: true } ) {
    Expr.pseudos[ i ] = createInputPseudo( i );
}
for ( i in { submit: true, reset: true } ) {
    Expr.pseudos[ i ] = createButtonPseudo( i );
}

function tokenize( selector, parseOnly ) {
    var matched, match, tokens, type,
        soFar, groups, preFilters,
        cached = tokenCache[ selector + " " ];

    if ( cached ) {
        return parseOnly ? 0 : cached.slice( 0 );
    }

    soFar = selector;
    groups = [];
    preFilters = Expr.preFilter;

    while ( soFar ) {

        // Comma and first run
        if ( !matched || (match = rcomma.exec( soFar )) ) {
            if ( match ) {
                // Don't consume trailing commas as valid
                soFar = soFar.slice( match[0].length ) || soFar;
            }
            groups.push( tokens = [] );
        }

        matched = false;

        // Combinators
        if ( (match = rcombinators.exec( soFar )) ) {
            matched = match.shift();
            tokens.push( {
                value: matched,
                // Cast descendant combinators to space
                type: match[0].replace( rtrim, " " )
            } );
            soFar = soFar.slice( matched.length );
        }

        // Filters
        for ( type in Expr.filter ) {
            if ( (match = matchExpr[ type ].exec( soFar )) && (!preFilters[ type ] ||
                (match = preFilters[ type ]( match ))) ) {
                matched = match.shift();
                tokens.push( {
                    value: matched,
                    type: type,
                    matches: match
                } );
                soFar = soFar.slice( matched.length );
            }
        }

        if ( !matched ) {
            break;
        }
    }

    // Return the length of the invalid excess
    // if we're just parsing
    // Otherwise, throw an error or return tokens
    return parseOnly ?
        soFar.length :
        soFar ?
            Sizzle.error( selector ) :
            // Cache the tokens
            tokenCache( selector, groups ).slice( 0 );
}

function toSelector( tokens ) {
    var i = 0,
        len = tokens.length,
        selector = "";
    for ( ; i < len; i++ ) {
        selector += tokens[i].value;
    }
    return selector;
}

function addCombinator( matcher, combinator, base ) {
    var dir = combinator.dir,
        checkNonElements = base && dir === "parentNode",
        doneName = done++;

    return combinator.first ?
        // Check against closest ancestor/preceding element
        function( elem, context, xml ) {
            while ( (elem = elem[ dir ]) ) {
                if ( elem.nodeType === 1 || checkNonElements ) {
                    return matcher( elem, context, xml );
                }
            }
        } :

        // Check against all ancestor/preceding elements
        function( elem, context, xml ) {
            var data, cache, outerCache,
                dirkey = dirruns + " " + doneName;

            // We can't set arbitrary data on XML nodes, so they don't benefit from dir caching
            if ( xml ) {
                while ( (elem = elem[ dir ]) ) {
                    if ( elem.nodeType === 1 || checkNonElements ) {
                        if ( matcher( elem, context, xml ) ) {
                            return true;
                        }
                    }
                }
            } else {
                while ( (elem = elem[ dir ]) ) {
                    if ( elem.nodeType === 1 || checkNonElements ) {
                        outerCache = elem[ expando ] || (elem[ expando ] = {});
                        if ( (cache = outerCache[ dir ]) && cache[0] === dirkey ) {
                            if ( (data = cache[1]) === true || data === cachedruns ) {
                                return data === true;
                            }
                        } else {
                            cache = outerCache[ dir ] = [ dirkey ];
                            cache[1] = matcher( elem, context, xml ) || cachedruns;
                            if ( cache[1] === true ) {
                                return true;
                            }
                        }
                    }
                }
            }
        };
}

function elementMatcher( matchers ) {
    return matchers.length > 1 ?
        function( elem, context, xml ) {
            var i = matchers.length;
            while ( i-- ) {
                if ( !matchers[i]( elem, context, xml ) ) {
                    return false;
                }
            }
            return true;
        } :
        matchers[0];
}

function condense( unmatched, map, filter, context, xml ) {
    var elem,
        newUnmatched = [],
        i = 0,
        len = unmatched.length,
        mapped = map != null;

    for ( ; i < len; i++ ) {
        if ( (elem = unmatched[i]) ) {
            if ( !filter || filter( elem, context, xml ) ) {
                newUnmatched.push( elem );
                if ( mapped ) {
                    map.push( i );
                }
            }
        }
    }

    return newUnmatched;
}

function setMatcher( preFilter, selector, matcher, postFilter, postFinder, postSelector ) {
    if ( postFilter && !postFilter[ expando ] ) {
        postFilter = setMatcher( postFilter );
    }
    if ( postFinder && !postFinder[ expando ] ) {
        postFinder = setMatcher( postFinder, postSelector );
    }
    return markFunction(function( seed, results, context, xml ) {
        var temp, i, elem,
            preMap = [],
            postMap = [],
            preexisting = results.length,

            // Get initial elements from seed or context
            elems = seed || multipleContexts( selector || "*", context.nodeType ? [ context ] : context, [] ),

            // Prefilter to get matcher input, preserving a map for seed-results synchronization
            matcherIn = preFilter && ( seed || !selector ) ?
                condense( elems, preMap, preFilter, context, xml ) :
                elems,

            matcherOut = matcher ?
                // If we have a postFinder, or filtered seed, or non-seed postFilter or preexisting results,
                postFinder || ( seed ? preFilter : preexisting || postFilter ) ?

                    // ...intermediate processing is necessary
                    [] :

                    // ...otherwise use results directly
                    results :
                matcherIn;

        // Find primary matches
        if ( matcher ) {
            matcher( matcherIn, matcherOut, context, xml );
        }

        // Apply postFilter
        if ( postFilter ) {
            temp = condense( matcherOut, postMap );
            postFilter( temp, [], context, xml );

            // Un-match failing elements by moving them back to matcherIn
            i = temp.length;
            while ( i-- ) {
                if ( (elem = temp[i]) ) {
                    matcherOut[ postMap[i] ] = !(matcherIn[ postMap[i] ] = elem);
                }
            }
        }

        if ( seed ) {
            if ( postFinder || preFilter ) {
                if ( postFinder ) {
                    // Get the final matcherOut by condensing this intermediate into postFinder contexts
                    temp = [];
                    i = matcherOut.length;
                    while ( i-- ) {
                        if ( (elem = matcherOut[i]) ) {
                            // Restore matcherIn since elem is not yet a final match
                            temp.push( (matcherIn[i] = elem) );
                        }
                    }
                    postFinder( null, (matcherOut = []), temp, xml );
                }

                // Move matched elements from seed to results to keep them synchronized
                i = matcherOut.length;
                while ( i-- ) {
                    if ( (elem = matcherOut[i]) &&
                        (temp = postFinder ? indexOf.call( seed, elem ) : preMap[i]) > -1 ) {

                        seed[temp] = !(results[temp] = elem);
                    }
                }
            }

        // Add elements to results, through postFinder if defined
        } else {
            matcherOut = condense(
                matcherOut === results ?
                    matcherOut.splice( preexisting, matcherOut.length ) :
                    matcherOut
            );
            if ( postFinder ) {
                postFinder( null, results, matcherOut, xml );
            } else {
                push.apply( results, matcherOut );
            }
        }
    });
}

function matcherFromTokens( tokens ) {
    var checkContext, matcher, j,
        len = tokens.length,
        leadingRelative = Expr.relative[ tokens[0].type ],
        implicitRelative = leadingRelative || Expr.relative[" "],
        i = leadingRelative ? 1 : 0,

        // The foundational matcher ensures that elements are reachable from top-level context(s)
        matchContext = addCombinator( function( elem ) {
            return elem === checkContext;
        }, implicitRelative, true ),
        matchAnyContext = addCombinator( function( elem ) {
            return indexOf.call( checkContext, elem ) > -1;
        }, implicitRelative, true ),
        matchers = [ function( elem, context, xml ) {
            return ( !leadingRelative && ( xml || context !== outermostContext ) ) || (
                (checkContext = context).nodeType ?
                    matchContext( elem, context, xml ) :
                    matchAnyContext( elem, context, xml ) );
        } ];

    for ( ; i < len; i++ ) {
        if ( (matcher = Expr.relative[ tokens[i].type ]) ) {
            matchers = [ addCombinator(elementMatcher( matchers ), matcher) ];
        } else {
            matcher = Expr.filter[ tokens[i].type ].apply( null, tokens[i].matches );

            // Return special upon seeing a positional matcher
            if ( matcher[ expando ] ) {
                // Find the next relative operator (if any) for proper handling
                j = ++i;
                for ( ; j < len; j++ ) {
                    if ( Expr.relative[ tokens[j].type ] ) {
                        break;
                    }
                }
                return setMatcher(
                    i > 1 && elementMatcher( matchers ),
                    i > 1 && toSelector( tokens.slice( 0, i - 1 ) ).replace( rtrim, "$1" ),
                    matcher,
                    i < j && matcherFromTokens( tokens.slice( i, j ) ),
                    j < len && matcherFromTokens( (tokens = tokens.slice( j )) ),
                    j < len && toSelector( tokens )
                );
            }
            matchers.push( matcher );
        }
    }

    return elementMatcher( matchers );
}

function matcherFromGroupMatchers( elementMatchers, setMatchers ) {
    // A counter to specify which element is currently being matched
    var matcherCachedRuns = 0,
        bySet = setMatchers.length > 0,
        byElement = elementMatchers.length > 0,
        superMatcher = function( seed, context, xml, results, expandContext ) {
            var elem, j, matcher,
                setMatched = [],
                matchedCount = 0,
                i = "0",
                unmatched = seed && [],
                outermost = expandContext != null,
                contextBackup = outermostContext,
                // We must always have either seed elements or context
                elems = seed || byElement && Expr.find["TAG"]( "*", expandContext && context.parentNode || context ),
                // Use integer dirruns iff this is the outermost matcher
                dirrunsUnique = (dirruns += contextBackup == null ? 1 : Math.random() || 0.1);

            if ( outermost ) {
                outermostContext = context !== document && context;
                cachedruns = matcherCachedRuns;
            }

            // Add elements passing elementMatchers directly to results
            // Keep `i` a string if there are no elements so `matchedCount` will be "00" below
            for ( ; (elem = elems[i]) != null; i++ ) {
                if ( byElement && elem ) {
                    j = 0;
                    while ( (matcher = elementMatchers[j++]) ) {
                        if ( matcher( elem, context, xml ) ) {
                            results.push( elem );
                            break;
                        }
                    }
                    if ( outermost ) {
                        dirruns = dirrunsUnique;
                        cachedruns = ++matcherCachedRuns;
                    }
                }

                // Track unmatched elements for set filters
                if ( bySet ) {
                    // They will have gone through all possible matchers
                    if ( (elem = !matcher && elem) ) {
                        matchedCount--;
                    }

                    // Lengthen the array for every element, matched or not
                    if ( seed ) {
                        unmatched.push( elem );
                    }
                }
            }

            // Apply set filters to unmatched elements
            matchedCount += i;
            if ( bySet && i !== matchedCount ) {
                j = 0;
                while ( (matcher = setMatchers[j++]) ) {
                    matcher( unmatched, setMatched, context, xml );
                }

                if ( seed ) {
                    // Reintegrate element matches to eliminate the need for sorting
                    if ( matchedCount > 0 ) {
                        while ( i-- ) {
                            if ( !(unmatched[i] || setMatched[i]) ) {
                                setMatched[i] = pop.call( results );
                            }
                        }
                    }

                    // Discard index placeholder values to get only actual matches
                    setMatched = condense( setMatched );
                }

                // Add matches to results
                push.apply( results, setMatched );

                // Seedless set matches succeeding multiple successful matchers stipulate sorting
                if ( outermost && !seed && setMatched.length > 0 &&
                    ( matchedCount + setMatchers.length ) > 1 ) {

                    Sizzle.uniqueSort( results );
                }
            }

            // Override manipulation of globals by nested matchers
            if ( outermost ) {
                dirruns = dirrunsUnique;
                outermostContext = contextBackup;
            }

            return unmatched;
        };

    return bySet ?
        markFunction( superMatcher ) :
        superMatcher;
}

compile = Sizzle.compile = function( selector, group /* Internal Use Only */ ) {
    var i,
        setMatchers = [],
        elementMatchers = [],
        cached = compilerCache[ selector + " " ];

    if ( !cached ) {
        // Generate a function of recursive functions that can be used to check each element
        if ( !group ) {
            group = tokenize( selector );
        }
        i = group.length;
        while ( i-- ) {
            cached = matcherFromTokens( group[i] );
            if ( cached[ expando ] ) {
                setMatchers.push( cached );
            } else {
                elementMatchers.push( cached );
            }
        }

        // Cache the compiled function
        cached = compilerCache( selector, matcherFromGroupMatchers( elementMatchers, setMatchers ) );
    }
    return cached;
};

function multipleContexts( selector, contexts, results ) {
    var i = 0,
        len = contexts.length;
    for ( ; i < len; i++ ) {
        Sizzle( selector, contexts[i], results );
    }
    return results;
}

function select( selector, context, results, seed ) {
    var i, tokens, token, type, find,
        match = tokenize( selector );

    if ( !seed ) {
        // Try to minimize operations if there is only one group
        if ( match.length === 1 ) {

            // Take a shortcut and set the context if the root selector is an ID
            tokens = match[0] = match[0].slice( 0 );
            if ( tokens.length > 2 && (token = tokens[0]).type === "ID" &&
                    context.nodeType === 9 && !documentIsXML &&
                    Expr.relative[ tokens[1].type ] ) {

                context = Expr.find["ID"]( token.matches[0].replace( runescape, funescape ), context )[0];
                if ( !context ) {
                    return results;
                }

                selector = selector.slice( tokens.shift().value.length );
            }

            // Fetch a seed set for right-to-left matching
            i = matchExpr["needsContext"].test( selector ) ? 0 : tokens.length;
            while ( i-- ) {
                token = tokens[i];

                // Abort if we hit a combinator
                if ( Expr.relative[ (type = token.type) ] ) {
                    break;
                }
                if ( (find = Expr.find[ type ]) ) {
                    // Search, expanding context for leading sibling combinators
                    if ( (seed = find(
                        token.matches[0].replace( runescape, funescape ),
                        rsibling.test( tokens[0].type ) && context.parentNode || context
                    )) ) {

                        // If seed is empty or no tokens remain, we can return early
                        tokens.splice( i, 1 );
                        selector = seed.length && toSelector( tokens );
                        if ( !selector ) {
                            push.apply( results, slice.call( seed, 0 ) );
                            return results;
                        }

                        break;
                    }
                }
            }
        }
    }

    // Compile and execute a filtering function
    // Provide `match` to avoid retokenization if we modified the selector above
    compile( selector, match )(
        seed,
        context,
        documentIsXML,
        results,
        rsibling.test( selector )
    );
    return results;
}

// Deprecated
Expr.pseudos["nth"] = Expr.pseudos["eq"];

// Easy API for creating new setFilters
function setFilters() {}
Expr.filters = setFilters.prototype = Expr.pseudos;
Expr.setFilters = new setFilters();

// Initialize with the default document
setDocument();

// Override sizzle attribute retrieval
Sizzle.attr = jQuery.attr;
jQuery.find = Sizzle;
jQuery.expr = Sizzle.selectors;
jQuery.expr[":"] = jQuery.expr.pseudos;
jQuery.unique = Sizzle.uniqueSort;
jQuery.text = Sizzle.getText;
jQuery.isXMLDoc = Sizzle.isXML;
jQuery.contains = Sizzle.contains;


})( window );
var runtil = /Until$/,
    rparentsprev = /^(?:parents|prev(?:Until|All))/,
    isSimple = /^.[^:#\[\.,]*$/,
    rneedsContext = jQuery.expr.match.needsContext,
    // methods guaranteed to produce a unique set when starting from a unique set
    guaranteedUnique = {
        children: true,
        contents: true,
        next: true,
        prev: true
    };

jQuery.fn.extend({
    find: function( selector ) {
        var i, ret, self,
            len = this.length;

        if ( typeof selector !== "string" ) {
            self = this;
            return this.pushStack( jQuery( selector ).filter(function() {
                for ( i = 0; i < len; i++ ) {
                    if ( jQuery.contains( self[ i ], this ) ) {
                        return true;
                    }
                }
            }) );
        }

        ret = [];
        for ( i = 0; i < len; i++ ) {
            jQuery.find( selector, this[ i ], ret );
        }

        // Needed because $( selector, context ) becomes $( context ).find( selector )
        ret = this.pushStack( len > 1 ? jQuery.unique( ret ) : ret );
        ret.selector = ( this.selector ? this.selector + " " : "" ) + selector;
        return ret;
    },

    has: function( target ) {
        var i,
            targets = jQuery( target, this ),
            len = targets.length;

        return this.filter(function() {
            for ( i = 0; i < len; i++ ) {
                if ( jQuery.contains( this, targets[i] ) ) {
                    return true;
                }
            }
        });
    },

    not: function( selector ) {
        return this.pushStack( winnow(this, selector, false) );
    },

    filter: function( selector ) {
        return this.pushStack( winnow(this, selector, true) );
    },

    is: function( selector ) {
        return !!selector && (
            typeof selector === "string" ?
                // If this is a positional/relative selector, check membership in the returned set
                // so $("p:first").is("p:last") won't return true for a doc with two "p".
                rneedsContext.test( selector ) ?
                    jQuery( selector, this.context ).index( this[0] ) >= 0 :
                    jQuery.filter( selector, this ).length > 0 :
                this.filter( selector ).length > 0 );
    },

    closest: function( selectors, context ) {
        var cur,
            i = 0,
            l = this.length,
            ret = [],
            pos = rneedsContext.test( selectors ) || typeof selectors !== "string" ?
                jQuery( selectors, context || this.context ) :
                0;

        for ( ; i < l; i++ ) {
            cur = this[i];

            while ( cur && cur.ownerDocument && cur !== context && cur.nodeType !== 11 ) {
                if ( pos ? pos.index(cur) > -1 : jQuery.find.matchesSelector(cur, selectors) ) {
                    ret.push( cur );
                    break;
                }
                cur = cur.parentNode;
            }
        }

        return this.pushStack( ret.length > 1 ? jQuery.unique( ret ) : ret );
    },

    // Determine the position of an element within
    // the matched set of elements
    index: function( elem ) {

        // No argument, return index in parent
        if ( !elem ) {
            return ( this[0] && this[0].parentNode ) ? this.first().prevAll().length : -1;
        }

        // index in selector
        if ( typeof elem === "string" ) {
            return jQuery.inArray( this[0], jQuery( elem ) );
        }

        // Locate the position of the desired element
        return jQuery.inArray(
            // If it receives a jQuery object, the first element is used
            elem.jquery ? elem[0] : elem, this );
    },

    add: function( selector, context ) {
        var set = typeof selector === "string" ?
                jQuery( selector, context ) :
                jQuery.makeArray( selector && selector.nodeType ? [ selector ] : selector ),
            all = jQuery.merge( this.get(), set );

        return this.pushStack( jQuery.unique(all) );
    },

    addBack: function( selector ) {
        return this.add( selector == null ?
            this.prevObject : this.prevObject.filter(selector)
        );
    }
});

jQuery.fn.andSelf = jQuery.fn.addBack;

function sibling( cur, dir ) {
    do {
        cur = cur[ dir ];
    } while ( cur && cur.nodeType !== 1 );

    return cur;
}

jQuery.each({
    parent: function( elem ) {
        var parent = elem.parentNode;
        return parent && parent.nodeType !== 11 ? parent : null;
    },
    parents: function( elem ) {
        return jQuery.dir( elem, "parentNode" );
    },
    parentsUntil: function( elem, i, until ) {
        return jQuery.dir( elem, "parentNode", until );
    },
    next: function( elem ) {
        return sibling( elem, "nextSibling" );
    },
    prev: function( elem ) {
        return sibling( elem, "previousSibling" );
    },
    nextAll: function( elem ) {
        return jQuery.dir( elem, "nextSibling" );
    },
    prevAll: function( elem ) {
        return jQuery.dir( elem, "previousSibling" );
    },
    nextUntil: function( elem, i, until ) {
        return jQuery.dir( elem, "nextSibling", until );
    },
    prevUntil: function( elem, i, until ) {
        return jQuery.dir( elem, "previousSibling", until );
    },
    siblings: function( elem ) {
        return jQuery.sibling( ( elem.parentNode || {} ).firstChild, elem );
    },
    children: function( elem ) {
        return jQuery.sibling( elem.firstChild );
    },
    contents: function( elem ) {
        return jQuery.nodeName( elem, "iframe" ) ?
            elem.contentDocument || elem.contentWindow.document :
            jQuery.merge( [], elem.childNodes );
    }
}, function( name, fn ) {
    jQuery.fn[ name ] = function( until, selector ) {
        var ret = jQuery.map( this, fn, until );

        if ( !runtil.test( name ) ) {
            selector = until;
        }

        if ( selector && typeof selector === "string" ) {
            ret = jQuery.filter( selector, ret );
        }

        ret = this.length > 1 && !guaranteedUnique[ name ] ? jQuery.unique( ret ) : ret;

        if ( this.length > 1 && rparentsprev.test( name ) ) {
            ret = ret.reverse();
        }

        return this.pushStack( ret );
    };
});

jQuery.extend({
    filter: function( expr, elems, not ) {
        if ( not ) {
            expr = ":not(" + expr + ")";
        }

        return elems.length === 1 ?
            jQuery.find.matchesSelector(elems[0], expr) ? [ elems[0] ] : [] :
            jQuery.find.matches(expr, elems);
    },

    dir: function( elem, dir, until ) {
        var matched = [],
            cur = elem[ dir ];

        while ( cur && cur.nodeType !== 9 && (until === undefined || cur.nodeType !== 1 || !jQuery( cur ).is( until )) ) {
            if ( cur.nodeType === 1 ) {
                matched.push( cur );
            }
            cur = cur[dir];
        }
        return matched;
    },

    sibling: function( n, elem ) {
        var r = [];

        for ( ; n; n = n.nextSibling ) {
            if ( n.nodeType === 1 && n !== elem ) {
                r.push( n );
            }
        }

        return r;
    }
});

// Implement the identical functionality for filter and not
function winnow( elements, qualifier, keep ) {

    // Can't pass null or undefined to indexOf in Firefox 4
    // Set to 0 to skip string check
    qualifier = qualifier || 0;

    if ( jQuery.isFunction( qualifier ) ) {
        return jQuery.grep(elements, function( elem, i ) {
            var retVal = !!qualifier.call( elem, i, elem );
            return retVal === keep;
        });

    } else if ( qualifier.nodeType ) {
        return jQuery.grep(elements, function( elem ) {
            return ( elem === qualifier ) === keep;
        });

    } else if ( typeof qualifier === "string" ) {
        var filtered = jQuery.grep(elements, function( elem ) {
            return elem.nodeType === 1;
        });

        if ( isSimple.test( qualifier ) ) {
            return jQuery.filter(qualifier, filtered, !keep);
        } else {
            qualifier = jQuery.filter( qualifier, filtered );
        }
    }

    return jQuery.grep(elements, function( elem ) {
        return ( jQuery.inArray( elem, qualifier ) >= 0 ) === keep;
    });
}
function createSafeFragment( document ) {
    var list = nodeNames.split( "|" ),
        safeFrag = document.createDocumentFragment();

    if ( safeFrag.createElement ) {
        while ( list.length ) {
            safeFrag.createElement(
                list.pop()
            );
        }
    }
    return safeFrag;
}

var nodeNames = "abbr|article|aside|audio|bdi|canvas|data|datalist|details|figcaption|figure|footer|" +
        "header|hgroup|mark|meter|nav|output|progress|section|summary|time|video",
    rinlinejQuery = / jQuery\d+="(?:null|\d+)"/g,
    rnoshimcache = new RegExp("<(?:" + nodeNames + ")[\\s/>]", "i"),
    rleadingWhitespace = /^\s+/,
    rxhtmlTag = /<(?!area|br|col|embed|hr|img|input|link|meta|param)(([\w:]+)[^>]*)\/>/gi,
    rtagName = /<([\w:]+)/,
    rtbody = /<tbody/i,
    rhtml = /<|&#?\w+;/,
    rnoInnerhtml = /<(?:script|style|link)/i,
    manipulation_rcheckableType = /^(?:checkbox|radio)$/i,
    // checked="checked" or checked
    rchecked = /checked\s*(?:[^=]|=\s*.checked.)/i,
    rscriptType = /^$|\/(?:java|ecma)script/i,
    rscriptTypeMasked = /^true\/(.*)/,
    rcleanScript = /^\s*<!(?:\[CDATA\[|--)|(?:\]\]|--)>\s*$/g,

    // We have to close these tags to support XHTML (#13200)
    wrapMap = {
        option: [ 1, "<select multiple='multiple'>", "</select>" ],
        legend: [ 1, "<fieldset>", "</fieldset>" ],
        area: [ 1, "<map>", "</map>" ],
        param: [ 1, "<object>", "</object>" ],
        thead: [ 1, "<table>", "</table>" ],
        tr: [ 2, "<table><tbody>", "</tbody></table>" ],
        col: [ 2, "<table><tbody></tbody><colgroup>", "</colgroup></table>" ],
        td: [ 3, "<table><tbody><tr>", "</tr></tbody></table>" ],

        // IE6-8 can't serialize link, script, style, or any html5 (NoScope) tags,
        // unless wrapped in a div with non-breaking characters in front of it.
        _default: jQuery.support.htmlSerialize ? [ 0, "", "" ] : [ 1, "X<div>", "</div>"  ]
    },
    safeFragment = createSafeFragment( document ),
    fragmentDiv = safeFragment.appendChild( document.createElement("div") );

wrapMap.optgroup = wrapMap.option;
wrapMap.tbody = wrapMap.tfoot = wrapMap.colgroup = wrapMap.caption = wrapMap.thead;
wrapMap.th = wrapMap.td;

jQuery.fn.extend({
    text: function( value ) {
        return jQuery.access( this, function( value ) {
            return value === undefined ?
                jQuery.text( this ) :
                this.empty().append( ( this[0] && this[0].ownerDocument || document ).createTextNode( value ) );
        }, null, value, arguments.length );
    },

    wrapAll: function( html ) {
        if ( jQuery.isFunction( html ) ) {
            return this.each(function(i) {
                jQuery(this).wrapAll( html.call(this, i) );
            });
        }

        if ( this[0] ) {
            // The elements to wrap the target around
            var wrap = jQuery( html, this[0].ownerDocument ).eq(0).clone(true);

            if ( this[0].parentNode ) {
                wrap.insertBefore( this[0] );
            }

            wrap.map(function() {
                var elem = this;

                while ( elem.firstChild && elem.firstChild.nodeType === 1 ) {
                    elem = elem.firstChild;
                }

                return elem;
            }).append( this );
        }

        return this;
    },

    wrapInner: function( html ) {
        if ( jQuery.isFunction( html ) ) {
            return this.each(function(i) {
                jQuery(this).wrapInner( html.call(this, i) );
            });
        }

        return this.each(function() {
            var self = jQuery( this ),
                contents = self.contents();

            if ( contents.length ) {
                contents.wrapAll( html );

            } else {
                self.append( html );
            }
        });
    },

    wrap: function( html ) {
        var isFunction = jQuery.isFunction( html );

        return this.each(function(i) {
            jQuery( this ).wrapAll( isFunction ? html.call(this, i) : html );
        });
    },

    unwrap: function() {
        return this.parent().each(function() {
            if ( !jQuery.nodeName( this, "body" ) ) {
                jQuery( this ).replaceWith( this.childNodes );
            }
        }).end();
    },

    append: function() {
        return this.domManip(arguments, true, function( elem ) {
            if ( this.nodeType === 1 || this.nodeType === 11 || this.nodeType === 9 ) {
                this.appendChild( elem );
            }
        });
    },

    prepend: function() {
        return this.domManip(arguments, true, function( elem ) {
            if ( this.nodeType === 1 || this.nodeType === 11 || this.nodeType === 9 ) {
                this.insertBefore( elem, this.firstChild );
            }
        });
    },

    before: function() {
        return this.domManip( arguments, false, function( elem ) {
            if ( this.parentNode ) {
                this.parentNode.insertBefore( elem, this );
            }
        });
    },

    after: function() {
        return this.domManip( arguments, false, function( elem ) {
            if ( this.parentNode ) {
                this.parentNode.insertBefore( elem, this.nextSibling );
            }
        });
    },

    // keepData is for internal use only--do not document
    remove: function( selector, keepData ) {
        var elem,
            i = 0;

        for ( ; (elem = this[i]) != null; i++ ) {
            if ( !selector || jQuery.filter( selector, [ elem ] ).length > 0 ) {
                if ( !keepData && elem.nodeType === 1 ) {
                    jQuery.cleanData( getAll( elem ) );
                }

                if ( elem.parentNode ) {
                    if ( keepData && jQuery.contains( elem.ownerDocument, elem ) ) {
                        setGlobalEval( getAll( elem, "script" ) );
                    }
                    elem.parentNode.removeChild( elem );
                }
            }
        }

        return this;
    },

    empty: function() {
        var elem,
            i = 0;

        for ( ; (elem = this[i]) != null; i++ ) {
            // Remove element nodes and prevent memory leaks
            if ( elem.nodeType === 1 ) {
                jQuery.cleanData( getAll( elem, false ) );
            }

            // Remove any remaining nodes
            while ( elem.firstChild ) {
                elem.removeChild( elem.firstChild );
            }

            // If this is a select, ensure that it displays empty (#12336)
            // Support: IE<9
            if ( elem.options && jQuery.nodeName( elem, "select" ) ) {
                elem.options.length = 0;
            }
        }

        return this;
    },

    clone: function( dataAndEvents, deepDataAndEvents ) {
        dataAndEvents = dataAndEvents == null ? false : dataAndEvents;
        deepDataAndEvents = deepDataAndEvents == null ? dataAndEvents : deepDataAndEvents;

        return this.map( function () {
            return jQuery.clone( this, dataAndEvents, deepDataAndEvents );
        });
    },

    html: function( value ) {
        return jQuery.access( this, function( value ) {
            var elem = this[0] || {},
                i = 0,
                l = this.length;

            if ( value === undefined ) {
                return elem.nodeType === 1 ?
                    elem.innerHTML.replace( rinlinejQuery, "" ) :
                    undefined;
            }

            // See if we can take a shortcut and just use innerHTML
            if ( typeof value === "string" && !rnoInnerhtml.test( value ) &&
                ( jQuery.support.htmlSerialize || !rnoshimcache.test( value )  ) &&
                ( jQuery.support.leadingWhitespace || !rleadingWhitespace.test( value ) ) &&
                !wrapMap[ ( rtagName.exec( value ) || ["", ""] )[1].toLowerCase() ] ) {

                value = value.replace( rxhtmlTag, "<$1></$2>" );

                try {
                    for (; i < l; i++ ) {
                        // Remove element nodes and prevent memory leaks
                        elem = this[i] || {};
                        if ( elem.nodeType === 1 ) {
                            jQuery.cleanData( getAll( elem, false ) );
                            elem.innerHTML = value;
                        }
                    }

                    elem = 0;

                // If using innerHTML throws an exception, use the fallback method
                } catch(e) {}
            }

            if ( elem ) {
                this.empty().append( value );
            }
        }, null, value, arguments.length );
    },

    replaceWith: function( value ) {
        var isFunc = jQuery.isFunction( value );

        // Make sure that the elements are removed from the DOM before they are inserted
        // this can help fix replacing a parent with child elements
        if ( !isFunc && typeof value !== "string" ) {
            value = jQuery( value ).not( this ).detach();
        }

        return this.domManip( [ value ], true, function( elem ) {
            var next = this.nextSibling,
                parent = this.parentNode;

            if ( parent ) {
                jQuery( this ).remove();
                parent.insertBefore( elem, next );
            }
        });
    },

    detach: function( selector ) {
        return this.remove( selector, true );
    },

    domManip: function( args, table, callback ) {

        // Flatten any nested arrays
        args = core_concat.apply( [], args );

        var first, node, hasScripts,
            scripts, doc, fragment,
            i = 0,
            l = this.length,
            set = this,
            iNoClone = l - 1,
            value = args[0],
            isFunction = jQuery.isFunction( value );

        // We can't cloneNode fragments that contain checked, in WebKit
        if ( isFunction || !( l <= 1 || typeof value !== "string" || jQuery.support.checkClone || !rchecked.test( value ) ) ) {
            return this.each(function( index ) {
                var self = set.eq( index );
                if ( isFunction ) {
                    args[0] = value.call( this, index, table ? self.html() : undefined );
                }
                self.domManip( args, table, callback );
            });
        }

        if ( l ) {
            fragment = jQuery.buildFragment( args, this[ 0 ].ownerDocument, false, this );
            first = fragment.firstChild;

            if ( fragment.childNodes.length === 1 ) {
                fragment = first;
            }

            if ( first ) {
                table = table && jQuery.nodeName( first, "tr" );
                scripts = jQuery.map( getAll( fragment, "script" ), disableScript );
                hasScripts = scripts.length;

                // Use the original fragment for the last item instead of the first because it can end up
                // being emptied incorrectly in certain situations (#8070).
                for ( ; i < l; i++ ) {
                    node = fragment;

                    if ( i !== iNoClone ) {
                        node = jQuery.clone( node, true, true );

                        // Keep references to cloned scripts for later restoration
                        if ( hasScripts ) {
                            jQuery.merge( scripts, getAll( node, "script" ) );
                        }
                    }

                    callback.call(
                        table && jQuery.nodeName( this[i], "table" ) ?
                            findOrAppend( this[i], "tbody" ) :
                            this[i],
                        node,
                        i
                    );
                }

                if ( hasScripts ) {
                    doc = scripts[ scripts.length - 1 ].ownerDocument;

                    // Reenable scripts
                    jQuery.map( scripts, restoreScript );

                    // Evaluate executable scripts on first document insertion
                    for ( i = 0; i < hasScripts; i++ ) {
                        node = scripts[ i ];
                        if ( rscriptType.test( node.type || "" ) &&
                            !jQuery._data( node, "globalEval" ) && jQuery.contains( doc, node ) ) {

                            if ( node.src ) {
                                // Hope ajax is available...
                                jQuery.ajax({
                                    url: node.src,
                                    type: "GET",
                                    dataType: "script",
                                    async: false,
                                    global: false,
                                    "throws": true
                                });
                            } else {
                                jQuery.globalEval( ( node.text || node.textContent || node.innerHTML || "" ).replace( rcleanScript, "" ) );
                            }
                        }
                    }
                }

                // Fix #11809: Avoid leaking memory
                fragment = first = null;
            }
        }

        return this;
    }
});

function findOrAppend( elem, tag ) {
    return elem.getElementsByTagName( tag )[0] || elem.appendChild( elem.ownerDocument.createElement( tag ) );
}

// Replace/restore the type attribute of script elements for safe DOM manipulation
function disableScript( elem ) {
    var attr = elem.getAttributeNode("type");
    elem.type = ( attr && attr.specified ) + "/" + elem.type;
    return elem;
}
function restoreScript( elem ) {
    var match = rscriptTypeMasked.exec( elem.type );
    if ( match ) {
        elem.type = match[1];
    } else {
        elem.removeAttribute("type");
    }
    return elem;
}

// Mark scripts as having already been evaluated
function setGlobalEval( elems, refElements ) {
    var elem,
        i = 0;
    for ( ; (elem = elems[i]) != null; i++ ) {
        jQuery._data( elem, "globalEval", !refElements || jQuery._data( refElements[i], "globalEval" ) );
    }
}

function cloneCopyEvent( src, dest ) {

    if ( dest.nodeType !== 1 || !jQuery.hasData( src ) ) {
        return;
    }

    var type, i, l,
        oldData = jQuery._data( src ),
        curData = jQuery._data( dest, oldData ),
        events = oldData.events;

    if ( events ) {
        delete curData.handle;
        curData.events = {};

        for ( type in events ) {
            for ( i = 0, l = events[ type ].length; i < l; i++ ) {
                jQuery.event.add( dest, type, events[ type ][ i ] );
            }
        }
    }

    // make the cloned public data object a copy from the original
    if ( curData.data ) {
        curData.data = jQuery.extend( {}, curData.data );
    }
}

function fixCloneNodeIssues( src, dest ) {
    var nodeName, e, data;

    // We do not need to do anything for non-Elements
    if ( dest.nodeType !== 1 ) {
        return;
    }

    nodeName = dest.nodeName.toLowerCase();

    // IE6-8 copies events bound via attachEvent when using cloneNode.
    if ( !jQuery.support.noCloneEvent && dest[ jQuery.expando ] ) {
        data = jQuery._data( dest );

        for ( e in data.events ) {
            jQuery.removeEvent( dest, e, data.handle );
        }

        // Event data gets referenced instead of copied if the expando gets copied too
        dest.removeAttribute( jQuery.expando );
    }

    // IE blanks contents when cloning scripts, and tries to evaluate newly-set text
    if ( nodeName === "script" && dest.text !== src.text ) {
        disableScript( dest ).text = src.text;
        restoreScript( dest );

    // IE6-10 improperly clones children of object elements using classid.
    // IE10 throws NoModificationAllowedError if parent is null, #12132.
    } else if ( nodeName === "object" ) {
        if ( dest.parentNode ) {
            dest.outerHTML = src.outerHTML;
        }

        // This path appears unavoidable for IE9. When cloning an object
        // element in IE9, the outerHTML strategy above is not sufficient.
        // If the src has innerHTML and the destination does not,
        // copy the src.innerHTML into the dest.innerHTML. #10324
        if ( jQuery.support.html5Clone && ( src.innerHTML && !jQuery.trim(dest.innerHTML) ) ) {
            dest.innerHTML = src.innerHTML;
        }

    } else if ( nodeName === "input" && manipulation_rcheckableType.test( src.type ) ) {
        // IE6-8 fails to persist the checked state of a cloned checkbox
        // or radio button. Worse, IE6-7 fail to give the cloned element
        // a checked appearance if the defaultChecked value isn't also set

        dest.defaultChecked = dest.checked = src.checked;

        // IE6-7 get confused and end up setting the value of a cloned
        // checkbox/radio button to an empty string instead of "on"
        if ( dest.value !== src.value ) {
            dest.value = src.value;
        }

    // IE6-8 fails to return the selected option to the default selected
    // state when cloning options
    } else if ( nodeName === "option" ) {
        dest.defaultSelected = dest.selected = src.defaultSelected;

    // IE6-8 fails to set the defaultValue to the correct value when
    // cloning other types of input fields
    } else if ( nodeName === "input" || nodeName === "textarea" ) {
        dest.defaultValue = src.defaultValue;
    }
}

jQuery.each({
    appendTo: "append",
    prependTo: "prepend",
    insertBefore: "before",
    insertAfter: "after",
    replaceAll: "replaceWith"
}, function( name, original ) {
    jQuery.fn[ name ] = function( selector ) {
        var elems,
            i = 0,
            ret = [],
            insert = jQuery( selector ),
            last = insert.length - 1;

        for ( ; i <= last; i++ ) {
            elems = i === last ? this : this.clone(true);
            jQuery( insert[i] )[ original ]( elems );

            // Modern browsers can apply jQuery collections as arrays, but oldIE needs a .get()
            core_push.apply( ret, elems.get() );
        }

        return this.pushStack( ret );
    };
});

function getAll( context, tag ) {
    var elems, elem,
        i = 0,
        found = typeof context.getElementsByTagName !== core_strundefined ? context.getElementsByTagName( tag || "*" ) :
            typeof context.querySelectorAll !== core_strundefined ? context.querySelectorAll( tag || "*" ) :
            undefined;

    if ( !found ) {
        for ( found = [], elems = context.childNodes || context; (elem = elems[i]) != null; i++ ) {
            if ( !tag || jQuery.nodeName( elem, tag ) ) {
                found.push( elem );
            } else {
                jQuery.merge( found, getAll( elem, tag ) );
            }
        }
    }

    return tag === undefined || tag && jQuery.nodeName( context, tag ) ?
        jQuery.merge( [ context ], found ) :
        found;
}

// Used in buildFragment, fixes the defaultChecked property
function fixDefaultChecked( elem ) {
    if ( manipulation_rcheckableType.test( elem.type ) ) {
        elem.defaultChecked = elem.checked;
    }
}

jQuery.extend({
    clone: function( elem, dataAndEvents, deepDataAndEvents ) {
        var destElements, node, clone, i, srcElements,
            inPage = jQuery.contains( elem.ownerDocument, elem );

        if ( jQuery.support.html5Clone || jQuery.isXMLDoc(elem) || !rnoshimcache.test( "<" + elem.nodeName + ">" ) ) {
            clone = elem.cloneNode( true );

        // IE<=8 does not properly clone detached, unknown element nodes
        } else {
            fragmentDiv.innerHTML = elem.outerHTML;
            fragmentDiv.removeChild( clone = fragmentDiv.firstChild );
        }

        if ( (!jQuery.support.noCloneEvent || !jQuery.support.noCloneChecked) &&
                (elem.nodeType === 1 || elem.nodeType === 11) && !jQuery.isXMLDoc(elem) ) {

            // We eschew Sizzle here for performance reasons: http://jsperf.com/getall-vs-sizzle/2
            destElements = getAll( clone );
            srcElements = getAll( elem );

            // Fix all IE cloning issues
            for ( i = 0; (node = srcElements[i]) != null; ++i ) {
                // Ensure that the destination node is not null; Fixes #9587
                if ( destElements[i] ) {
                    fixCloneNodeIssues( node, destElements[i] );
                }
            }
        }

        // Copy the events from the original to the clone
        if ( dataAndEvents ) {
            if ( deepDataAndEvents ) {
                srcElements = srcElements || getAll( elem );
                destElements = destElements || getAll( clone );

                for ( i = 0; (node = srcElements[i]) != null; i++ ) {
                    cloneCopyEvent( node, destElements[i] );
                }
            } else {
                cloneCopyEvent( elem, clone );
            }
        }

        // Preserve script evaluation history
        destElements = getAll( clone, "script" );
        if ( destElements.length > 0 ) {
            setGlobalEval( destElements, !inPage && getAll( elem, "script" ) );
        }

        destElements = srcElements = node = null;

        // Return the cloned set
        return clone;
    },

    buildFragment: function( elems, context, scripts, selection ) {
        var j, elem, contains,
            tmp, tag, tbody, wrap,
            l = elems.length,

            // Ensure a safe fragment
            safe = createSafeFragment( context ),

            nodes = [],
            i = 0;

        for ( ; i < l; i++ ) {
            elem = elems[ i ];

            if ( elem || elem === 0 ) {

                // Add nodes directly
                if ( jQuery.type( elem ) === "object" ) {
                    jQuery.merge( nodes, elem.nodeType ? [ elem ] : elem );

                // Convert non-html into a text node
                } else if ( !rhtml.test( elem ) ) {
                    nodes.push( context.createTextNode( elem ) );

                // Convert html into DOM nodes
                } else {
                    tmp = tmp || safe.appendChild( context.createElement("div") );

                    // Deserialize a standard representation
                    tag = ( rtagName.exec( elem ) || ["", ""] )[1].toLowerCase();
                    wrap = wrapMap[ tag ] || wrapMap._default;

                    tmp.innerHTML = wrap[1] + elem.replace( rxhtmlTag, "<$1></$2>" ) + wrap[2];

                    // Descend through wrappers to the right content
                    j = wrap[0];
                    while ( j-- ) {
                        tmp = tmp.lastChild;
                    }

                    // Manually add leading whitespace removed by IE
                    if ( !jQuery.support.leadingWhitespace && rleadingWhitespace.test( elem ) ) {
                        nodes.push( context.createTextNode( rleadingWhitespace.exec( elem )[0] ) );
                    }

                    // Remove IE's autoinserted <tbody> from table fragments
                    if ( !jQuery.support.tbody ) {

                        // String was a <table>, *may* have spurious <tbody>
                        elem = tag === "table" && !rtbody.test( elem ) ?
                            tmp.firstChild :

                            // String was a bare <thead> or <tfoot>
                            wrap[1] === "<table>" && !rtbody.test( elem ) ?
                                tmp :
                                0;

                        j = elem && elem.childNodes.length;
                        while ( j-- ) {
                            if ( jQuery.nodeName( (tbody = elem.childNodes[j]), "tbody" ) && !tbody.childNodes.length ) {
                                elem.removeChild( tbody );
                            }
                        }
                    }

                    jQuery.merge( nodes, tmp.childNodes );

                    // Fix #12392 for WebKit and IE > 9
                    tmp.textContent = "";

                    // Fix #12392 for oldIE
                    while ( tmp.firstChild ) {
                        tmp.removeChild( tmp.firstChild );
                    }

                    // Remember the top-level container for proper cleanup
                    tmp = safe.lastChild;
                }
            }
        }

        // Fix #11356: Clear elements from fragment
        if ( tmp ) {
            safe.removeChild( tmp );
        }

        // Reset defaultChecked for any radios and checkboxes
        // about to be appended to the DOM in IE 6/7 (#8060)
        if ( !jQuery.support.appendChecked ) {
            jQuery.grep( getAll( nodes, "input" ), fixDefaultChecked );
        }

        i = 0;
        while ( (elem = nodes[ i++ ]) ) {

            // #4087 - If origin and destination elements are the same, and this is
            // that element, do not do anything
            if ( selection && jQuery.inArray( elem, selection ) !== -1 ) {
                continue;
            }

            contains = jQuery.contains( elem.ownerDocument, elem );

            // Append to fragment
            tmp = getAll( safe.appendChild( elem ), "script" );

            // Preserve script evaluation history
            if ( contains ) {
                setGlobalEval( tmp );
            }

            // Capture executables
            if ( scripts ) {
                j = 0;
                while ( (elem = tmp[ j++ ]) ) {
                    if ( rscriptType.test( elem.type || "" ) ) {
                        scripts.push( elem );
                    }
                }
            }
        }

        tmp = null;

        return safe;
    },

    cleanData: function( elems, /* internal */ acceptData ) {
        var elem, type, id, data,
            i = 0,
            internalKey = jQuery.expando,
            cache = jQuery.cache,
            deleteExpando = jQuery.support.deleteExpando,
            special = jQuery.event.special;

        for ( ; (elem = elems[i]) != null; i++ ) {

            if ( acceptData || jQuery.acceptData( elem ) ) {

                id = elem[ internalKey ];
                data = id && cache[ id ];

                if ( data ) {
                    if ( data.events ) {
                        for ( type in data.events ) {
                            if ( special[ type ] ) {
                                jQuery.event.remove( elem, type );

                            // This is a shortcut to avoid jQuery.event.remove's overhead
                            } else {
                                jQuery.removeEvent( elem, type, data.handle );
                            }
                        }
                    }

                    // Remove cache only if it was not already removed by jQuery.event.remove
                    if ( cache[ id ] ) {

                        delete cache[ id ];

                        // IE does not allow us to delete expando properties from nodes,
                        // nor does it have a removeAttribute function on Document nodes;
                        // we must handle all of these cases
                        if ( deleteExpando ) {
                            delete elem[ internalKey ];

                        } else if ( typeof elem.removeAttribute !== core_strundefined ) {
                            elem.removeAttribute( internalKey );

                        } else {
                            elem[ internalKey ] = null;
                        }

                        core_deletedIds.push( id );
                    }
                }
            }
        }
    }
});
var iframe, getStyles, curCSS,
    ralpha = /alpha\([^)]*\)/i,
    ropacity = /opacity\s*=\s*([^)]*)/,
    rposition = /^(top|right|bottom|left)$/,
    // swappable if display is none or starts with table except "table", "table-cell", or "table-caption"
    // see here for display values: https://developer.mozilla.org/en-US/docs/CSS/display
    rdisplayswap = /^(none|table(?!-c[ea]).+)/,
    rmargin = /^margin/,
    rnumsplit = new RegExp( "^(" + core_pnum + ")(.*)$", "i" ),
    rnumnonpx = new RegExp( "^(" + core_pnum + ")(?!px)[a-z%]+$", "i" ),
    rrelNum = new RegExp( "^([+-])=(" + core_pnum + ")", "i" ),
    elemdisplay = { BODY: "block" },

    cssShow = { position: "absolute", visibility: "hidden", display: "block" },
    cssNormalTransform = {
        letterSpacing: 0,
        fontWeight: 400
    },

    cssExpand = [ "Top", "Right", "Bottom", "Left" ],
    cssPrefixes = [ "Webkit", "O", "Moz", "ms" ];

// return a css property mapped to a potentially vendor prefixed property
function vendorPropName( style, name ) {

    // shortcut for names that are not vendor prefixed
    if ( name in style ) {
        return name;
    }

    // check for vendor prefixed names
    var capName = name.charAt(0).toUpperCase() + name.slice(1),
        origName = name,
        i = cssPrefixes.length;

    while ( i-- ) {
        name = cssPrefixes[ i ] + capName;
        if ( name in style ) {
            return name;
        }
    }

    return origName;
}

function isHidden( elem, el ) {
    // isHidden might be called from jQuery#filter function;
    // in that case, element will be second argument
    elem = el || elem;
    return jQuery.css( elem, "display" ) === "none" || !jQuery.contains( elem.ownerDocument, elem );
}

function showHide( elements, show ) {
    var display, elem, hidden,
        values = [],
        index = 0,
        length = elements.length;

    for ( ; index < length; index++ ) {
        elem = elements[ index ];
        if ( !elem.style ) {
            continue;
        }

        values[ index ] = jQuery._data( elem, "olddisplay" );
        display = elem.style.display;
        if ( show ) {
            // Reset the inline display of this element to learn if it is
            // being hidden by cascaded rules or not
            if ( !values[ index ] && display === "none" ) {
                elem.style.display = "";
            }

            // Set elements which have been overridden with display: none
            // in a stylesheet to whatever the default browser style is
            // for such an element
            if ( elem.style.display === "" && isHidden( elem ) ) {
                values[ index ] = jQuery._data( elem, "olddisplay", css_defaultDisplay(elem.nodeName) );
            }
        } else {

            if ( !values[ index ] ) {
                hidden = isHidden( elem );

                if ( display && display !== "none" || !hidden ) {
                    jQuery._data( elem, "olddisplay", hidden ? display : jQuery.css( elem, "display" ) );
                }
            }
        }
    }

    // Set the display of most of the elements in a second loop
    // to avoid the constant reflow
    for ( index = 0; index < length; index++ ) {
        elem = elements[ index ];
        if ( !elem.style ) {
            continue;
        }
        if ( !show || elem.style.display === "none" || elem.style.display === "" ) {
            elem.style.display = show ? values[ index ] || "" : "none";
        }
    }

    return elements;
}

jQuery.fn.extend({
    css: function( name, value ) {
        return jQuery.access( this, function( elem, name, value ) {
            var len, styles,
                map = {},
                i = 0;

            if ( jQuery.isArray( name ) ) {
                styles = getStyles( elem );
                len = name.length;

                for ( ; i < len; i++ ) {
                    map[ name[ i ] ] = jQuery.css( elem, name[ i ], false, styles );
                }

                return map;
            }

            return value !== undefined ?
                jQuery.style( elem, name, value ) :
                jQuery.css( elem, name );
        }, name, value, arguments.length > 1 );
    },
    show: function() {
        return showHide( this, true );
    },
    hide: function() {
        return showHide( this );
    },
    toggle: function( state ) {
        var bool = typeof state === "boolean";

        return this.each(function() {
            if ( bool ? state : isHidden( this ) ) {
                jQuery( this ).show();
            } else {
                jQuery( this ).hide();
            }
        });
    }
});

jQuery.extend({
    // Add in style property hooks for overriding the default
    // behavior of getting and setting a style property
    cssHooks: {
        opacity: {
            get: function( elem, computed ) {
                if ( computed ) {
                    // We should always get a number back from opacity
                    var ret = curCSS( elem, "opacity" );
                    return ret === "" ? "1" : ret;
                }
            }
        }
    },

    // Exclude the following css properties to add px
    cssNumber: {
        "columnCount": true,
        "fillOpacity": true,
        "fontWeight": true,
        "lineHeight": true,
        "opacity": true,
        "orphans": true,
        "widows": true,
        "zIndex": true,
        "zoom": true
    },

    // Add in properties whose names you wish to fix before
    // setting or getting the value
    cssProps: {
        // normalize float css property
        "float": jQuery.support.cssFloat ? "cssFloat" : "styleFloat"
    },

    // Get and set the style property on a DOM Node
    style: function( elem, name, value, extra ) {
        // Don't set styles on text and comment nodes
        if ( !elem || elem.nodeType === 3 || elem.nodeType === 8 || !elem.style ) {
            return;
        }

        // Make sure that we're working with the right name
        var ret, type, hooks,
            origName = jQuery.camelCase( name ),
            style = elem.style;

        name = jQuery.cssProps[ origName ] || ( jQuery.cssProps[ origName ] = vendorPropName( style, origName ) );

        // gets hook for the prefixed version
        // followed by the unprefixed version
        hooks = jQuery.cssHooks[ name ] || jQuery.cssHooks[ origName ];

        // Check if we're setting a value
        if ( value !== undefined ) {
            type = typeof value;

            // convert relative number strings (+= or -=) to relative numbers. #7345
            if ( type === "string" && (ret = rrelNum.exec( value )) ) {
                value = ( ret[1] + 1 ) * ret[2] + parseFloat( jQuery.css( elem, name ) );
                // Fixes bug #9237
                type = "number";
            }

            // Make sure that NaN and null values aren't set. See: #7116
            if ( value == null || type === "number" && isNaN( value ) ) {
                return;
            }

            // If a number was passed in, add 'px' to the (except for certain CSS properties)
            if ( type === "number" && !jQuery.cssNumber[ origName ] ) {
                value += "px";
            }

            // Fixes #8908, it can be done more correctly by specifing setters in cssHooks,
            // but it would mean to define eight (for every problematic property) identical functions
            if ( !jQuery.support.clearCloneStyle && value === "" && name.indexOf("background") === 0 ) {
                style[ name ] = "inherit";
            }

            // If a hook was provided, use that value, otherwise just set the specified value
            if ( !hooks || !("set" in hooks) || (value = hooks.set( elem, value, extra )) !== undefined ) {

                // Wrapped to prevent IE from throwing errors when 'invalid' values are provided
                // Fixes bug #5509
                try {
                    style[ name ] = value;
                } catch(e) {}
            }

        } else {
            // If a hook was provided get the non-computed value from there
            if ( hooks && "get" in hooks && (ret = hooks.get( elem, false, extra )) !== undefined ) {
                return ret;
            }

            // Otherwise just get the value from the style object
            return style[ name ];
        }
    },

    css: function( elem, name, extra, styles ) {
        var num, val, hooks,
            origName = jQuery.camelCase( name );

        // Make sure that we're working with the right name
        name = jQuery.cssProps[ origName ] || ( jQuery.cssProps[ origName ] = vendorPropName( elem.style, origName ) );

        // gets hook for the prefixed version
        // followed by the unprefixed version
        hooks = jQuery.cssHooks[ name ] || jQuery.cssHooks[ origName ];

        // If a hook was provided get the computed value from there
        if ( hooks && "get" in hooks ) {
            val = hooks.get( elem, true, extra );
        }

        // Otherwise, if a way to get the computed value exists, use that
        if ( val === undefined ) {
            val = curCSS( elem, name, styles );
        }

        //convert "normal" to computed value
        if ( val === "normal" && name in cssNormalTransform ) {
            val = cssNormalTransform[ name ];
        }

        // Return, converting to number if forced or a qualifier was provided and val looks numeric
        if ( extra === "" || extra ) {
            num = parseFloat( val );
            return extra === true || jQuery.isNumeric( num ) ? num || 0 : val;
        }
        return val;
    },

    // A method for quickly swapping in/out CSS properties to get correct calculations
    swap: function( elem, options, callback, args ) {
        var ret, name,
            old = {};

        // Remember the old values, and insert the new ones
        for ( name in options ) {
            old[ name ] = elem.style[ name ];
            elem.style[ name ] = options[ name ];
        }

        ret = callback.apply( elem, args || [] );

        // Revert the old values
        for ( name in options ) {
            elem.style[ name ] = old[ name ];
        }

        return ret;
    }
});

// NOTE: we've included the "window" in window.getComputedStyle
// because jsdom on node.js will break without it.
if ( window.getComputedStyle ) {
    getStyles = function( elem ) {
        return window.getComputedStyle( elem, null );
    };

    curCSS = function( elem, name, _computed ) {
        var width, minWidth, maxWidth,
            computed = _computed || getStyles( elem ),

            // getPropertyValue is only needed for .css('filter') in IE9, see #12537
            ret = computed ? computed.getPropertyValue( name ) || computed[ name ] : undefined,
            style = elem.style;

        if ( computed ) {

            if ( ret === "" && !jQuery.contains( elem.ownerDocument, elem ) ) {
                ret = jQuery.style( elem, name );
            }

            // A tribute to the "awesome hack by Dean Edwards"
            // Chrome < 17 and Safari 5.0 uses "computed value" instead of "used value" for margin-right
            // Safari 5.1.7 (at least) returns percentage for a larger set of values, but width seems to be reliably pixels
            // this is against the CSSOM draft spec: http://dev.w3.org/csswg/cssom/#resolved-values
            if ( rnumnonpx.test( ret ) && rmargin.test( name ) ) {

                // Remember the original values
                width = style.width;
                minWidth = style.minWidth;
                maxWidth = style.maxWidth;

                // Put in the new values to get a computed value out
                style.minWidth = style.maxWidth = style.width = ret;
                ret = computed.width;

                // Revert the changed values
                style.width = width;
                style.minWidth = minWidth;
                style.maxWidth = maxWidth;
            }
        }

        return ret;
    };
} else if ( document.documentElement.currentStyle ) {
    getStyles = function( elem ) {
        return elem.currentStyle;
    };

    curCSS = function( elem, name, _computed ) {
        var left, rs, rsLeft,
            computed = _computed || getStyles( elem ),
            ret = computed ? computed[ name ] : undefined,
            style = elem.style;

        // Avoid setting ret to empty string here
        // so we don't default to auto
        if ( ret == null && style && style[ name ] ) {
            ret = style[ name ];
        }

        // From the awesome hack by Dean Edwards
        // http://erik.eae.net/archives/2007/07/27/18.54.15/#comment-102291

        // If we're not dealing with a regular pixel number
        // but a number that has a weird ending, we need to convert it to pixels
        // but not position css attributes, as those are proportional to the parent element instead
        // and we can't measure the parent instead because it might trigger a "stacking dolls" problem
        if ( rnumnonpx.test( ret ) && !rposition.test( name ) ) {

            // Remember the original values
            left = style.left;
            rs = elem.runtimeStyle;
            rsLeft = rs && rs.left;

            // Put in the new values to get a computed value out
            if ( rsLeft ) {
                rs.left = elem.currentStyle.left;
            }
            style.left = name === "fontSize" ? "1em" : ret;
            ret = style.pixelLeft + "px";

            // Revert the changed values
            style.left = left;
            if ( rsLeft ) {
                rs.left = rsLeft;
            }
        }

        return ret === "" ? "auto" : ret;
    };
}

function setPositiveNumber( elem, value, subtract ) {
    var matches = rnumsplit.exec( value );
    return matches ?
        // Guard against undefined "subtract", e.g., when used as in cssHooks
        Math.max( 0, matches[ 1 ] - ( subtract || 0 ) ) + ( matches[ 2 ] || "px" ) :
        value;
}

function augmentWidthOrHeight( elem, name, extra, isBorderBox, styles ) {
    var i = extra === ( isBorderBox ? "border" : "content" ) ?
        // If we already have the right measurement, avoid augmentation
        4 :
        // Otherwise initialize for horizontal or vertical properties
        name === "width" ? 1 : 0,

        val = 0;

    for ( ; i < 4; i += 2 ) {
        // both box models exclude margin, so add it if we want it
        if ( extra === "margin" ) {
            val += jQuery.css( elem, extra + cssExpand[ i ], true, styles );
        }

        if ( isBorderBox ) {
            // border-box includes padding, so remove it if we want content
            if ( extra === "content" ) {
                val -= jQuery.css( elem, "padding" + cssExpand[ i ], true, styles );
            }

            // at this point, extra isn't border nor margin, so remove border
            if ( extra !== "margin" ) {
                val -= jQuery.css( elem, "border" + cssExpand[ i ] + "Width", true, styles );
            }
        } else {
            // at this point, extra isn't content, so add padding
            val += jQuery.css( elem, "padding" + cssExpand[ i ], true, styles );

            // at this point, extra isn't content nor padding, so add border
            if ( extra !== "padding" ) {
                val += jQuery.css( elem, "border" + cssExpand[ i ] + "Width", true, styles );
            }
        }
    }

    return val;
}

function getWidthOrHeight( elem, name, extra ) {

    // Start with offset property, which is equivalent to the border-box value
    var valueIsBorderBox = true,
        val = name === "width" ? elem.offsetWidth : elem.offsetHeight,
        styles = getStyles( elem ),
        isBorderBox = jQuery.support.boxSizing && jQuery.css( elem, "boxSizing", false, styles ) === "border-box";

    // some non-html elements return undefined for offsetWidth, so check for null/undefined
    // svg - https://bugzilla.mozilla.org/show_bug.cgi?id=649285
    // MathML - https://bugzilla.mozilla.org/show_bug.cgi?id=491668
    if ( val <= 0 || val == null ) {
        // Fall back to computed then uncomputed css if necessary
        val = curCSS( elem, name, styles );
        if ( val < 0 || val == null ) {
            val = elem.style[ name ];
        }

        // Computed unit is not pixels. Stop here and return.
        if ( rnumnonpx.test(val) ) {
            return val;
        }

        // we need the check for style in case a browser which returns unreliable values
        // for getComputedStyle silently falls back to the reliable elem.style
        valueIsBorderBox = isBorderBox && ( jQuery.support.boxSizingReliable || val === elem.style[ name ] );

        // Normalize "", auto, and prepare for extra
        val = parseFloat( val ) || 0;
    }

    // use the active box-sizing model to add/subtract irrelevant styles
    return ( val +
        augmentWidthOrHeight(
            elem,
            name,
            extra || ( isBorderBox ? "border" : "content" ),
            valueIsBorderBox,
            styles
        )
    ) + "px";
}

// Try to determine the default display value of an element
function css_defaultDisplay( nodeName ) {
    var doc = document,
        display = elemdisplay[ nodeName ];

    if ( !display ) {
        display = actualDisplay( nodeName, doc );

        // If the simple way fails, read from inside an iframe
        if ( display === "none" || !display ) {
            // Use the already-created iframe if possible
            iframe = ( iframe ||
                jQuery("<iframe frameborder='0' width='0' height='0'/>")
                .css( "cssText", "display:block !important" )
            ).appendTo( doc.documentElement );

            // Always write a new HTML skeleton so Webkit and Firefox don't choke on reuse
            doc = ( iframe[0].contentWindow || iframe[0].contentDocument ).document;
            doc.write("<!doctype html><html><body>");
            doc.close();

            display = actualDisplay( nodeName, doc );
            iframe.detach();
        }

        // Store the correct default display
        elemdisplay[ nodeName ] = display;
    }

    return display;
}

// Called ONLY from within css_defaultDisplay
function actualDisplay( name, doc ) {
    var elem = jQuery( doc.createElement( name ) ).appendTo( doc.body ),
        display = jQuery.css( elem[0], "display" );
    elem.remove();
    return display;
}

jQuery.each([ "height", "width" ], function( i, name ) {
    jQuery.cssHooks[ name ] = {
        get: function( elem, computed, extra ) {
            if ( computed ) {
                // certain elements can have dimension info if we invisibly show them
                // however, it must have a current display style that would benefit from this
                return elem.offsetWidth === 0 && rdisplayswap.test( jQuery.css( elem, "display" ) ) ?
                    jQuery.swap( elem, cssShow, function() {
                        return getWidthOrHeight( elem, name, extra );
                    }) :
                    getWidthOrHeight( elem, name, extra );
            }
        },

        set: function( elem, value, extra ) {
            var styles = extra && getStyles( elem );
            return setPositiveNumber( elem, value, extra ?
                augmentWidthOrHeight(
                    elem,
                    name,
                    extra,
                    jQuery.support.boxSizing && jQuery.css( elem, "boxSizing", false, styles ) === "border-box",
                    styles
                ) : 0
            );
        }
    };
});

if ( !jQuery.support.opacity ) {
    jQuery.cssHooks.opacity = {
        get: function( elem, computed ) {
            // IE uses filters for opacity
            return ropacity.test( (computed && elem.currentStyle ? elem.currentStyle.filter : elem.style.filter) || "" ) ?
                ( 0.01 * parseFloat( RegExp.$1 ) ) + "" :
                computed ? "1" : "";
        },

        set: function( elem, value ) {
            var style = elem.style,
                currentStyle = elem.currentStyle,
                opacity = jQuery.isNumeric( value ) ? "alpha(opacity=" + value * 100 + ")" : "",
                filter = currentStyle && currentStyle.filter || style.filter || "";

            // IE has trouble with opacity if it does not have layout
            // Force it by setting the zoom level
            style.zoom = 1;

            // if setting opacity to 1, and no other filters exist - attempt to remove filter attribute #6652
            // if value === "", then remove inline opacity #12685
            if ( ( value >= 1 || value === "" ) &&
                    jQuery.trim( filter.replace( ralpha, "" ) ) === "" &&
                    style.removeAttribute ) {

                // Setting style.filter to null, "" & " " still leave "filter:" in the cssText
                // if "filter:" is present at all, clearType is disabled, we want to avoid this
                // style.removeAttribute is IE Only, but so apparently is this code path...
                style.removeAttribute( "filter" );

                // if there is no filter style applied in a css rule or unset inline opacity, we are done
                if ( value === "" || currentStyle && !currentStyle.filter ) {
                    return;
                }
            }

            // otherwise, set new filter values
            style.filter = ralpha.test( filter ) ?
                filter.replace( ralpha, opacity ) :
                filter + " " + opacity;
        }
    };
}

// These hooks cannot be added until DOM ready because the support test
// for it is not run until after DOM ready
jQuery(function() {
    if ( !jQuery.support.reliableMarginRight ) {
        jQuery.cssHooks.marginRight = {
            get: function( elem, computed ) {
                if ( computed ) {
                    // WebKit Bug 13343 - getComputedStyle returns wrong value for margin-right
                    // Work around by temporarily setting element display to inline-block
                    return jQuery.swap( elem, { "display": "inline-block" },
                        curCSS, [ elem, "marginRight" ] );
                }
            }
        };
    }

    // Webkit bug: https://bugs.webkit.org/show_bug.cgi?id=29084
    // getComputedStyle returns percent when specified for top/left/bottom/right
    // rather than make the css module depend on the offset module, we just check for it here
    if ( !jQuery.support.pixelPosition && jQuery.fn.position ) {
        jQuery.each( [ "top", "left" ], function( i, prop ) {
            jQuery.cssHooks[ prop ] = {
                get: function( elem, computed ) {
                    if ( computed ) {
                        computed = curCSS( elem, prop );
                        // if curCSS returns percentage, fallback to offset
                        return rnumnonpx.test( computed ) ?
                            jQuery( elem ).position()[ prop ] + "px" :
                            computed;
                    }
                }
            };
        });
    }

});

if ( jQuery.expr && jQuery.expr.filters ) {
    jQuery.expr.filters.hidden = function( elem ) {
        // Support: Opera <= 12.12
        // Opera reports offsetWidths and offsetHeights less than zero on some elements
        return elem.offsetWidth <= 0 && elem.offsetHeight <= 0 ||
            (!jQuery.support.reliableHiddenOffsets && ((elem.style && elem.style.display) || jQuery.css( elem, "display" )) === "none");
    };

    jQuery.expr.filters.visible = function( elem ) {
        return !jQuery.expr.filters.hidden( elem );
    };
}

// These hooks are used by animate to expand properties
jQuery.each({
    margin: "",
    padding: "",
    border: "Width"
}, function( prefix, suffix ) {
    jQuery.cssHooks[ prefix + suffix ] = {
        expand: function( value ) {
            var i = 0,
                expanded = {},

                // assumes a single number if not a string
                parts = typeof value === "string" ? value.split(" ") : [ value ];

            for ( ; i < 4; i++ ) {
                expanded[ prefix + cssExpand[ i ] + suffix ] =
                    parts[ i ] || parts[ i - 2 ] || parts[ 0 ];
            }

            return expanded;
        }
    };

    if ( !rmargin.test( prefix ) ) {
        jQuery.cssHooks[ prefix + suffix ].set = setPositiveNumber;
    }
});
var r20 = /%20/g,
    rbracket = /\[\]$/,
    rCRLF = /\r?\n/g,
    rsubmitterTypes = /^(?:submit|button|image|reset|file)$/i,
    rsubmittable = /^(?:input|select|textarea|keygen)/i;

jQuery.fn.extend({
    serialize: function() {
        return jQuery.param( this.serializeArray() );
    },
    serializeArray: function() {
        return this.map(function(){
            // Can add propHook for "elements" to filter or add form elements
            var elements = jQuery.prop( this, "elements" );
            return elements ? jQuery.makeArray( elements ) : this;
        })
        .filter(function(){
            var type = this.type;
            // Use .is(":disabled") so that fieldset[disabled] works
            return this.name && !jQuery( this ).is( ":disabled" ) &&
                rsubmittable.test( this.nodeName ) && !rsubmitterTypes.test( type ) &&
                ( this.checked || !manipulation_rcheckableType.test( type ) );
        })
        .map(function( i, elem ){
            var val = jQuery( this ).val();

            return val == null ?
                null :
                jQuery.isArray( val ) ?
                    jQuery.map( val, function( val ){
                        return { name: elem.name, value: val.replace( rCRLF, "\r\n" ) };
                    }) :
                    { name: elem.name, value: val.replace( rCRLF, "\r\n" ) };
        }).get();
    }
});

//Serialize an array of form elements or a set of
//key/values into a query string
jQuery.param = function( a, traditional ) {
    var prefix,
        s = [],
        add = function( key, value ) {
            // If value is a function, invoke it and return its value
            value = jQuery.isFunction( value ) ? value() : ( value == null ? "" : value );
            s[ s.length ] = encodeURIComponent( key ) + "=" + encodeURIComponent( value );
        };

    // Set traditional to true for jQuery <= 1.3.2 behavior.
    if ( traditional === undefined ) {
        traditional = jQuery.ajaxSettings && jQuery.ajaxSettings.traditional;
    }

    // If an array was passed in, assume that it is an array of form elements.
    if ( jQuery.isArray( a ) || ( a.jquery && !jQuery.isPlainObject( a ) ) ) {
        // Serialize the form elements
        jQuery.each( a, function() {
            add( this.name, this.value );
        });

    } else {
        // If traditional, encode the "old" way (the way 1.3.2 or older
        // did it), otherwise encode params recursively.
        for ( prefix in a ) {
            buildParams( prefix, a[ prefix ], traditional, add );
        }
    }

    // Return the resulting serialization
    return s.join( "&" ).replace( r20, "+" );
};

function buildParams( prefix, obj, traditional, add ) {
    var name;

    if ( jQuery.isArray( obj ) ) {
        // Serialize array item.
        jQuery.each( obj, function( i, v ) {
            if ( traditional || rbracket.test( prefix ) ) {
                // Treat each array item as a scalar.
                add( prefix, v );

            } else {
                // Item is non-scalar (array or object), encode its numeric index.
                buildParams( prefix + "[" + ( typeof v === "object" ? i : "" ) + "]", v, traditional, add );
            }
        });

    } else if ( !traditional && jQuery.type( obj ) === "object" ) {
        // Serialize object item.
        for ( name in obj ) {
            buildParams( prefix + "[" + name + "]", obj[ name ], traditional, add );
        }

    } else {
        // Serialize scalar item.
        add( prefix, obj );
    }
}
jQuery.each( ("blur focus focusin focusout load resize scroll unload click dblclick " +
    "mousedown mouseup mousemove mouseover mouseout mouseenter mouseleave " +
    "change select submit keydown keypress keyup error contextmenu").split(" "), function( i, name ) {

    // Handle event binding
    jQuery.fn[ name ] = function( data, fn ) {
        return arguments.length > 0 ?
            this.on( name, null, data, fn ) :
            this.trigger( name );
    };
});

jQuery.fn.hover = function( fnOver, fnOut ) {
    return this.mouseenter( fnOver ).mouseleave( fnOut || fnOver );
};
var
    // Document location
    ajaxLocParts,
    ajaxLocation,
    ajax_nonce = jQuery.now(),

    ajax_rquery = /\?/,
    rhash = /#.*$/,
    rts = /([?&])_=[^&]*/,
    rheaders = /^(.*?):[ \t]*([^\r\n]*)\r?$/mg, // IE leaves an \r character at EOL
    // #7653, #8125, #8152: local protocol detection
    rlocalProtocol = /^(?:about|app|app-storage|.+-extension|file|res|widget):$/,
    rnoContent = /^(?:GET|HEAD)$/,
    rprotocol = /^\/\//,
    rurl = /^([\w.+-]+:)(?:\/\/([^\/?#:]*)(?::(\d+)|)|)/,

    // Keep a copy of the old load method
    _load = jQuery.fn.load,

    /* Prefilters
     * 1) They are useful to introduce custom dataTypes (see ajax/jsonp.js for an example)
     * 2) These are called:
     *    - BEFORE asking for a transport
     *    - AFTER param serialization (s.data is a string if s.processData is true)
     * 3) key is the dataType
     * 4) the catchall symbol "*" can be used
     * 5) execution will start with transport dataType and THEN continue down to "*" if needed
     */
    prefilters = {},

    /* Transports bindings
     * 1) key is the dataType
     * 2) the catchall symbol "*" can be used
     * 3) selection will start with transport dataType and THEN go to "*" if needed
     */
    transports = {},

    // Avoid comment-prolog char sequence (#10098); must appease lint and evade compression
    allTypes = "*/".concat("*");

// #8138, IE may throw an exception when accessing
// a field from window.location if document.domain has been set
try {
    ajaxLocation = location.href;
} catch( e ) {
    // Use the href attribute of an A element
    // since IE will modify it given document.location
    ajaxLocation = document.createElement( "a" );
    ajaxLocation.href = "";
    ajaxLocation = ajaxLocation.href;
}

// Segment location into parts
ajaxLocParts = rurl.exec( ajaxLocation.toLowerCase() ) || [];

// Base "constructor" for jQuery.ajaxPrefilter and jQuery.ajaxTransport
function addToPrefiltersOrTransports( structure ) {

    // dataTypeExpression is optional and defaults to "*"
    return function( dataTypeExpression, func ) {

        if ( typeof dataTypeExpression !== "string" ) {
            func = dataTypeExpression;
            dataTypeExpression = "*";
        }

        var dataType,
            i = 0,
            dataTypes = dataTypeExpression.toLowerCase().match( core_rnotwhite ) || [];

        if ( jQuery.isFunction( func ) ) {
            // For each dataType in the dataTypeExpression
            while ( (dataType = dataTypes[i++]) ) {
                // Prepend if requested
                if ( dataType[0] === "+" ) {
                    dataType = dataType.slice( 1 ) || "*";
                    (structure[ dataType ] = structure[ dataType ] || []).unshift( func );

                // Otherwise append
                } else {
                    (structure[ dataType ] = structure[ dataType ] || []).push( func );
                }
            }
        }
    };
}

// Base inspection function for prefilters and transports
function inspectPrefiltersOrTransports( structure, options, originalOptions, jqXHR ) {

    var inspected = {},
        seekingTransport = ( structure === transports );

    function inspect( dataType ) {
        var selected;
        inspected[ dataType ] = true;
        jQuery.each( structure[ dataType ] || [], function( _, prefilterOrFactory ) {
            var dataTypeOrTransport = prefilterOrFactory( options, originalOptions, jqXHR );
            if( typeof dataTypeOrTransport === "string" && !seekingTransport && !inspected[ dataTypeOrTransport ] ) {
                options.dataTypes.unshift( dataTypeOrTransport );
                inspect( dataTypeOrTransport );
                return false;
            } else if ( seekingTransport ) {
                return !( selected = dataTypeOrTransport );
            }
        });
        return selected;
    }

    return inspect( options.dataTypes[ 0 ] ) || !inspected[ "*" ] && inspect( "*" );
}

// A special extend for ajax options
// that takes "flat" options (not to be deep extended)
// Fixes #9887
function ajaxExtend( target, src ) {
    var deep, key,
        flatOptions = jQuery.ajaxSettings.flatOptions || {};

    for ( key in src ) {
        if ( src[ key ] !== undefined ) {
            ( flatOptions[ key ] ? target : ( deep || (deep = {}) ) )[ key ] = src[ key ];
        }
    }
    if ( deep ) {
        jQuery.extend( true, target, deep );
    }

    return target;
}

jQuery.fn.load = function( url, params, callback ) {
    if ( typeof url !== "string" && _load ) {
        return _load.apply( this, arguments );
    }

    var selector, response, type,
        self = this,
        off = url.indexOf(" ");

    if ( off >= 0 ) {
        selector = url.slice( off, url.length );
        url = url.slice( 0, off );
    }

    // If it's a function
    if ( jQuery.isFunction( params ) ) {

        // We assume that it's the callback
        callback = params;
        params = undefined;

    // Otherwise, build a param string
    } else if ( params && typeof params === "object" ) {
        type = "POST";
    }

    // If we have elements to modify, make the request
    if ( self.length > 0 ) {
        jQuery.ajax({
            url: url,

            // if "type" variable is undefined, then "GET" method will be used
            type: type,
            dataType: "html",
            data: params
        }).done(function( responseText ) {

            // Save response for use in complete callback
            response = arguments;

            self.html( selector ?

                // If a selector was specified, locate the right elements in a dummy div
                // Exclude scripts to avoid IE 'Permission Denied' errors
                jQuery("<div>").append( jQuery.parseHTML( responseText ) ).find( selector ) :

                // Otherwise use the full result
                responseText );

        }).complete( callback && function( jqXHR, status ) {
            self.each( callback, response || [ jqXHR.responseText, status, jqXHR ] );
        });
    }

    return this;
};

// Attach a bunch of functions for handling common AJAX events
jQuery.each( [ "ajaxStart", "ajaxStop", "ajaxComplete", "ajaxError", "ajaxSuccess", "ajaxSend" ], function( i, type ){
    jQuery.fn[ type ] = function( fn ){
        return this.on( type, fn );
    };
});

jQuery.each( [ "get", "post" ], function( i, method ) {
    jQuery[ method ] = function( url, data, callback, type ) {
        // shift arguments if data argument was omitted
        if ( jQuery.isFunction( data ) ) {
            type = type || callback;
            callback = data;
            data = undefined;
        }

        return jQuery.ajax({
            url: url,
            type: method,
            dataType: type,
            data: data,
            success: callback
        });
    };
});

jQuery.extend({

    // Counter for holding the number of active queries
    active: 0,

    // Last-Modified header cache for next request
    lastModified: {},
    etag: {},

    ajaxSettings: {
        url: ajaxLocation,
        type: "GET",
        isLocal: rlocalProtocol.test( ajaxLocParts[ 1 ] ),
        global: true,
        processData: true,
        async: true,
        contentType: "application/x-www-form-urlencoded; charset=UTF-8",
        /*
        timeout: 0,
        data: null,
        dataType: null,
        username: null,
        password: null,
        cache: null,
        throws: false,
        traditional: false,
        headers: {},
        */

        accepts: {
            "*": allTypes,
            text: "text/plain",
            html: "text/html",
            xml: "application/xml, text/xml",
            json: "application/json, text/javascript"
        },

        contents: {
            xml: /xml/,
            html: /html/,
            json: /json/
        },

        responseFields: {
            xml: "responseXML",
            text: "responseText"
        },

        // Data converters
        // Keys separate source (or catchall "*") and destination types with a single space
        converters: {

            // Convert anything to text
            "* text": window.String,

            // Text to html (true = no transformation)
            "text html": true,

            // Evaluate text as a json expression
            "text json": jQuery.parseJSON,

            // Parse text as xml
            "text xml": jQuery.parseXML
        },

        // For options that shouldn't be deep extended:
        // you can add your own custom options here if
        // and when you create one that shouldn't be
        // deep extended (see ajaxExtend)
        flatOptions: {
            url: true,
            context: true
        }
    },

    // Creates a full fledged settings object into target
    // with both ajaxSettings and settings fields.
    // If target is omitted, writes into ajaxSettings.
    ajaxSetup: function( target, settings ) {
        return settings ?

            // Building a settings object
            ajaxExtend( ajaxExtend( target, jQuery.ajaxSettings ), settings ) :

            // Extending ajaxSettings
            ajaxExtend( jQuery.ajaxSettings, target );
    },

    ajaxPrefilter: addToPrefiltersOrTransports( prefilters ),
    ajaxTransport: addToPrefiltersOrTransports( transports ),

    // Main method
    ajax: function( url, options ) {

        // If url is an object, simulate pre-1.5 signature
        if ( typeof url === "object" ) {
            options = url;
            url = undefined;
        }

        // Force options to be an object
        options = options || {};

        var // Cross-domain detection vars
            parts,
            // Loop variable
            i,
            // URL without anti-cache param
            cacheURL,
            // Response headers as string
            responseHeadersString,
            // timeout handle
            timeoutTimer,

            // To know if global events are to be dispatched
            fireGlobals,

            transport,
            // Response headers
            responseHeaders,
            // Create the final options object
            s = jQuery.ajaxSetup( {}, options ),
            // Callbacks context
            callbackContext = s.context || s,
            // Context for global events is callbackContext if it is a DOM node or jQuery collection
            globalEventContext = s.context && ( callbackContext.nodeType || callbackContext.jquery ) ?
                jQuery( callbackContext ) :
                jQuery.event,
            // Deferreds
            deferred = jQuery.Deferred(),
            completeDeferred = jQuery.Callbacks("once memory"),
            // Status-dependent callbacks
            statusCode = s.statusCode || {},
            // Headers (they are sent all at once)
            requestHeaders = {},
            requestHeadersNames = {},
            // The jqXHR state
            state = 0,
            // Default abort message
            strAbort = "canceled",
            // Fake xhr
            jqXHR = {
                readyState: 0,

                // Builds headers hashtable if needed
                getResponseHeader: function( key ) {
                    var match;
                    if ( state === 2 ) {
                        if ( !responseHeaders ) {
                            responseHeaders = {};
                            while ( (match = rheaders.exec( responseHeadersString )) ) {
                                responseHeaders[ match[1].toLowerCase() ] = match[ 2 ];
                            }
                        }
                        match = responseHeaders[ key.toLowerCase() ];
                    }
                    return match == null ? null : match;
                },

                // Raw string
                getAllResponseHeaders: function() {
                    return state === 2 ? responseHeadersString : null;
                },

                // Caches the header
                setRequestHeader: function( name, value ) {
                    var lname = name.toLowerCase();
                    if ( !state ) {
                        name = requestHeadersNames[ lname ] = requestHeadersNames[ lname ] || name;
                        requestHeaders[ name ] = value;
                    }
                    return this;
                },

                // Overrides response content-type header
                overrideMimeType: function( type ) {
                    if ( !state ) {
                        s.mimeType = type;
                    }
                    return this;
                },

                // Status-dependent callbacks
                statusCode: function( map ) {
                    var code;
                    if ( map ) {
                        if ( state < 2 ) {
                            for ( code in map ) {
                                // Lazy-add the new callback in a way that preserves old ones
                                statusCode[ code ] = [ statusCode[ code ], map[ code ] ];
                            }
                        } else {
                            // Execute the appropriate callbacks
                            jqXHR.always( map[ jqXHR.status ] );
                        }
                    }
                    return this;
                },

                // Cancel the request
                abort: function( statusText ) {
                    var finalText = statusText || strAbort;
                    if ( transport ) {
                        transport.abort( finalText );
                    }
                    done( 0, finalText );
                    return this;
                }
            };

        // Attach deferreds
        deferred.promise( jqXHR ).complete = completeDeferred.add;
        jqXHR.success = jqXHR.done;
        jqXHR.error = jqXHR.fail;

        // Remove hash character (#7531: and string promotion)
        // Add protocol if not provided (#5866: IE7 issue with protocol-less urls)
        // Handle falsy url in the settings object (#10093: consistency with old signature)
        // We also use the url parameter if available
        s.url = ( ( url || s.url || ajaxLocation ) + "" ).replace( rhash, "" ).replace( rprotocol, ajaxLocParts[ 1 ] + "//" );

        // Alias method option to type as per ticket #12004
        s.type = options.method || options.type || s.method || s.type;

        // Extract dataTypes list
        s.dataTypes = jQuery.trim( s.dataType || "*" ).toLowerCase().match( core_rnotwhite ) || [""];

        // A cross-domain request is in order when we have a protocol:host:port mismatch
        if ( s.crossDomain == null ) {
            parts = rurl.exec( s.url.toLowerCase() );
            s.crossDomain = !!( parts &&
                ( parts[ 1 ] !== ajaxLocParts[ 1 ] || parts[ 2 ] !== ajaxLocParts[ 2 ] ||
                    ( parts[ 3 ] || ( parts[ 1 ] === "http:" ? 80 : 443 ) ) !=
                        ( ajaxLocParts[ 3 ] || ( ajaxLocParts[ 1 ] === "http:" ? 80 : 443 ) ) )
            );
        }

        // Convert data if not already a string
        if ( s.data && s.processData && typeof s.data !== "string" ) {
            s.data = jQuery.param( s.data, s.traditional );
        }

        // Apply prefilters
        inspectPrefiltersOrTransports( prefilters, s, options, jqXHR );

        // If request was aborted inside a prefilter, stop there
        if ( state === 2 ) {
            return jqXHR;
        }

        // We can fire global events as of now if asked to
        fireGlobals = s.global;

        // Watch for a new set of requests
        if ( fireGlobals && jQuery.active++ === 0 ) {
            jQuery.event.trigger("ajaxStart");
        }

        // Uppercase the type
        s.type = s.type.toUpperCase();

        // Determine if request has content
        s.hasContent = !rnoContent.test( s.type );

        // Save the URL in case we're toying with the If-Modified-Since
        // and/or If-None-Match header later on
        cacheURL = s.url;

        // More options handling for requests with no content
        if ( !s.hasContent ) {

            // If data is available, append data to url
            if ( s.data ) {
                cacheURL = ( s.url += ( ajax_rquery.test( cacheURL ) ? "&" : "?" ) + s.data );
                // #9682: remove data so that it's not used in an eventual retry
                delete s.data;
            }

            // Add anti-cache in url if needed
            if ( s.cache === false ) {
                s.url = rts.test( cacheURL ) ?

                    // If there is already a '_' parameter, set its value
                    cacheURL.replace( rts, "$1_=" + ajax_nonce++ ) :

                    // Otherwise add one to the end
                    cacheURL + ( ajax_rquery.test( cacheURL ) ? "&" : "?" ) + "_=" + ajax_nonce++;
            }
        }

        // Set the If-Modified-Since and/or If-None-Match header, if in ifModified mode.
        if ( s.ifModified ) {
            if ( jQuery.lastModified[ cacheURL ] ) {
                jqXHR.setRequestHeader( "If-Modified-Since", jQuery.lastModified[ cacheURL ] );
            }
            if ( jQuery.etag[ cacheURL ] ) {
                jqXHR.setRequestHeader( "If-None-Match", jQuery.etag[ cacheURL ] );
            }
        }

        // Set the correct header, if data is being sent
        if ( s.data && s.hasContent && s.contentType !== false || options.contentType ) {
            jqXHR.setRequestHeader( "Content-Type", s.contentType );
        }

        // Set the Accepts header for the server, depending on the dataType
        jqXHR.setRequestHeader(
            "Accept",
            s.dataTypes[ 0 ] && s.accepts[ s.dataTypes[0] ] ?
                s.accepts[ s.dataTypes[0] ] + ( s.dataTypes[ 0 ] !== "*" ? ", " + allTypes + "; q=0.01" : "" ) :
                s.accepts[ "*" ]
        );

        // Check for headers option
        for ( i in s.headers ) {
            jqXHR.setRequestHeader( i, s.headers[ i ] );
        }

        // Allow custom headers/mimetypes and early abort
        if ( s.beforeSend && ( s.beforeSend.call( callbackContext, jqXHR, s ) === false || state === 2 ) ) {
            // Abort if not done already and return
            return jqXHR.abort();
        }

        // aborting is no longer a cancellation
        strAbort = "abort";

        // Install callbacks on deferreds
        for ( i in { success: 1, error: 1, complete: 1 } ) {
            jqXHR[ i ]( s[ i ] );
        }

        // Get transport
        transport = inspectPrefiltersOrTransports( transports, s, options, jqXHR );

        // If no transport, we auto-abort
        if ( !transport ) {
            done( -1, "No Transport" );
        } else {
            jqXHR.readyState = 1;

            // Send global event
            if ( fireGlobals ) {
                globalEventContext.trigger( "ajaxSend", [ jqXHR, s ] );
            }
            // Timeout
            if ( s.async && s.timeout > 0 ) {
                timeoutTimer = setTimeout(function() {
                    jqXHR.abort("timeout");
                }, s.timeout );
            }

            try {
                state = 1;
                transport.send( requestHeaders, done );
            } catch ( e ) {
                // Propagate exception as error if not done
                if ( state < 2 ) {
                    done( -1, e );
                // Simply rethrow otherwise
                } else {
                    throw e;
                }
            }
        }

        // Callback for when everything is done
        function done( status, nativeStatusText, responses, headers ) {
            var isSuccess, success, error, response, modified,
                statusText = nativeStatusText;

            // Called once
            if ( state === 2 ) {
                return;
            }

            // State is "done" now
            state = 2;

            // Clear timeout if it exists
            if ( timeoutTimer ) {
                clearTimeout( timeoutTimer );
            }

            // Dereference transport for early garbage collection
            // (no matter how long the jqXHR object will be used)
            transport = undefined;

            // Cache response headers
            responseHeadersString = headers || "";

            // Set readyState
            jqXHR.readyState = status > 0 ? 4 : 0;

            // Get response data
            if ( responses ) {
                response = ajaxHandleResponses( s, jqXHR, responses );
            }

            // If successful, handle type chaining
            if ( status >= 200 && status < 300 || status === 304 ) {

                // Set the If-Modified-Since and/or If-None-Match header, if in ifModified mode.
                if ( s.ifModified ) {
                    modified = jqXHR.getResponseHeader("Last-Modified");
                    if ( modified ) {
                        jQuery.lastModified[ cacheURL ] = modified;
                    }
                    modified = jqXHR.getResponseHeader("etag");
                    if ( modified ) {
                        jQuery.etag[ cacheURL ] = modified;
                    }
                }

                // if no content
                if ( status === 204 ) {
                    isSuccess = true;
                    statusText = "nocontent";

                // if not modified
                } else if ( status === 304 ) {
                    isSuccess = true;
                    statusText = "notmodified";

                // If we have data, let's convert it
                } else {
                    isSuccess = ajaxConvert( s, response );
                    statusText = isSuccess.state;
                    success = isSuccess.data;
                    error = isSuccess.error;
                    isSuccess = !error;
                }
            } else {
                // We extract error from statusText
                // then normalize statusText and status for non-aborts
                error = statusText;
                if ( status || !statusText ) {
                    statusText = "error";
                    if ( status < 0 ) {
                        status = 0;
                    }
                }
            }

            // Set data for the fake xhr object
            jqXHR.status = status;
            jqXHR.statusText = ( nativeStatusText || statusText ) + "";

            // Success/Error
            if ( isSuccess ) {
                deferred.resolveWith( callbackContext, [ success, statusText, jqXHR ] );
            } else {
                deferred.rejectWith( callbackContext, [ jqXHR, statusText, error ] );
            }

            // Status-dependent callbacks
            jqXHR.statusCode( statusCode );
            statusCode = undefined;

            if ( fireGlobals ) {
                globalEventContext.trigger( isSuccess ? "ajaxSuccess" : "ajaxError",
                    [ jqXHR, s, isSuccess ? success : error ] );
            }

            // Complete
            completeDeferred.fireWith( callbackContext, [ jqXHR, statusText ] );

            if ( fireGlobals ) {
                globalEventContext.trigger( "ajaxComplete", [ jqXHR, s ] );
                // Handle the global AJAX counter
                if ( !( --jQuery.active ) ) {
                    jQuery.event.trigger("ajaxStop");
                }
            }
        }

        return jqXHR;
    },

    getScript: function( url, callback ) {
        return jQuery.get( url, undefined, callback, "script" );
    },

    getJSON: function( url, data, callback ) {
        return jQuery.get( url, data, callback, "json" );
    }
});

/* Handles responses to an ajax request:
 * - sets all responseXXX fields accordingly
 * - finds the right dataType (mediates between content-type and expected dataType)
 * - returns the corresponding response
 */
function ajaxHandleResponses( s, jqXHR, responses ) {
    var firstDataType, ct, finalDataType, type,
        contents = s.contents,
        dataTypes = s.dataTypes,
        responseFields = s.responseFields;

    // Fill responseXXX fields
    for ( type in responseFields ) {
        if ( type in responses ) {
            jqXHR[ responseFields[type] ] = responses[ type ];
        }
    }

    // Remove auto dataType and get content-type in the process
    while( dataTypes[ 0 ] === "*" ) {
        dataTypes.shift();
        if ( ct === undefined ) {
            ct = s.mimeType || jqXHR.getResponseHeader("Content-Type");
        }
    }

    // Check if we're dealing with a known content-type
    if ( ct ) {
        for ( type in contents ) {
            if ( contents[ type ] && contents[ type ].test( ct ) ) {
                dataTypes.unshift( type );
                break;
            }
        }
    }

    // Check to see if we have a response for the expected dataType
    if ( dataTypes[ 0 ] in responses ) {
        finalDataType = dataTypes[ 0 ];
    } else {
        // Try convertible dataTypes
        for ( type in responses ) {
            if ( !dataTypes[ 0 ] || s.converters[ type + " " + dataTypes[0] ] ) {
                finalDataType = type;
                break;
            }
            if ( !firstDataType ) {
                firstDataType = type;
            }
        }
        // Or just use first one
        finalDataType = finalDataType || firstDataType;
    }

    // If we found a dataType
    // We add the dataType to the list if needed
    // and return the corresponding response
    if ( finalDataType ) {
        if ( finalDataType !== dataTypes[ 0 ] ) {
            dataTypes.unshift( finalDataType );
        }
        return responses[ finalDataType ];
    }
}

// Chain conversions given the request and the original response
function ajaxConvert( s, response ) {
    var conv2, current, conv, tmp,
        converters = {},
        i = 0,
        // Work with a copy of dataTypes in case we need to modify it for conversion
        dataTypes = s.dataTypes.slice(),
        prev = dataTypes[ 0 ];

    // Apply the dataFilter if provided
    if ( s.dataFilter ) {
        response = s.dataFilter( response, s.dataType );
    }

    // Create converters map with lowercased keys
    if ( dataTypes[ 1 ] ) {
        for ( conv in s.converters ) {
            converters[ conv.toLowerCase() ] = s.converters[ conv ];
        }
    }

    // Convert to each sequential dataType, tolerating list modification
    for ( ; (current = dataTypes[++i]); ) {

        // There's only work to do if current dataType is non-auto
        if ( current !== "*" ) {

            // Convert response if prev dataType is non-auto and differs from current
            if ( prev !== "*" && prev !== current ) {

                // Seek a direct converter
                conv = converters[ prev + " " + current ] || converters[ "* " + current ];

                // If none found, seek a pair
                if ( !conv ) {
                    for ( conv2 in converters ) {

                        // If conv2 outputs current
                        tmp = conv2.split(" ");
                        if ( tmp[ 1 ] === current ) {

                            // If prev can be converted to accepted input
                            conv = converters[ prev + " " + tmp[ 0 ] ] ||
                                converters[ "* " + tmp[ 0 ] ];
                            if ( conv ) {
                                // Condense equivalence converters
                                if ( conv === true ) {
                                    conv = converters[ conv2 ];

                                // Otherwise, insert the intermediate dataType
                                } else if ( converters[ conv2 ] !== true ) {
                                    current = tmp[ 0 ];
                                    dataTypes.splice( i--, 0, current );
                                }

                                break;
                            }
                        }
                    }
                }

                // Apply converter (if not an equivalence)
                if ( conv !== true ) {

                    // Unless errors are allowed to bubble, catch and return them
                    if ( conv && s["throws"] ) {
                        response = conv( response );
                    } else {
                        try {
                            response = conv( response );
                        } catch ( e ) {
                            return { state: "parsererror", error: conv ? e : "No conversion from " + prev + " to " + current };
                        }
                    }
                }
            }

            // Update prev for next iteration
            prev = current;
        }
    }

    return { state: "success", data: response };
}
// Install script dataType
jQuery.ajaxSetup({
    accepts: {
        script: "text/javascript, application/javascript, application/ecmascript, application/x-ecmascript"
    },
    contents: {
        script: /(?:java|ecma)script/
    },
    converters: {
        "text script": function( text ) {
            jQuery.globalEval( text );
            return text;
        }
    }
});

// Handle cache's special case and global
jQuery.ajaxPrefilter( "script", function( s ) {
    if ( s.cache === undefined ) {
        s.cache = false;
    }
    if ( s.crossDomain ) {
        s.type = "GET";
        s.global = false;
    }
});

// Bind script tag hack transport
jQuery.ajaxTransport( "script", function(s) {

    // This transport only deals with cross domain requests
    if ( s.crossDomain ) {

        var script,
            head = document.head || jQuery("head")[0] || document.documentElement;

        return {

            send: function( _, callback ) {

                script = document.createElement("script");

                script.async = true;

                if ( s.scriptCharset ) {
                    script.charset = s.scriptCharset;
                }

                script.src = s.url;

                // Attach handlers for all browsers
                script.onload = script.onreadystatechange = function( _, isAbort ) {

                    if ( isAbort || !script.readyState || /loaded|complete/.test( script.readyState ) ) {

                        // Handle memory leak in IE
                        script.onload = script.onreadystatechange = null;

                        // Remove the script
                        if ( script.parentNode ) {
                            script.parentNode.removeChild( script );
                        }

                        // Dereference the script
                        script = null;

                        // Callback if not abort
                        if ( !isAbort ) {
                            callback( 200, "success" );
                        }
                    }
                };

                // Circumvent IE6 bugs with base elements (#2709 and #4378) by prepending
                // Use native DOM manipulation to avoid our domManip AJAX trickery
                head.insertBefore( script, head.firstChild );
            },

            abort: function() {
                if ( script ) {
                    script.onload( undefined, true );
                }
            }
        };
    }
});
var oldCallbacks = [],
    rjsonp = /(=)\?(?=&|$)|\?\?/;

// Default jsonp settings
jQuery.ajaxSetup({
    jsonp: "callback",
    jsonpCallback: function() {
        var callback = oldCallbacks.pop() || ( jQuery.expando + "_" + ( ajax_nonce++ ) );
        this[ callback ] = true;
        return callback;
    }
});

// Detect, normalize options and install callbacks for jsonp requests
jQuery.ajaxPrefilter( "json jsonp", function( s, originalSettings, jqXHR ) {

    var callbackName, overwritten, responseContainer,
        jsonProp = s.jsonp !== false && ( rjsonp.test( s.url ) ?
            "url" :
            typeof s.data === "string" && !( s.contentType || "" ).indexOf("application/x-www-form-urlencoded") && rjsonp.test( s.data ) && "data"
        );

    // Handle iff the expected data type is "jsonp" or we have a parameter to set
    if ( jsonProp || s.dataTypes[ 0 ] === "jsonp" ) {

        // Get callback name, remembering preexisting value associated with it
        callbackName = s.jsonpCallback = jQuery.isFunction( s.jsonpCallback ) ?
            s.jsonpCallback() :
            s.jsonpCallback;

        // Insert callback into url or form data
        if ( jsonProp ) {
            s[ jsonProp ] = s[ jsonProp ].replace( rjsonp, "$1" + callbackName );
        } else if ( s.jsonp !== false ) {
            s.url += ( ajax_rquery.test( s.url ) ? "&" : "?" ) + s.jsonp + "=" + callbackName;
        }

        // Use data converter to retrieve json after script execution
        s.converters["script json"] = function() {
            if ( !responseContainer ) {
                jQuery.error( callbackName + " was not called" );
            }
            return responseContainer[ 0 ];
        };

        // force json dataType
        s.dataTypes[ 0 ] = "json";

        // Install callback
        overwritten = window[ callbackName ];
        window[ callbackName ] = function() {
            responseContainer = arguments;
        };

        // Clean-up function (fires after converters)
        jqXHR.always(function() {
            // Restore preexisting value
            window[ callbackName ] = overwritten;

            // Save back as free
            if ( s[ callbackName ] ) {
                // make sure that re-using the options doesn't screw things around
                s.jsonpCallback = originalSettings.jsonpCallback;

                // save the callback name for future use
                oldCallbacks.push( callbackName );
            }

            // Call if it was a function and we have a response
            if ( responseContainer && jQuery.isFunction( overwritten ) ) {
                overwritten( responseContainer[ 0 ] );
            }

            responseContainer = overwritten = undefined;
        });

        // Delegate to script
        return "script";
    }
});
var xhrCallbacks, xhrSupported,
    xhrId = 0,
    // #5280: Internet Explorer will keep connections alive if we don't abort on unload
    xhrOnUnloadAbort = window.ActiveXObject && function() {
        // Abort all pending requests
        var key;
        for ( key in xhrCallbacks ) {
            xhrCallbacks[ key ]( undefined, true );
        }
    };

// Functions to create xhrs
function createStandardXHR() {
    try {
        return new window.XMLHttpRequest();
    } catch( e ) {}
}

function createActiveXHR() {
    try {
        return new window.ActiveXObject("Microsoft.XMLHTTP");
    } catch( e ) {}
}

// Create the request object
// (This is still attached to ajaxSettings for backward compatibility)
jQuery.ajaxSettings.xhr = window.ActiveXObject ?
    /* Microsoft failed to properly
     * implement the XMLHttpRequest in IE7 (can't request local files),
     * so we use the ActiveXObject when it is available
     * Additionally XMLHttpRequest can be disabled in IE7/IE8 so
     * we need a fallback.
     */
    function() {
        return !this.isLocal && createStandardXHR() || createActiveXHR();
    } :
    // For all other browsers, use the standard XMLHttpRequest object
    createStandardXHR;

// Determine support properties
xhrSupported = jQuery.ajaxSettings.xhr();
jQuery.support.cors = !!xhrSupported && ( "withCredentials" in xhrSupported );
xhrSupported = jQuery.support.ajax = !!xhrSupported;

// Create transport if the browser can provide an xhr
if ( xhrSupported ) {

    jQuery.ajaxTransport(function( s ) {
        // Cross domain only allowed if supported through XMLHttpRequest
        if ( !s.crossDomain || jQuery.support.cors ) {

            var callback;

            return {
                send: function( headers, complete ) {

                    // Get a new xhr
                    var handle, i,
                        xhr = s.xhr();

                    // Open the socket
                    // Passing null username, generates a login popup on Opera (#2865)
                    if ( s.username ) {
                        xhr.open( s.type, s.url, s.async, s.username, s.password );
                    } else {
                        xhr.open( s.type, s.url, s.async );
                    }

                    // Apply custom fields if provided
                    if ( s.xhrFields ) {
                        for ( i in s.xhrFields ) {
                            xhr[ i ] = s.xhrFields[ i ];
                        }
                    }

                    // Override mime type if needed
                    if ( s.mimeType && xhr.overrideMimeType ) {
                        xhr.overrideMimeType( s.mimeType );
                    }

                    // X-Requested-With header
                    // For cross-domain requests, seeing as conditions for a preflight are
                    // akin to a jigsaw puzzle, we simply never set it to be sure.
                    // (it can always be set on a per-request basis or even using ajaxSetup)
                    // For same-domain requests, won't change header if already provided.
                    if ( !s.crossDomain && !headers["X-Requested-With"] ) {
                        headers["X-Requested-With"] = "XMLHttpRequest";
                    }

                    // Need an extra try/catch for cross domain requests in Firefox 3
                    try {
                        for ( i in headers ) {
                            xhr.setRequestHeader( i, headers[ i ] );
                        }
                    } catch( err ) {}

                    // Do send the request
                    // This may raise an exception which is actually
                    // handled in jQuery.ajax (so no try/catch here)
                    xhr.send( ( s.hasContent && s.data ) || null );

                    // Listener
                    callback = function( _, isAbort ) {
                        var status, responseHeaders, statusText, responses;

                        // Firefox throws exceptions when accessing properties
                        // of an xhr when a network error occurred
                        // http://helpful.knobs-dials.com/index.php/Component_returned_failure_code:_0x80040111_(NS_ERROR_NOT_AVAILABLE)
                        try {

                            // Was never called and is aborted or complete
                            if ( callback && ( isAbort || xhr.readyState === 4 ) ) {

                                // Only called once
                                callback = undefined;

                                // Do not keep as active anymore
                                if ( handle ) {
                                    xhr.onreadystatechange = jQuery.noop;
                                    if ( xhrOnUnloadAbort ) {
                                        delete xhrCallbacks[ handle ];
                                    }
                                }

                                // If it's an abort
                                if ( isAbort ) {
                                    // Abort it manually if needed
                                    if ( xhr.readyState !== 4 ) {
                                        xhr.abort();
                                    }
                                } else {
                                    responses = {};
                                    status = xhr.status;
                                    responseHeaders = xhr.getAllResponseHeaders();

                                    // XXX(basta): This is a hack to work around bug 858225
                                    if (!responseHeaders) {
                                        responseHeaders = 'Content-Type: ' + xhr.getResponseHeader('Content-Type');
                                    }

                                    // When requesting binary data, IE6-9 will throw an exception
                                    // on any attempt to access responseText (#11426)
                                    if ( typeof xhr.responseText === "string" ) {
                                        responses.text = xhr.responseText;
                                    }

                                    // Firefox throws an exception when accessing
                                    // statusText for faulty cross-domain requests
                                    try {
                                        statusText = xhr.statusText;
                                    } catch( e ) {
                                        // We normalize with Webkit giving an empty statusText
                                        statusText = "";
                                    }

                                    // Filter status for non standard behaviors

                                    // If the request is local and we have data: assume a success
                                    // (success with no data won't get notified, that's the best we
                                    // can do given current implementations)
                                    if ( !status && s.isLocal && !s.crossDomain ) {
                                        status = responses.text ? 200 : 404;
                                    // IE - #1450: sometimes returns 1223 when it should be 204
                                    } else if ( status === 1223 ) {
                                        status = 204;
                                    }
                                }
                            }
                        } catch( firefoxAccessException ) {
                            if ( !isAbort ) {
                                complete( -1, firefoxAccessException );
                            }
                        }

                        // Call complete if needed
                        if ( responses ) {
                            complete( status, statusText, responses, responseHeaders );
                        }
                    };

                    if ( !s.async ) {
                        // if we're in sync mode we fire the callback
                        callback();
                    } else if ( xhr.readyState === 4 ) {
                        // (IE6 & IE7) if it's in cache and has been
                        // retrieved directly we need to fire the callback
                        setTimeout( callback );
                    } else {
                        handle = ++xhrId;
                        if ( xhrOnUnloadAbort ) {
                            // Create the active xhrs callbacks list if needed
                            // and attach the unload handler
                            if ( !xhrCallbacks ) {
                                xhrCallbacks = {};
                                jQuery( window ).unload( xhrOnUnloadAbort );
                            }
                            // Add to list of active xhrs callbacks
                            xhrCallbacks[ handle ] = callback;
                        }
                        xhr.onreadystatechange = callback;
                    }
                },

                abort: function() {
                    if ( callback ) {
                        callback( undefined, true );
                    }
                }
            };
        }
    });
}
var fxNow, timerId,
    rfxtypes = /^(?:toggle|show|hide)$/,
    rfxnum = new RegExp( "^(?:([+-])=|)(" + core_pnum + ")([a-z%]*)$", "i" ),
    rrun = /queueHooks$/,
    animationPrefilters = [ defaultPrefilter ],
    tweeners = {
        "*": [function( prop, value ) {
            var end, unit,
                tween = this.createTween( prop, value ),
                parts = rfxnum.exec( value ),
                target = tween.cur(),
                start = +target || 0,
                scale = 1,
                maxIterations = 20;

            if ( parts ) {
                end = +parts[2];
                unit = parts[3] || ( jQuery.cssNumber[ prop ] ? "" : "px" );

                // We need to compute starting value
                if ( unit !== "px" && start ) {
                    // Iteratively approximate from a nonzero starting point
                    // Prefer the current property, because this process will be trivial if it uses the same units
                    // Fallback to end or a simple constant
                    start = jQuery.css( tween.elem, prop, true ) || end || 1;

                    do {
                        // If previous iteration zeroed out, double until we get *something*
                        // Use a string for doubling factor so we don't accidentally see scale as unchanged below
                        scale = scale || ".5";

                        // Adjust and apply
                        start = start / scale;
                        jQuery.style( tween.elem, prop, start + unit );

                    // Update scale, tolerating zero or NaN from tween.cur()
                    // And breaking the loop if scale is unchanged or perfect, or if we've just had enough
                    } while ( scale !== (scale = tween.cur() / target) && scale !== 1 && --maxIterations );
                }

                tween.unit = unit;
                tween.start = start;
                // If a +=/-= token was provided, we're doing a relative animation
                tween.end = parts[1] ? start + ( parts[1] + 1 ) * end : end;
            }
            return tween;
        }]
    };

// Animations created synchronously will run synchronously
function createFxNow() {
    setTimeout(function() {
        fxNow = undefined;
    });
    return ( fxNow = jQuery.now() );
}

function createTweens( animation, props ) {
    jQuery.each( props, function( prop, value ) {
        var collection = ( tweeners[ prop ] || [] ).concat( tweeners[ "*" ] ),
            index = 0,
            length = collection.length;
        for ( ; index < length; index++ ) {
            if ( collection[ index ].call( animation, prop, value ) ) {

                // we're done with this property
                return;
            }
        }
    });
}

function Animation( elem, properties, options ) {
    var result,
        stopped,
        index = 0,
        length = animationPrefilters.length,
        deferred = jQuery.Deferred().always( function() {
            // don't match elem in the :animated selector
            delete tick.elem;
        }),
        tick = function() {
            if ( stopped ) {
                return false;
            }
            var currentTime = fxNow || createFxNow(),
                remaining = Math.max( 0, animation.startTime + animation.duration - currentTime ),
                // archaic crash bug won't allow us to use 1 - ( 0.5 || 0 ) (#12497)
                temp = remaining / animation.duration || 0,
                percent = 1 - temp,
                index = 0,
                length = animation.tweens.length;

            for ( ; index < length ; index++ ) {
                animation.tweens[ index ].run( percent );
            }

            deferred.notifyWith( elem, [ animation, percent, remaining ]);

            if ( percent < 1 && length ) {
                return remaining;
            } else {
                deferred.resolveWith( elem, [ animation ] );
                return false;
            }
        },
        animation = deferred.promise({
            elem: elem,
            props: jQuery.extend( {}, properties ),
            opts: jQuery.extend( true, { specialEasing: {} }, options ),
            originalProperties: properties,
            originalOptions: options,
            startTime: fxNow || createFxNow(),
            duration: options.duration,
            tweens: [],
            createTween: function( prop, end ) {
                var tween = jQuery.Tween( elem, animation.opts, prop, end,
                        animation.opts.specialEasing[ prop ] || animation.opts.easing );
                animation.tweens.push( tween );
                return tween;
            },
            stop: function( gotoEnd ) {
                var index = 0,
                    // if we are going to the end, we want to run all the tweens
                    // otherwise we skip this part
                    length = gotoEnd ? animation.tweens.length : 0;
                if ( stopped ) {
                    return this;
                }
                stopped = true;
                for ( ; index < length ; index++ ) {
                    animation.tweens[ index ].run( 1 );
                }

                // resolve when we played the last frame
                // otherwise, reject
                if ( gotoEnd ) {
                    deferred.resolveWith( elem, [ animation, gotoEnd ] );
                } else {
                    deferred.rejectWith( elem, [ animation, gotoEnd ] );
                }
                return this;
            }
        }),
        props = animation.props;

    propFilter( props, animation.opts.specialEasing );

    for ( ; index < length ; index++ ) {
        result = animationPrefilters[ index ].call( animation, elem, props, animation.opts );
        if ( result ) {
            return result;
        }
    }

    createTweens( animation, props );

    if ( jQuery.isFunction( animation.opts.start ) ) {
        animation.opts.start.call( elem, animation );
    }

    jQuery.fx.timer(
        jQuery.extend( tick, {
            elem: elem,
            anim: animation,
            queue: animation.opts.queue
        })
    );

    // attach callbacks from options
    return animation.progress( animation.opts.progress )
        .done( animation.opts.done, animation.opts.complete )
        .fail( animation.opts.fail )
        .always( animation.opts.always );
}

function propFilter( props, specialEasing ) {
    var value, name, index, easing, hooks;

    // camelCase, specialEasing and expand cssHook pass
    for ( index in props ) {
        name = jQuery.camelCase( index );
        easing = specialEasing[ name ];
        value = props[ index ];
        if ( jQuery.isArray( value ) ) {
            easing = value[ 1 ];
            value = props[ index ] = value[ 0 ];
        }

        if ( index !== name ) {
            props[ name ] = value;
            delete props[ index ];
        }

        hooks = jQuery.cssHooks[ name ];
        if ( hooks && "expand" in hooks ) {
            value = hooks.expand( value );
            delete props[ name ];

            // not quite $.extend, this wont overwrite keys already present.
            // also - reusing 'index' from above because we have the correct "name"
            for ( index in value ) {
                if ( !( index in props ) ) {
                    props[ index ] = value[ index ];
                    specialEasing[ index ] = easing;
                }
            }
        } else {
            specialEasing[ name ] = easing;
        }
    }
}

jQuery.Animation = jQuery.extend( Animation, {

    tweener: function( props, callback ) {
        if ( jQuery.isFunction( props ) ) {
            callback = props;
            props = [ "*" ];
        } else {
            props = props.split(" ");
        }

        var prop,
            index = 0,
            length = props.length;

        for ( ; index < length ; index++ ) {
            prop = props[ index ];
            tweeners[ prop ] = tweeners[ prop ] || [];
            tweeners[ prop ].unshift( callback );
        }
    },

    prefilter: function( callback, prepend ) {
        if ( prepend ) {
            animationPrefilters.unshift( callback );
        } else {
            animationPrefilters.push( callback );
        }
    }
});

function defaultPrefilter( elem, props, opts ) {
    /*jshint validthis:true */
    var prop, index, length,
        value, dataShow, toggle,
        tween, hooks, oldfire,
        anim = this,
        style = elem.style,
        orig = {},
        handled = [],
        hidden = elem.nodeType && isHidden( elem );

    // handle queue: false promises
    if ( !opts.queue ) {
        hooks = jQuery._queueHooks( elem, "fx" );
        if ( hooks.unqueued == null ) {
            hooks.unqueued = 0;
            oldfire = hooks.empty.fire;
            hooks.empty.fire = function() {
                if ( !hooks.unqueued ) {
                    oldfire();
                }
            };
        }
        hooks.unqueued++;

        anim.always(function() {
            // doing this makes sure that the complete handler will be called
            // before this completes
            anim.always(function() {
                hooks.unqueued--;
                if ( !jQuery.queue( elem, "fx" ).length ) {
                    hooks.empty.fire();
                }
            });
        });
    }

    // height/width overflow pass
    if ( elem.nodeType === 1 && ( "height" in props || "width" in props ) ) {
        // Make sure that nothing sneaks out
        // Record all 3 overflow attributes because IE does not
        // change the overflow attribute when overflowX and
        // overflowY are set to the same value
        opts.overflow = [ style.overflow, style.overflowX, style.overflowY ];

        // Set display property to inline-block for height/width
        // animations on inline elements that are having width/height animated
        if ( jQuery.css( elem, "display" ) === "inline" &&
                jQuery.css( elem, "float" ) === "none" ) {

            // inline-level elements accept inline-block;
            // block-level elements need to be inline with layout
            if ( !jQuery.support.inlineBlockNeedsLayout || css_defaultDisplay( elem.nodeName ) === "inline" ) {
                style.display = "inline-block";

            } else {
                style.zoom = 1;
            }
        }
    }

    if ( opts.overflow ) {
        style.overflow = "hidden";
        if ( !jQuery.support.shrinkWrapBlocks ) {
            anim.always(function() {
                style.overflow = opts.overflow[ 0 ];
                style.overflowX = opts.overflow[ 1 ];
                style.overflowY = opts.overflow[ 2 ];
            });
        }
    }


    // show/hide pass
    for ( index in props ) {
        value = props[ index ];
        if ( rfxtypes.exec( value ) ) {
            delete props[ index ];
            toggle = toggle || value === "toggle";
            if ( value === ( hidden ? "hide" : "show" ) ) {
                continue;
            }
            handled.push( index );
        }
    }

    length = handled.length;
    if ( length ) {
        dataShow = jQuery._data( elem, "fxshow" ) || jQuery._data( elem, "fxshow", {} );
        if ( "hidden" in dataShow ) {
            hidden = dataShow.hidden;
        }

        // store state if its toggle - enables .stop().toggle() to "reverse"
        if ( toggle ) {
            dataShow.hidden = !hidden;
        }
        if ( hidden ) {
            jQuery( elem ).show();
        } else {
            anim.done(function() {
                jQuery( elem ).hide();
            });
        }
        anim.done(function() {
            var prop;
            jQuery._removeData( elem, "fxshow" );
            for ( prop in orig ) {
                jQuery.style( elem, prop, orig[ prop ] );
            }
        });
        for ( index = 0 ; index < length ; index++ ) {
            prop = handled[ index ];
            tween = anim.createTween( prop, hidden ? dataShow[ prop ] : 0 );
            orig[ prop ] = dataShow[ prop ] || jQuery.style( elem, prop );

            if ( !( prop in dataShow ) ) {
                dataShow[ prop ] = tween.start;
                if ( hidden ) {
                    tween.end = tween.start;
                    tween.start = prop === "width" || prop === "height" ? 1 : 0;
                }
            }
        }
    }
}

function Tween( elem, options, prop, end, easing ) {
    return new Tween.prototype.init( elem, options, prop, end, easing );
}
jQuery.Tween = Tween;

Tween.prototype = {
    constructor: Tween,
    init: function( elem, options, prop, end, easing, unit ) {
        this.elem = elem;
        this.prop = prop;
        this.easing = easing || "swing";
        this.options = options;
        this.start = this.now = this.cur();
        this.end = end;
        this.unit = unit || ( jQuery.cssNumber[ prop ] ? "" : "px" );
    },
    cur: function() {
        var hooks = Tween.propHooks[ this.prop ];

        return hooks && hooks.get ?
            hooks.get( this ) :
            Tween.propHooks._default.get( this );
    },
    run: function( percent ) {
        var eased,
            hooks = Tween.propHooks[ this.prop ];

        if ( this.options.duration ) {
            this.pos = eased = jQuery.easing[ this.easing ](
                percent, this.options.duration * percent, 0, 1, this.options.duration
            );
        } else {
            this.pos = eased = percent;
        }
        this.now = ( this.end - this.start ) * eased + this.start;

        if ( this.options.step ) {
            this.options.step.call( this.elem, this.now, this );
        }

        if ( hooks && hooks.set ) {
            hooks.set( this );
        } else {
            Tween.propHooks._default.set( this );
        }
        return this;
    }
};

Tween.prototype.init.prototype = Tween.prototype;

Tween.propHooks = {
    _default: {
        get: function( tween ) {
            var result;

            if ( tween.elem[ tween.prop ] != null &&
                (!tween.elem.style || tween.elem.style[ tween.prop ] == null) ) {
                return tween.elem[ tween.prop ];
            }

            // passing an empty string as a 3rd parameter to .css will automatically
            // attempt a parseFloat and fallback to a string if the parse fails
            // so, simple values such as "10px" are parsed to Float.
            // complex values such as "rotate(1rad)" are returned as is.
            result = jQuery.css( tween.elem, tween.prop, "" );
            // Empty strings, null, undefined and "auto" are converted to 0.
            return !result || result === "auto" ? 0 : result;
        },
        set: function( tween ) {
            // use step hook for back compat - use cssHook if its there - use .style if its
            // available and use plain properties where available
            if ( jQuery.fx.step[ tween.prop ] ) {
                jQuery.fx.step[ tween.prop ]( tween );
            } else if ( tween.elem.style && ( tween.elem.style[ jQuery.cssProps[ tween.prop ] ] != null || jQuery.cssHooks[ tween.prop ] ) ) {
                jQuery.style( tween.elem, tween.prop, tween.now + tween.unit );
            } else {
                tween.elem[ tween.prop ] = tween.now;
            }
        }
    }
};

// Remove in 2.0 - this supports IE8's panic based approach
// to setting things on disconnected nodes

Tween.propHooks.scrollTop = Tween.propHooks.scrollLeft = {
    set: function( tween ) {
        if ( tween.elem.nodeType && tween.elem.parentNode ) {
            tween.elem[ tween.prop ] = tween.now;
        }
    }
};

jQuery.each([ "toggle", "show", "hide" ], function( i, name ) {
    var cssFn = jQuery.fn[ name ];
    jQuery.fn[ name ] = function( speed, easing, callback ) {
        return speed == null || typeof speed === "boolean" ?
            cssFn.apply( this, arguments ) :
            this.animate( genFx( name, true ), speed, easing, callback );
    };
});

jQuery.fn.extend({
    fadeTo: function( speed, to, easing, callback ) {

        // show any hidden elements after setting opacity to 0
        return this.filter( isHidden ).css( "opacity", 0 ).show()

            // animate to the value specified
            .end().animate({ opacity: to }, speed, easing, callback );
    },
    animate: function( prop, speed, easing, callback ) {
        var empty = jQuery.isEmptyObject( prop ),
            optall = jQuery.speed( speed, easing, callback ),
            doAnimation = function() {
                // Operate on a copy of prop so per-property easing won't be lost
                var anim = Animation( this, jQuery.extend( {}, prop ), optall );
                doAnimation.finish = function() {
                    anim.stop( true );
                };
                // Empty animations, or finishing resolves immediately
                if ( empty || jQuery._data( this, "finish" ) ) {
                    anim.stop( true );
                }
            };
            doAnimation.finish = doAnimation;

        return empty || optall.queue === false ?
            this.each( doAnimation ) :
            this.queue( optall.queue, doAnimation );
    },
    stop: function( type, clearQueue, gotoEnd ) {
        var stopQueue = function( hooks ) {
            var stop = hooks.stop;
            delete hooks.stop;
            stop( gotoEnd );
        };

        if ( typeof type !== "string" ) {
            gotoEnd = clearQueue;
            clearQueue = type;
            type = undefined;
        }
        if ( clearQueue && type !== false ) {
            this.queue( type || "fx", [] );
        }

        return this.each(function() {
            var dequeue = true,
                index = type != null && type + "queueHooks",
                timers = jQuery.timers,
                data = jQuery._data( this );

            if ( index ) {
                if ( data[ index ] && data[ index ].stop ) {
                    stopQueue( data[ index ] );
                }
            } else {
                for ( index in data ) {
                    if ( data[ index ] && data[ index ].stop && rrun.test( index ) ) {
                        stopQueue( data[ index ] );
                    }
                }
            }

            for ( index = timers.length; index--; ) {
                if ( timers[ index ].elem === this && (type == null || timers[ index ].queue === type) ) {
                    timers[ index ].anim.stop( gotoEnd );
                    dequeue = false;
                    timers.splice( index, 1 );
                }
            }

            // start the next in the queue if the last step wasn't forced
            // timers currently will call their complete callbacks, which will dequeue
            // but only if they were gotoEnd
            if ( dequeue || !gotoEnd ) {
                jQuery.dequeue( this, type );
            }
        });
    },
    finish: function( type ) {
        if ( type !== false ) {
            type = type || "fx";
        }
        return this.each(function() {
            var index,
                data = jQuery._data( this ),
                queue = data[ type + "queue" ],
                hooks = data[ type + "queueHooks" ],
                timers = jQuery.timers,
                length = queue ? queue.length : 0;

            // enable finishing flag on private data
            data.finish = true;

            // empty the queue first
            jQuery.queue( this, type, [] );

            if ( hooks && hooks.cur && hooks.cur.finish ) {
                hooks.cur.finish.call( this );
            }

            // look for any active animations, and finish them
            for ( index = timers.length; index--; ) {
                if ( timers[ index ].elem === this && timers[ index ].queue === type ) {
                    timers[ index ].anim.stop( true );
                    timers.splice( index, 1 );
                }
            }

            // look for any animations in the old queue and finish them
            for ( index = 0; index < length; index++ ) {
                if ( queue[ index ] && queue[ index ].finish ) {
                    queue[ index ].finish.call( this );
                }
            }

            // turn off finishing flag
            delete data.finish;
        });
    }
});

// Generate parameters to create a standard animation
function genFx( type, includeWidth ) {
    var which,
        attrs = { height: type },
        i = 0;

    // if we include width, step value is 1 to do all cssExpand values,
    // if we don't include width, step value is 2 to skip over Left and Right
    includeWidth = includeWidth? 1 : 0;
    for( ; i < 4 ; i += 2 - includeWidth ) {
        which = cssExpand[ i ];
        attrs[ "margin" + which ] = attrs[ "padding" + which ] = type;
    }

    if ( includeWidth ) {
        attrs.opacity = attrs.width = type;
    }

    return attrs;
}

// Generate shortcuts for custom animations
jQuery.each({
    slideDown: genFx("show"),
    slideUp: genFx("hide"),
    slideToggle: genFx("toggle"),
    fadeIn: { opacity: "show" },
    fadeOut: { opacity: "hide" },
    fadeToggle: { opacity: "toggle" }
}, function( name, props ) {
    jQuery.fn[ name ] = function( speed, easing, callback ) {
        return this.animate( props, speed, easing, callback );
    };
});

jQuery.speed = function( speed, easing, fn ) {
    var opt = speed && typeof speed === "object" ? jQuery.extend( {}, speed ) : {
        complete: fn || !fn && easing ||
            jQuery.isFunction( speed ) && speed,
        duration: speed,
        easing: fn && easing || easing && !jQuery.isFunction( easing ) && easing
    };

    opt.duration = jQuery.fx.off ? 0 : typeof opt.duration === "number" ? opt.duration :
        opt.duration in jQuery.fx.speeds ? jQuery.fx.speeds[ opt.duration ] : jQuery.fx.speeds._default;

    // normalize opt.queue - true/undefined/null -> "fx"
    if ( opt.queue == null || opt.queue === true ) {
        opt.queue = "fx";
    }

    // Queueing
    opt.old = opt.complete;

    opt.complete = function() {
        if ( jQuery.isFunction( opt.old ) ) {
            opt.old.call( this );
        }

        if ( opt.queue ) {
            jQuery.dequeue( this, opt.queue );
        }
    };

    return opt;
};

jQuery.easing = {
    linear: function( p ) {
        return p;
    },
    swing: function( p ) {
        return 0.5 - Math.cos( p*Math.PI ) / 2;
    }
};

jQuery.timers = [];
jQuery.fx = Tween.prototype.init;
jQuery.fx.tick = function() {
    var timer,
        timers = jQuery.timers,
        i = 0;

    fxNow = jQuery.now();

    for ( ; i < timers.length; i++ ) {
        timer = timers[ i ];
        // Checks the timer has not already been removed
        if ( !timer() && timers[ i ] === timer ) {
            timers.splice( i--, 1 );
        }
    }

    if ( !timers.length ) {
        jQuery.fx.stop();
    }
    fxNow = undefined;
};

jQuery.fx.timer = function( timer ) {
    if ( timer() && jQuery.timers.push( timer ) ) {
        jQuery.fx.start();
    }
};

jQuery.fx.interval = 13;

jQuery.fx.start = function() {
    if ( !timerId ) {
        timerId = setInterval( jQuery.fx.tick, jQuery.fx.interval );
    }
};

jQuery.fx.stop = function() {
    clearInterval( timerId );
    timerId = null;
};

jQuery.fx.speeds = {
    slow: 600,
    fast: 200,
    // Default speed
    _default: 400
};

// Back Compat <1.8 extension point
jQuery.fx.step = {};

if ( jQuery.expr && jQuery.expr.filters ) {
    jQuery.expr.filters.animated = function( elem ) {
        return jQuery.grep(jQuery.timers, function( fn ) {
            return elem === fn.elem;
        }).length;
    };
}
jQuery.fn.offset = function( options ) {
    if ( arguments.length ) {
        return options === undefined ?
            this :
            this.each(function( i ) {
                jQuery.offset.setOffset( this, options, i );
            });
    }

    var docElem, win,
        box = { top: 0, left: 0 },
        elem = this[ 0 ],
        doc = elem && elem.ownerDocument;

    if ( !doc ) {
        return;
    }

    docElem = doc.documentElement;

    // Make sure it's not a disconnected DOM node
    if ( !jQuery.contains( docElem, elem ) ) {
        return box;
    }

    // If we don't have gBCR, just use 0,0 rather than error
    // BlackBerry 5, iOS 3 (original iPhone)
    if ( typeof elem.getBoundingClientRect !== core_strundefined ) {
        box = elem.getBoundingClientRect();
    }
    win = getWindow( doc );
    return {
        top: box.top  + ( win.pageYOffset || docElem.scrollTop )  - ( docElem.clientTop  || 0 ),
        left: box.left + ( win.pageXOffset || docElem.scrollLeft ) - ( docElem.clientLeft || 0 )
    };
};

jQuery.offset = {

    setOffset: function( elem, options, i ) {
        var position = jQuery.css( elem, "position" );

        // set position first, in-case top/left are set even on static elem
        if ( position === "static" ) {
            elem.style.position = "relative";
        }

        var curElem = jQuery( elem ),
            curOffset = curElem.offset(),
            curCSSTop = jQuery.css( elem, "top" ),
            curCSSLeft = jQuery.css( elem, "left" ),
            calculatePosition = ( position === "absolute" || position === "fixed" ) && jQuery.inArray("auto", [curCSSTop, curCSSLeft]) > -1,
            props = {}, curPosition = {}, curTop, curLeft;

        // need to be able to calculate position if either top or left is auto and position is either absolute or fixed
        if ( calculatePosition ) {
            curPosition = curElem.position();
            curTop = curPosition.top;
            curLeft = curPosition.left;
        } else {
            curTop = parseFloat( curCSSTop ) || 0;
            curLeft = parseFloat( curCSSLeft ) || 0;
        }

        if ( jQuery.isFunction( options ) ) {
            options = options.call( elem, i, curOffset );
        }

        if ( options.top != null ) {
            props.top = ( options.top - curOffset.top ) + curTop;
        }
        if ( options.left != null ) {
            props.left = ( options.left - curOffset.left ) + curLeft;
        }

        if ( "using" in options ) {
            options.using.call( elem, props );
        } else {
            curElem.css( props );
        }
    }
};


jQuery.fn.extend({

    position: function() {
        if ( !this[ 0 ] ) {
            return;
        }

        var offsetParent, offset,
            parentOffset = { top: 0, left: 0 },
            elem = this[ 0 ];

        // fixed elements are offset from window (parentOffset = {top:0, left: 0}, because it is it's only offset parent
        if ( jQuery.css( elem, "position" ) === "fixed" ) {
            // we assume that getBoundingClientRect is available when computed position is fixed
            offset = elem.getBoundingClientRect();
        } else {
            // Get *real* offsetParent
            offsetParent = this.offsetParent();

            // Get correct offsets
            offset = this.offset();
            if ( !jQuery.nodeName( offsetParent[ 0 ], "html" ) ) {
                parentOffset = offsetParent.offset();
            }

            // Add offsetParent borders
            parentOffset.top  += jQuery.css( offsetParent[ 0 ], "borderTopWidth", true );
            parentOffset.left += jQuery.css( offsetParent[ 0 ], "borderLeftWidth", true );
        }

        // Subtract parent offsets and element margins
        // note: when an element has margin: auto the offsetLeft and marginLeft
        // are the same in Safari causing offset.left to incorrectly be 0
        return {
            top:  offset.top  - parentOffset.top - jQuery.css( elem, "marginTop", true ),
            left: offset.left - parentOffset.left - jQuery.css( elem, "marginLeft", true)
        };
    },

    offsetParent: function() {
        return this.map(function() {
            var offsetParent = this.offsetParent || document.documentElement;
            while ( offsetParent && ( !jQuery.nodeName( offsetParent, "html" ) && jQuery.css( offsetParent, "position") === "static" ) ) {
                offsetParent = offsetParent.offsetParent;
            }
            return offsetParent || document.documentElement;
        });
    }
});


// Create scrollLeft and scrollTop methods
jQuery.each( {scrollLeft: "pageXOffset", scrollTop: "pageYOffset"}, function( method, prop ) {
    var top = /Y/.test( prop );

    jQuery.fn[ method ] = function( val ) {
        return jQuery.access( this, function( elem, method, val ) {
            var win = getWindow( elem );

            if ( val === undefined ) {
                return win ? (prop in win) ? win[ prop ] :
                    win.document.documentElement[ method ] :
                    elem[ method ];
            }

            if ( win ) {
                win.scrollTo(
                    !top ? val : jQuery( win ).scrollLeft(),
                    top ? val : jQuery( win ).scrollTop()
                );

            } else {
                elem[ method ] = val;
            }
        }, method, val, arguments.length, null );
    };
});

function getWindow( elem ) {
    return jQuery.isWindow( elem ) ?
        elem :
        elem.nodeType === 9 ?
            elem.defaultView || elem.parentWindow :
            false;
}
// Create innerHeight, innerWidth, height, width, outerHeight and outerWidth methods
jQuery.each( { Height: "height", Width: "width" }, function( name, type ) {
    jQuery.each( { padding: "inner" + name, content: type, "": "outer" + name }, function( defaultExtra, funcName ) {
        // margin is only for outerHeight, outerWidth
        jQuery.fn[ funcName ] = function( margin, value ) {
            var chainable = arguments.length && ( defaultExtra || typeof margin !== "boolean" ),
                extra = defaultExtra || ( margin === true || value === true ? "margin" : "border" );

            return jQuery.access( this, function( elem, type, value ) {
                var doc;

                if ( jQuery.isWindow( elem ) ) {
                    // As of 5/8/2012 this will yield incorrect results for Mobile Safari, but there
                    // isn't a whole lot we can do. See pull request at this URL for discussion:
                    // https://github.com/jquery/jquery/pull/764
                    return elem.document.documentElement[ "client" + name ];
                }

                // Get document width or height
                if ( elem.nodeType === 9 ) {
                    doc = elem.documentElement;

                    // Either scroll[Width/Height] or offset[Width/Height] or client[Width/Height], whichever is greatest
                    // unfortunately, this causes bug #3838 in IE6/8 only, but there is currently no good, small way to fix it.
                    return Math.max(
                        elem.body[ "scroll" + name ], doc[ "scroll" + name ],
                        elem.body[ "offset" + name ], doc[ "offset" + name ],
                        doc[ "client" + name ]
                    );
                }

                return value === undefined ?
                    // Get width or height on the element, requesting but not forcing parseFloat
                    jQuery.css( elem, type, extra ) :

                    // Set width or height on the element
                    jQuery.style( elem, type, value, extra );
            }, type, chainable ? margin : undefined, chainable, null );
        };
    });
});
// Limit scope pollution from any deprecated API
// (function() {

// })();
// Expose jQuery to the global object
window.jQuery = window.$ = jQuery;

// Expose jQuery as an AMD module, but only for AMD loaders that
// understand the issues with loading multiple versions of jQuery
// in a page that all might call define(). The loader will indicate
// they have special allowances for multiple jQuery versions by
// specifying define.amd.jQuery = true. Register as a named module,
// since jQuery can be concatenated with other files that may use define,
// but not use a proper concatenation script that understands anonymous
// AMD modules. A named AMD is safest and most robust way to register.
// Lowercase jquery is used because AMD module names are derived from
// file names, and jQuery is normally delivered in a lowercase file name.
// Do this after creating the global so that if an AMD module wants to call
// noConflict to hide this version of jQuery, it will work.
if ( typeof define === "function" && define.amd && define.amd.jQuery ) {
    define( "jquery", [], function () { return jQuery; } );
}

})( window );
define('nunjucks.compat', ['nunjucks'], function(nunjucks) {
    console.log('Loading nunjucks compat...')

    var runtime = nunjucks.require('runtime');
    var lib = nunjucks.require('lib');

    var orig_contextOrFrameLookup = runtime.contextOrFrameLookup;
    runtime.contextOrFrameLookup = function(context, frame, key) {
        var val = orig_contextOrFrameLookup.apply(this, arguments);
        if (val === undefined) {
            switch (key) {
                case 'True':
                    return true;
                case 'False':
                    return false;
                case 'None':
                    return null;
            }
        }

        return val;
    };

    var orig_memberLookup = runtime.memberLookup;
    runtime.memberLookup = function(obj, val, autoescape) {
        obj = obj || {};

        // If the object is an object, return any of the methods that Python would
        // otherwise provide.
        if (lib.isArray(obj)) {
            // Handy list methods.
            switch (val) {
                case 'pop':
                    return function(index) {
                        if (index === undefined) {
                            return obj.pop();
                        }
                        if (index >= obj.length || index < 0) {
                            throw new Error('KeyError');
                        }
                        return obj.splice(index, 1);
                    };
                case 'remove':
                    return function(element) {
                        for (var i = 0; i < obj.length; i++) {
                            if (obj[i] == element) {
                                return obj.splice(i, 1);
                            }
                        }
                        throw new Error('ValueError');
                    };
                case 'count':
                    return function(element) {
                        var count = 0;
                        for (var i = 0; i < obj.length; i++) {
                            if (obj[i] == element) {
                                count++;
                            }
                        }
                        return count;
                    };
                case 'index':
                    return function(element) {
                        var i;
                        if ((i = obj.indexOf(element)) == -1) {
                            throw new Error('ValueError');
                        }
                        return i;
                    };
                case 'find':
                    return function(element) {
                        return obj.indexOf(element);
                    };
                case 'insert':
                    return function(index, elem) {
                        return obj.splice(index, 0, elem);
                    };
            }
        }

        if (lib.isObject(obj)) {
            switch (val) {
                case 'items':
                case 'iteritems':
                    return function() {
                        var ret = [];
                        for(var k in obj) {
                            ret.push([k, obj[k]]);
                        }
                        return ret;
                    };

                case 'values':
                case 'itervalues':
                    return function() {
                        var ret = [];
                        for(var k in obj) {
                            ret.push(obj[k]);
                        }
                        return ret;
                    };

                case 'keys':
                case 'iterkeys':
                    return function() {
                        var ret = [];
                        for(var k in obj) {
                            ret.push(k);
                        }
                        return ret;
                    };

                case 'get':
                    return function(key, def) {
                        var output = obj[key];
                        if (output === undefined) {
                            output = def;
                        }
                        return output;
                    };

                case 'has_key':
                    return function(key) {
                        return key in obj;
                    };

                case 'pop':
                    return function(key, def) {
                        var output = obj[key];
                        if (output === undefined && def !== undefined) {
                            output = def;
                        } else if (output === undefined) {
                            throw new Error('KeyError');
                        } else {
                            delete obj[key];
                        }
                        return output;
                    };

                case 'popitem':
                    return function() {
                        for (var k in obj) {
                            // Return the first object pair.
                            var val = obj[k];
                            delete obj[k];
                            return [k, val];
                        }
                        throw new Error('KeyError');
                    };

                case 'setdefault':
                    return function(key, def) {
                        if (key in obj) {
                            return obj[key];
                        }
                        if (def === undefined) {
                            def = null;
                        }
                        return obj[key] = def;
                    };

                case 'update':
                    return function(kwargs) {
                        for (var k in kwargs) {
                            obj[k] = kwargs[k];
                        }
                        return null;  // Always returns None
                    };
            }
        }

        return orig_memberLookup.apply(this, arguments);
    };

});

(function() {
var modules = {};
(function() {

// A simple class system, more documentation to come

function extend(cls, name, props) {
    var prototype = Object.create(cls.prototype);
    var fnTest = /xyz/.test(function(){ xyz; }) ? /\bparent\b/ : /.*/;
    props = props || {};

    for(var k in props) {
        var src = props[k];
        var parent = prototype[k];

        if(typeof parent == "function" &&
           typeof src == "function" &&
           fnTest.test(src)) {
            prototype[k] = (function (src, parent) {
                return function() {
                    // Save the current parent method
                    var tmp = this.parent;

                    // Set parent to the previous method, call, and restore
                    this.parent = parent;
                    var res = src.apply(this, arguments);
                    this.parent = tmp;

                    return res;
                };
            })(src, parent);
        }
        else {
            prototype[k] = src;
        }
    }

    prototype.typename = name;

    var new_cls = function() {
        if(prototype.init) {
            prototype.init.apply(this, arguments);
        }
    };

    new_cls.prototype = prototype;
    new_cls.prototype.constructor = new_cls;

    new_cls.extend = function(name, props) {
        if(typeof name == "object") {
            props = name;
            name = "anonymous";
        }
        return extend(new_cls, name, props);
    };

    return new_cls;
}

modules['object'] = extend(Object, "Object", {});
})();
(function() {
var ArrayProto = Array.prototype;
var ObjProto = Object.prototype;

var escapeMap = {
    '&': '&amp;',
    '"': '&quot;',
    "'": '&#39;',
    "<": '&lt;',
    ">": '&gt;'
};

var lookupEscape = function(ch) {
    return escapeMap[ch];
};

var exports = modules['lib'] = {};

exports.withPrettyErrors = function(path, withInternals, func) {
    try {
        return func();
    } catch (e) {
        if (!e.Update) {
            // not one of ours, cast it
            e = new exports.TemplateError(e);
        }
        e.Update(path);

        // Unless they marked the dev flag, show them a trace from here
        if (!withInternals) {
            var old = e;
            e = new Error(old.message);
            e.name = old.name;
        }

        throw e;
    }
}

exports.TemplateError = function(message, lineno, colno) {
    var err = this;

    if (message instanceof Error) { // for casting regular js errors
        err = message;
        message = message.name + ": " + message.message;
    } else {
        Error.captureStackTrace(err);
    }

    err.name = "Template render error";
    err.message = message;
    err.lineno = lineno;
    err.colno = colno;
    err.firstUpdate = true;

    err.Update = function(path) {
        var message = "(" + (path || "unknown path") + ")";

        // only show lineno + colno next to path of template
        // where error occurred
        if (this.firstUpdate) {
            if(this.lineno && this.colno) {
                message += ' [Line ' + this.lineno + ', Column ' + this.colno + ']';
            }
            else if(this.lineno) {
                message += ' [Line ' + this.lineno + ']';
            }
        }

        message += '\n ';
        if (this.firstUpdate) {
            message += ' ';
        }

        this.message = message + (this.message || '');
        this.firstUpdate = false;
        return this;
    };

    return err;
};

exports.TemplateError.prototype = Error.prototype;

exports.escape = function(val) {
    return val.replace(/[&"'<>]/g, lookupEscape);
};

exports.isFunction = function(obj) {
    return ObjProto.toString.call(obj) == '[object Function]';
};

exports.isArray = Array.isArray || function(obj) {
    return ObjProto.toString.call(obj) == '[object Array]';
};

exports.isString = function(obj) {
    return ObjProto.toString.call(obj) == '[object String]';
};

exports.isObject = function(obj) {
    return obj === Object(obj);
};

exports.groupBy = function(obj, val) {
    var result = {};
    var iterator = exports.isFunction(val) ? val : function(obj) { return obj[val]; };
    for(var i=0; i<obj.length; i++) {
        var value = obj[i];
        var key = iterator(value, i);
        (result[key] || (result[key] = [])).push(value);
    }
    return result;
};

exports.toArray = function(obj) {
    return Array.prototype.slice.call(obj);
};

exports.without = function(array) {
    var result = [];
    if (!array) {
        return result;
    }
    var index = -1,
    length = array.length,
    contains = exports.toArray(arguments).slice(1);

    while(++index < length) {
        if(contains.indexOf(array[index]) === -1) {
            result.push(array[index]);
        }
    }
    return result;
};

exports.extend = function(obj, obj2) {
    for(var k in obj2) {
        obj[k] = obj2[k];
    }
    return obj;
};

exports.repeat = function(char_, n) {
    var str = '';
    for(var i=0; i<n; i++) {
        str += char_;
    }
    return str;
};

exports.each = function(obj, func, context) {
    if(obj == null) {
        return;
    }

    if(ArrayProto.each && obj.each == ArrayProto.each) {
        obj.forEach(func, context);
    }
    else if(obj.length === +obj.length) {
        for(var i=0, l=obj.length; i<l; i++) {
            func.call(context, obj[i], i, obj);
        }
    }
};

exports.map = function(obj, func) {
    var results = [];
    if(obj == null) {
        return results;
    }

    if(ArrayProto.map && obj.map === ArrayProto.map) {
        return obj.map(func);
    }

    for(var i=0; i<obj.length; i++) {
        results[results.length] = func(obj[i], i);
    }

    if(obj.length === +obj.length) {
        results.length = obj.length;
    }

    return results;
};
})();
(function() {

var lib = modules["lib"];
var Object = modules["object"];

// Frames keep track of scoping both at compile-time and run-time so
// we know how to access variables. Block tags can introduce special
// variables, for example.
var Frame = Object.extend({
    init: function(parent) {
        this.variables = {};
        this.parent = parent;
    },

    set: function(name, val) {
        // Allow variables with dots by automatically creating the
        // nested structure
        var parts = name.split('.');
        var obj = this.variables;

        for(var i=0; i<parts.length - 1; i++) {
            var id = parts[i];

            if(!obj[id]) {
                obj[id] = {};
            }
            obj = obj[id];
        }

        obj[parts[parts.length - 1]] = val;
    },

    lookup: function(name) {
        var p = this.parent;
        var val = this.variables[name];
        if(val !== undefined && val !== null) {
            return val;
        }
        return p && p.lookup(name);
    },

    push: function() {
        return new Frame(this);
    },

    pop: function() {
        return this.parent;
    }
});

function makeMacro(argNames, kwargNames, func) {
    return function() {
        var argCount = numArgs(arguments);
        var args;
        var kwargs = getKeywordArgs(arguments);

        if(argCount > argNames.length) {
            args = Array.prototype.slice.call(arguments, 0, argNames.length);

            // Positional arguments that should be passed in as
            // keyword arguments (essentially default values)
            var vals = Array.prototype.slice.call(arguments, args.length, argCount);
            for(var i=0; i<vals.length; i++) {
                if(i < kwargNames.length) {
                    kwargs[kwargNames[i]] = vals[i];
                }
            }

            args.push(kwargs);
        }
        else if(argCount < argNames.length) {
            args = Array.prototype.slice.call(arguments, 0, argCount);

            for(var i=argCount; i<argNames.length; i++) {
                var arg = argNames[i];

                // Keyword arguments that should be passed as
                // positional arguments, i.e. the caller explicitly
                // used the name of a positional arg
                args.push(kwargs[arg]);
                delete kwargs[arg];
            }

            args.push(kwargs);
        }
        else {
            args = arguments;
        }

        return func.apply(this, args);
    };
}

function makeKeywordArgs(obj) {
    obj.__keywords = true;
    return obj;
}

function getKeywordArgs(args) {
    if(args.length && args[args.length - 1].__keywords) {
        return args[args.length - 1];
    }
    return {};
}

function numArgs(args) {
    if(args.length === 0) {
        return 0;
    }
    else if(args[args.length - 1].__keywords) {
        return args.length - 1;
    }
    else {
        return args.length;
    }
}

// A SafeString object indicates that the string should not be
// autoescaped. This happens magically because autoescaping only
// occurs on primitive string objects.
function SafeString(val) {
    if(typeof val != 'string') {
        return val;
    }

    this.toString = function() {
        return val;
    };

    this.length = val.length;

    var methods = [
        'charAt', 'charCodeAt', 'concat', 'contains',
        'endsWith', 'fromCharCode', 'indexOf', 'lastIndexOf',
        'length', 'localeCompare', 'match', 'quote', 'replace',
        'search', 'slice', 'split', 'startsWith', 'substr',
        'substring', 'toLocaleLowerCase', 'toLocaleUpperCase',
        'toLowerCase', 'toUpperCase', 'trim', 'trimLeft', 'trimRight'
    ];

    for(var i=0; i<methods.length; i++) {
        this[methods[i]] = proxyStr(val[methods[i]]);
    }
}

function copySafeness(dest, target) {
    if(dest instanceof SafeString) {
        return new SafeString(target);
    }
    return target.toString();
}

function proxyStr(func) {
    return function() {
        var ret = func.apply(this, arguments);

        if(typeof ret == 'string') {
            return new SafeString(ret);
        }
        return ret;
    };
}

function suppressValue(val, autoescape) {
    val = (val !== undefined && val !== null) ? val : "";

    if(autoescape && typeof val === "string") {
        val = lib.escape(val);
    }

    return val;
}

function memberLookup(obj, val, autoescape) {
    obj = obj || {};

    if(typeof obj[val] === 'function') {
        return function() {
            return obj[val].apply(obj, arguments);
        };
    }

    return suppressValue(obj[val]);
}

function callWrap(obj, name, args) {
    if(!obj) {
        throw new Error('Unable to call `' + name + '`, which is undefined or falsey');
    }
    else if(typeof obj !== 'function') {
        throw new Error('Unable to call `' + name + '`, which is not a function');
    }

    return obj.apply(this, args);
}

function contextOrFrameLookup(context, frame, name) {
    var val = context.lookup(name);
    return (val !== undefined && val !== null) ?
        val :
        frame.lookup(name);
}

function handleError(error, lineno, colno) {
    if(error.lineno) {
        throw error;
    }
    else {
        throw new lib.TemplateError(error, lineno, colno);
    }
}

modules['runtime'] = {
    Frame: Frame,
    makeMacro: makeMacro,
    makeKeywordArgs: makeKeywordArgs,
    numArgs: numArgs,
    suppressValue: suppressValue,
    memberLookup: memberLookup,
    contextOrFrameLookup: contextOrFrameLookup,
    callWrap: callWrap,
    handleError: handleError,
    isArray: lib.isArray,
    SafeString: SafeString,
    copySafeness: copySafeness
};
})();
(function() {

var lib = modules["lib"];
var r = modules["runtime"];

var filters = {
    abs: function(n) {
        return Math.abs(n);
    },

    batch: function(arr, linecount, fill_with) {
        var res = [];
        var tmp = [];

        for(var i=0; i<arr.length; i++) {
            if(i % linecount === 0 && tmp.length) {
                res.push(tmp);
                tmp = [];
            }

            tmp.push(arr[i]);
        }

        if(tmp.length) {
            if(fill_with) {
                for(var i=tmp.length; i<linecount; i++) {
                    tmp.push(fill_with);
                }
            }

            res.push(tmp);
        }

        return res;
    },

    capitalize: function(str) {
        var ret = str.toLowerCase();
        return r.copySafeness(str, ret[0].toUpperCase() + ret.slice(1));
    },

    center: function(str, width) {
        width = width || 80;

        if(str.length >= width) {
            return str;
        }

        var spaces = width - str.length;
        var pre = lib.repeat(" ", spaces/2 - spaces % 2);
        var post = lib.repeat(" ", spaces/2);
        return r.copySafeness(str, pre + str + post);
    },

    'default': function(val, def) {
        return val ? val : def;
    },

    dictsort: function(val, case_sensitive, by) {
        if (!lib.isObject(val)) {
            throw new lib.TemplateError("dictsort filter: val must be an object");
        }

        var array = [];
        for (var k in val) {
            // deliberately include properties from the object's prototype
            array.push([k,val[k]]);
        }

        var si;
        if (by === undefined || by === "key") {
            si = 0;
        } else if (by === "value") {
            si = 1;
        } else {
            throw new lib.TemplateError(
                "dictsort filter: You can only sort by either key or value");
        }

        array.sort(function(t1, t2) {
            var a = t1[si];
            var b = t2[si];

            if (!case_sensitive) {
                if (lib.isString(a)) {
                    a = a.toUpperCase();
                }
                if (lib.isString(b)) {
                    b = b.toUpperCase();
                }
            }

            return a > b ? 1 : (a == b ? 0 : -1);
        });

        return array;
    },

    escape: function(str) {
        if(typeof str == 'string' ||
           str instanceof r.SafeString) {
            return lib.escape(str);
        }
        return str;
    },

    safe: function(str) {
        return new r.SafeString(str);
    },

    first: function(arr) {
        return arr[0];
    },

    groupby: function(arr, attr) {
        return lib.groupBy(arr, attr);
    },

    indent: function(str, width, indentfirst) {
        width = width || 4;
        var res = '';
        var lines = str.split('\n');
        var sp = lib.repeat(' ', width);

        for(var i=0; i<lines.length; i++) {
            if(i == 0 && !indentfirst) {
                res += lines[i] + '\n';
            }
            else {
                res += sp + lines[i] + '\n';
            }
        }

        return r.copySafeness(str, res);
    },

    join: function(arr, del, attr) {
        del = del || '';

        if(attr) {
            arr = lib.map(arr, function(v) {
                return v[attr];
            });
        }

        return arr.join(del);
    },

    last: function(arr) {
        return arr[arr.length-1];
    },

    length: function(arr) {
        return arr.length;
    },

    list: function(val) {
        if(lib.isString(val)) {
            return val.split('');
        }
        else if(lib.isObject(val)) {
            var keys = [];

            if(Object.keys) {
                keys = Object.keys(val);
            }
            else {
                for(var k in val) {
                    keys.push(k);
                }
            }

            return lib.map(keys, function(k) {
                return { key: k,
                         value: val[k] };
            });
        }
        else {
            throw new lib.TemplateError("list filter: type not iterable");
        }
    },

    lower: function(str) {
        return str.toLowerCase();
    },

    random: function(arr) {
        var i = Math.floor(Math.random() * arr.length);
        if(i == arr.length) {
            i--;
        }

        return arr[i];
    },

    replace: function(str, old, new_, maxCount) {
        var res = str;
        var last = res;
        var count = 1;
        res = res.replace(old, new_);

        while(last != res) {
            if(count >= maxCount) {
                break;
            }

            last = res;
            res = res.replace(old, new_);
            count++;
        }

        return r.copySafeness(str, res);
    },

    reverse: function(val) {
        var arr;
        if(lib.isString(val)) {
            arr = filters.list(val);
        }
        else {
            // Copy it
            arr = lib.map(val, function(v) { return v; });
        }

        arr.reverse();

        if(lib.isString(val)) {
            return r.copySafeness(val, arr.join(''));
        }
        return arr;
    },

    round: function(val, precision, method) {
        precision = precision || 0;
        var factor = Math.pow(10, precision);
        var rounder;

        if(method == 'ceil') {
            rounder = Math.ceil;
        }
        else if(method == 'floor') {
            rounder = Math.floor;
        }
        else {
            rounder = Math.round;
        }

        return rounder(val * factor) / factor;
    },

    slice: function(arr, slices, fillWith) {
        var sliceLength = Math.floor(arr.length / slices);
        var extra = arr.length % slices;
        var offset = 0;
        var res = [];

        for(var i=0; i<slices; i++) {
            var start = offset + i * sliceLength;
            if(i < extra) {
                offset++;
            }
            var end = offset + (i + 1) * sliceLength;

            var slice = arr.slice(start, end);
            if(fillWith && i >= extra) {
                slice.push(fillWith);
            }
            res.push(slice);
        }

        return res;
    },

    sort: function(arr, reverse, caseSens, attr) {
        // Copy it
        arr = lib.map(arr, function(v) { return v; });

        arr.sort(function(a, b) {
            var x, y;

            if(attr) {
                x = a[attr];
                y = b[attr];
            }
            else {
                x = a;
                y = b;
            }

            if(!caseSens && lib.isString(x) && lib.isString(y)) {
                x = x.toLowerCase();
                y = y.toLowerCase();
            }

            if(x < y) {
                return reverse ? 1 : -1;
            }
            else if(x > y) {
                return reverse ? -1: 1;
            }
            else {
                return 0;
            }
        });

        return arr;
    },

    string: function(obj) {
        return r.copySafeness(obj, obj);
    },

    title: function(str) {
        var words = str.split(' ');
        for(var i = 0; i < words.length; i++) {
            words[i] = filters.capitalize(words[i]);
        }
        return r.copySafeness(str, words.join(' '));
    },

    trim: function(str) {
        return r.copySafeness(str, str.replace(/^\s*|\s*$/g, ''));
    },

    truncate: function(input, length, killwords, end) {
        var orig = input;
        length = length || 255;

        if (input.length <= length)
            return input;

        if (killwords) {
            input = input.substring(0, length);
        } else {
            input = input.substring(0, input.lastIndexOf(' ', length));
        }

        input += (end !== undefined && end !== null) ? end : '...';
        return r.copySafeness(orig, input);
    },

    upper: function(str) {
        return str.toUpperCase();
    },

    wordcount: function(str) {
        return str.match(/\w+/g).length;
    },

    'float': function(val, def) {
        var res = parseFloat(val);
        return isNaN(res) ? def : res;
    },

    'int': function(val, def) {
        var res = parseInt(val, 10);
        return isNaN(res) ? def : res;
    }
};

// Aliases
filters.d = filters['default'];
filters.e = filters.escape;

modules['filters'] = filters;
})();
(function() {
var lib = modules["lib"];
var Object = modules["object"];
var lexer = modules["lexer"];
var compiler = modules["compiler"];
var builtin_filters = modules["filters"];
var builtin_loaders = modules["loaders"];
var runtime = modules["runtime"];
var Frame = runtime.Frame;

var Environment = Object.extend({
    init: function(loaders, opts) {
        // The dev flag determines the trace that'll be shown on errors.
        // If set to true, returns the full trace from the error point,
        // otherwise will return trace starting from Template.render
        // (the full trace from within nunjucks may confuse developers using
        //  the library)
        // defaults to false
        opts = opts || {};
        this.dev = !!opts.dev;

        // The autoescape flag sets global autoescaping. If true,
        // every string variable will be escaped by default.
        // If false, strings can be manually escaped using the `escape` filter.
        // defaults to false
        this.autoesc = !!opts.autoescape;

        if(!loaders) {
            // The filesystem loader is only available client-side
            if(builtin_loaders.FileSystemLoader) {
                this.loaders = [new builtin_loaders.FileSystemLoader()];
            }
            else {
                this.loaders = [new builtin_loaders.HttpLoader('/views')];
            }
        }
        else {
            this.loaders = lib.isArray(loaders) ? loaders : [loaders];
        }

        if(opts.tags) {
            lexer.setTags(opts.tags);
        }

        this.filters = builtin_filters;
        this.cache = {};
        this.extensions = {};
        this.extensionsList = [];
    },

    addExtension: function(name, extension) {
        extension._name = name;
        this.extensions[name] = extension;
        this.extensionsList.push(extension);
    },

    getExtension: function(name) {
        return this.extensions[name];
    },

    addFilter: function(name, func) {
        this.filters[name] = func;
    },

    getFilter: function(name) {
        if(!this.filters[name]) {
            throw new Error('filter not found: ' + name);
        }
        return this.filters[name];
    },

    getTemplate: function(name, eagerCompile) {
        if (name && name.raw) {
            // this fixes autoescape for templates referenced in symbols
            name = name.raw;
        }
        var info = null;
        var tmpl = this.cache[name];
        var upToDate;

        if(typeof name !== 'string') {
            throw new Error('template names must be a string: ' + name);
        }

        if(!tmpl || !tmpl.isUpToDate()) {
            for(var i=0; i<this.loaders.length; i++) {
                if((info = this.loaders[i].getSource(name))) {
                    break;
                }
            }

            if(!info) {
                throw new Error('template not found: ' + name);
            }

            this.cache[name] = new Template(info.src,
                                            this,
                                            info.path,
                                            info.upToDate,
                                            eagerCompile);
        }

        return this.cache[name];
    },

    registerPrecompiled: function(templates) {
        for(var name in templates) {
            this.cache[name] = new Template({ type: 'code',
                                              obj: templates[name] },
                                            this,
                                            name,
                                            function() { return true; },
                                            true);
        }
    },

    express: function(app) {
        var env = this;

        if(app.render) {
            // Express >2.5.11
            app.render = function(name, ctx, k) {
                var context = {};

                if(lib.isFunction(ctx)) {
                    k = ctx;
                    ctx = {};
                }

                context = lib.extend(context, this.locals);

                if(ctx._locals) {
                    context = lib.extend(context, ctx._locals);
                }

                context = lib.extend(context, ctx);

                var res = env.render(name, context);
                k(null, res);
            };
        }
        else {
            // Express <2.5.11
            var http = modules["http"];
            var res = http.ServerResponse.prototype;

            res._render = function(name, ctx, k) {
                var app = this.app;
                var context = {};

                if(this._locals) {
                    context = lib.extend(context, this._locals);
                }

                if(ctx) {
                    context = lib.extend(context, ctx);

                    if(ctx.locals) {
                        context = lib.extend(context, ctx.locals);
                    }
                }

                context = lib.extend(context, app._locals);
                var str = env.render(name, context);

                if(k) {
                    k(null, str);
                }
                else {
                    this.send(str);
                }
            };
        }
    },

    render: function(name, ctx) {
        return this.getTemplate(name).render(ctx);
    }
});

var Context = Object.extend({
    init: function(ctx, blocks) {
        this.ctx = ctx;
        this.blocks = {};
        this.exported = [];

        for(var name in blocks) {
            this.addBlock(name, blocks[name]);
        }
    },

    lookup: function(name) {
        return this.ctx[name];
    },

    setVariable: function(name, val) {
        this.ctx[name] = val;
    },

    getVariables: function() {
        return this.ctx;
    },

    addBlock: function(name, block) {
        this.blocks[name] = this.blocks[name] || [];
        this.blocks[name].push(block);
    },

    getBlock: function(name) {
        if(!this.blocks[name]) {
            throw new Error('unknown block "' + name + '"');
        }

        return this.blocks[name][0];
    },

    getSuper: function(env, name, block, frame, runtime) {
        var idx = (this.blocks[name] || []).indexOf(block);
        var blk = this.blocks[name][idx + 1];
        var context = this;

        return function() {
            if(idx == -1 || !blk) {
                throw new Error('no super block available for "' + name + '"');
            }

            return blk(env, context, frame, runtime);
        };
    },

    addExport: function(name) {
        this.exported.push(name);
    },

    getExported: function() {
        var exported = {};
        for(var i=0; i<this.exported.length; i++) {
            var name = this.exported[i];
            exported[name] = this.ctx[name];
        }
        return exported;
    }
});

var Template = Object.extend({
    init: function (src, env, path, upToDate, eagerCompile) {
        this.env = env || new Environment();

        if(lib.isObject(src)) {
            switch(src.type) {
            case 'code': this.tmplProps = src.obj; break;
            case 'string': this.tmplStr = src.obj; break;
            }
        }
        else if(lib.isString(src)) {
            this.tmplStr = src;
        }
        else {
            throw new Error("src must be a string or an object describing " +
                            "the source");
        }

        this.path = path;
        this.upToDate = upToDate || function() { return false; };

        if(eagerCompile) {
            var _this = this;
            lib.withPrettyErrors(this.path,
                                 this.env.dev,
                                 function() { _this._compile(); });
        }
        else {
            this.compiled = false;
        }
    },

    render: function(ctx, frame) {
        var self = this;

        var render = function() {
            if(!self.compiled) {
                self._compile();
            }

            var context = new Context(ctx || {}, self.blocks);

            return self.rootRenderFunc(self.env,
                context,
                frame || new Frame(),
                runtime);
        };

        return lib.withPrettyErrors(this.path, this.env.dev, render);
    },

    isUpToDate: function() {
        return this.upToDate();
    },

    getExported: function() {
        if(!this.compiled) {
            this._compile();
        }

        // Run the rootRenderFunc to populate the context with exported vars
        var context = new Context({}, this.blocks);
        this.rootRenderFunc(this.env,
                            context,
                            new Frame(),
                            runtime);
        return context.getExported();
    },

    _compile: function() {
        var props;

        if(this.tmplProps) {
            props = this.tmplProps;
        }
        else {
            var source = compiler.compile(this.tmplStr, this.env.extensionsList, this.path);
            var func = new Function(source);
            props = func();
        }

        this.blocks = this._getBlocks(props);
        this.rootRenderFunc = props.root;
        this.compiled = true;
    },

    _getBlocks: function(props) {
        var blocks = {};

        for(var k in props) {
            if(k.slice(0, 2) == 'b_') {
                blocks[k.slice(2)] = props[k];
            }
        }

        return blocks;
    }
});

// var fs = modules["fs"];
// var src = fs.readFileSync('test.html', 'utf-8');
// var src = '{{ foo|safe|bar }}';
// var env = new Environment(null, { autoescape: true, dev: true });

// env.addFilter('bar', function(x) {
//     return runtime.copySafeness(x, x.substring(3, 1) + x.substring(0, 2));
// });

// //env.addExtension('testExtension', new testExtension());
// console.log(compiler.compile(src));

// var tmpl = new Template(src, env);
// console.log("OUTPUT ---");
// console.log(tmpl.render({ foo: '<>&' }));

modules['environment'] = {
    Environment: Environment,
    Template: Template
};
})();
var nunjucks;

var env = modules["environment"];
var compiler = modules["compiler"];
var parser = modules["parser"];
var lexer = modules["lexer"];
var loaders = modules["loaders"];

nunjucks = {};
nunjucks.Environment = env.Environment;
nunjucks.Template = env.Template;

// loaders is not available when using precompiled templates
if(loaders) {
    if(loaders.FileSystemLoader) {
        nunjucks.FileSystemLoader = loaders.FileSystemLoader;
    }
    else {
        nunjucks.HttpLoader = loaders.HttpLoader;
    }
}

nunjucks.compiler = compiler;
nunjucks.parser = parser;
nunjucks.lexer = lexer;

nunjucks.require = function(name) { return modules[name]; };

if(typeof define === 'function' && define.amd) {
    define('nunjucks', function() { return nunjucks; });
}
else {
    window.nunjucks = nunjucks;
}

})();

// Underscore.js 1.4.4
// ===================

// > http://underscorejs.org
// > (c) 2009-2013 Jeremy Ashkenas, DocumentCloud Inc.
// > Underscore may be freely distributed under the MIT license.

// Baseline setup
// --------------
(function() {

  // Establish the root object, `window` in the browser, or `global` on the server.
  var root = this;

  // Save the previous value of the `_` variable.
  var previousUnderscore = root._;

  // Establish the object that gets returned to break out of a loop iteration.
  var breaker = {};

  // Save bytes in the minified (but not gzipped) version:
  var ArrayProto = Array.prototype, ObjProto = Object.prototype, FuncProto = Function.prototype;

  // Create quick reference variables for speed access to core prototypes.
  var push             = ArrayProto.push,
      slice            = ArrayProto.slice,
      concat           = ArrayProto.concat,
      toString         = ObjProto.toString,
      hasOwnProperty   = ObjProto.hasOwnProperty;

  // All **ECMAScript 5** native function implementations that we hope to use
  // are declared here.
  var
    nativeForEach      = ArrayProto.forEach,
    nativeMap          = ArrayProto.map,
    nativeReduce       = ArrayProto.reduce,
    nativeReduceRight  = ArrayProto.reduceRight,
    nativeFilter       = ArrayProto.filter,
    nativeEvery        = ArrayProto.every,
    nativeSome         = ArrayProto.some,
    nativeIndexOf      = ArrayProto.indexOf,
    nativeLastIndexOf  = ArrayProto.lastIndexOf,
    nativeIsArray      = Array.isArray,
    nativeKeys         = Object.keys,
    nativeBind         = FuncProto.bind;

  // Create a safe reference to the Underscore object for use below.
  var _ = function(obj) {
    if (obj instanceof _) return obj;
    if (!(this instanceof _)) return new _(obj);
    this._wrapped = obj;
  };

  // Export the Underscore object for **Node.js**, with
  // backwards-compatibility for the old `require()` API. If we're in
  // the browser, add `_` as a global object via a string identifier,
  // for Closure Compiler "advanced" mode.
  if (typeof exports !== 'undefined') {
    if (typeof module !== 'undefined' && module.exports) {
      exports = module.exports = _;
    }
    exports._ = _;
  } else {
    root._ = _;
  }

  // Current version.
  _.VERSION = '1.4.4';

  // Collection Functions
  // --------------------

  // The cornerstone, an `each` implementation, aka `forEach`.
  // Handles objects with the built-in `forEach`, arrays, and raw objects.
  // Delegates to **ECMAScript 5**'s native `forEach` if available.
  var each = _.each = _.forEach = function(obj, iterator, context) {
    if (obj == null) return;
    if (nativeForEach && obj.forEach === nativeForEach) {
      obj.forEach(iterator, context);
    } else if (obj.length === +obj.length) {
      for (var i = 0, l = obj.length; i < l; i++) {
        if (iterator.call(context, obj[i], i, obj) === breaker) return;
      }
    } else {
      for (var key in obj) {
        if (_.has(obj, key)) {
          if (iterator.call(context, obj[key], key, obj) === breaker) return;
        }
      }
    }
  };

  // Return the results of applying the iterator to each element.
  // Delegates to **ECMAScript 5**'s native `map` if available.
  _.map = _.collect = function(obj, iterator, context) {
    var results = [];
    if (obj == null) return results;
    if (nativeMap && obj.map === nativeMap) return obj.map(iterator, context);
    each(obj, function(value, index, list) {
      results[results.length] = iterator.call(context, value, index, list);
    });
    return results;
  };

  var reduceError = 'Reduce of empty array with no initial value';

  // **Reduce** builds up a single result from a list of values, aka `inject`,
  // or `foldl`. Delegates to **ECMAScript 5**'s native `reduce` if available.
  _.reduce = _.foldl = _.inject = function(obj, iterator, memo, context) {
    var initial = arguments.length > 2;
    if (obj == null) obj = [];
    if (nativeReduce && obj.reduce === nativeReduce) {
      if (context) iterator = _.bind(iterator, context);
      return initial ? obj.reduce(iterator, memo) : obj.reduce(iterator);
    }
    each(obj, function(value, index, list) {
      if (!initial) {
        memo = value;
        initial = true;
      } else {
        memo = iterator.call(context, memo, value, index, list);
      }
    });
    if (!initial) throw new TypeError(reduceError);
    return memo;
  };

  // The right-associative version of reduce, also known as `foldr`.
  // Delegates to **ECMAScript 5**'s native `reduceRight` if available.
  _.reduceRight = _.foldr = function(obj, iterator, memo, context) {
    var initial = arguments.length > 2;
    if (obj == null) obj = [];
    if (nativeReduceRight && obj.reduceRight === nativeReduceRight) {
      if (context) iterator = _.bind(iterator, context);
      return initial ? obj.reduceRight(iterator, memo) : obj.reduceRight(iterator);
    }
    var length = obj.length;
    if (length !== +length) {
      var keys = _.keys(obj);
      length = keys.length;
    }
    each(obj, function(value, index, list) {
      index = keys ? keys[--length] : --length;
      if (!initial) {
        memo = obj[index];
        initial = true;
      } else {
        memo = iterator.call(context, memo, obj[index], index, list);
      }
    });
    if (!initial) throw new TypeError(reduceError);
    return memo;
  };

  // Return the first value which passes a truth test. Aliased as `detect`.
  _.find = _.detect = function(obj, iterator, context) {
    var result;
    any(obj, function(value, index, list) {
      if (iterator.call(context, value, index, list)) {
        result = value;
        return true;
      }
    });
    return result;
  };

  // Return all the elements that pass a truth test.
  // Delegates to **ECMAScript 5**'s native `filter` if available.
  // Aliased as `select`.
  _.filter = _.select = function(obj, iterator, context) {
    var results = [];
    if (obj == null) return results;
    if (nativeFilter && obj.filter === nativeFilter) return obj.filter(iterator, context);
    each(obj, function(value, index, list) {
      if (iterator.call(context, value, index, list)) results[results.length] = value;
    });
    return results;
  };

  // Return all the elements for which a truth test fails.
  _.reject = function(obj, iterator, context) {
    return _.filter(obj, function(value, index, list) {
      return !iterator.call(context, value, index, list);
    }, context);
  };

  // Determine whether all of the elements match a truth test.
  // Delegates to **ECMAScript 5**'s native `every` if available.
  // Aliased as `all`.
  _.every = _.all = function(obj, iterator, context) {
    iterator || (iterator = _.identity);
    var result = true;
    if (obj == null) return result;
    if (nativeEvery && obj.every === nativeEvery) return obj.every(iterator, context);
    each(obj, function(value, index, list) {
      if (!(result = result && iterator.call(context, value, index, list))) return breaker;
    });
    return !!result;
  };

  // Determine if at least one element in the object matches a truth test.
  // Delegates to **ECMAScript 5**'s native `some` if available.
  // Aliased as `any`.
  var any = _.some = _.any = function(obj, iterator, context) {
    iterator || (iterator = _.identity);
    var result = false;
    if (obj == null) return result;
    if (nativeSome && obj.some === nativeSome) return obj.some(iterator, context);
    each(obj, function(value, index, list) {
      if (result || (result = iterator.call(context, value, index, list))) return breaker;
    });
    return !!result;
  };

  // Determine if the array or object contains a given value (using `===`).
  // Aliased as `include`.
  _.contains = _.include = function(obj, target) {
    if (obj == null) return false;
    if (nativeIndexOf && obj.indexOf === nativeIndexOf) return obj.indexOf(target) != -1;
    return any(obj, function(value) {
      return value === target;
    });
  };

  // Invoke a method (with arguments) on every item in a collection.
  _.invoke = function(obj, method) {
    var args = slice.call(arguments, 2);
    var isFunc = _.isFunction(method);
    return _.map(obj, function(value) {
      return (isFunc ? method : value[method]).apply(value, args);
    });
  };

  // Convenience version of a common use case of `map`: fetching a property.
  _.pluck = function(obj, key) {
    return _.map(obj, function(value){ return value[key]; });
  };

  // Convenience version of a common use case of `filter`: selecting only objects
  // containing specific `key:value` pairs.
  _.where = function(obj, attrs, first) {
    if (_.isEmpty(attrs)) return first ? null : [];
    return _[first ? 'find' : 'filter'](obj, function(value) {
      for (var key in attrs) {
        if (attrs[key] !== value[key]) return false;
      }
      return true;
    });
  };

  // Convenience version of a common use case of `find`: getting the first object
  // containing specific `key:value` pairs.
  _.findWhere = function(obj, attrs) {
    return _.where(obj, attrs, true);
  };

  // Return the maximum element or (element-based computation).
  // Can't optimize arrays of integers longer than 65,535 elements.
  // See: https://bugs.webkit.org/show_bug.cgi?id=80797
  _.max = function(obj, iterator, context) {
    if (!iterator && _.isArray(obj) && obj[0] === +obj[0] && obj.length < 65535) {
      return Math.max.apply(Math, obj);
    }
    if (!iterator && _.isEmpty(obj)) return -Infinity;
    var result = {computed : -Infinity, value: -Infinity};
    each(obj, function(value, index, list) {
      var computed = iterator ? iterator.call(context, value, index, list) : value;
      computed >= result.computed && (result = {value : value, computed : computed});
    });
    return result.value;
  };

  // Return the minimum element (or element-based computation).
  _.min = function(obj, iterator, context) {
    if (!iterator && _.isArray(obj) && obj[0] === +obj[0] && obj.length < 65535) {
      return Math.min.apply(Math, obj);
    }
    if (!iterator && _.isEmpty(obj)) return Infinity;
    var result = {computed : Infinity, value: Infinity};
    each(obj, function(value, index, list) {
      var computed = iterator ? iterator.call(context, value, index, list) : value;
      computed < result.computed && (result = {value : value, computed : computed});
    });
    return result.value;
  };

  // Shuffle an array.
  _.shuffle = function(obj) {
    var rand;
    var index = 0;
    var shuffled = [];
    each(obj, function(value) {
      rand = _.random(index++);
      shuffled[index - 1] = shuffled[rand];
      shuffled[rand] = value;
    });
    return shuffled;
  };

  // An internal function to generate lookup iterators.
  var lookupIterator = function(value) {
    return _.isFunction(value) ? value : function(obj){ return obj[value]; };
  };

  // Sort the object's values by a criterion produced by an iterator.
  _.sortBy = function(obj, value, context) {
    var iterator = lookupIterator(value);
    return _.pluck(_.map(obj, function(value, index, list) {
      return {
        value : value,
        index : index,
        criteria : iterator.call(context, value, index, list)
      };
    }).sort(function(left, right) {
      var a = left.criteria;
      var b = right.criteria;
      if (a !== b) {
        if (a > b || a === void 0) return 1;
        if (a < b || b === void 0) return -1;
      }
      return left.index < right.index ? -1 : 1;
    }), 'value');
  };

  // An internal function used for aggregate "group by" operations.
  var group = function(obj, value, context, behavior) {
    var result = {};
    var iterator = lookupIterator(value || _.identity);
    each(obj, function(value, index) {
      var key = iterator.call(context, value, index, obj);
      behavior(result, key, value);
    });
    return result;
  };

  // Groups the object's values by a criterion. Pass either a string attribute
  // to group by, or a function that returns the criterion.
  _.groupBy = function(obj, value, context) {
    return group(obj, value, context, function(result, key, value) {
      (_.has(result, key) ? result[key] : (result[key] = [])).push(value);
    });
  };

  // Counts instances of an object that group by a certain criterion. Pass
  // either a string attribute to count by, or a function that returns the
  // criterion.
  _.countBy = function(obj, value, context) {
    return group(obj, value, context, function(result, key) {
      if (!_.has(result, key)) result[key] = 0;
      result[key]++;
    });
  };

  // Use a comparator function to figure out the smallest index at which
  // an object should be inserted so as to maintain order. Uses binary search.
  _.sortedIndex = function(array, obj, iterator, context) {
    iterator = iterator == null ? _.identity : lookupIterator(iterator);
    var value = iterator.call(context, obj);
    var low = 0, high = array.length;
    while (low < high) {
      var mid = (low + high) >>> 1;
      iterator.call(context, array[mid]) < value ? low = mid + 1 : high = mid;
    }
    return low;
  };

  // Safely convert anything iterable into a real, live array.
  _.toArray = function(obj) {
    if (!obj) return [];
    if (_.isArray(obj)) return slice.call(obj);
    if (obj.length === +obj.length) return _.map(obj, _.identity);
    return _.values(obj);
  };

  // Return the number of elements in an object.
  _.size = function(obj) {
    if (obj == null) return 0;
    return (obj.length === +obj.length) ? obj.length : _.keys(obj).length;
  };

  // Array Functions
  // ---------------

  // Get the first element of an array. Passing **n** will return the first N
  // values in the array. Aliased as `head` and `take`. The **guard** check
  // allows it to work with `_.map`.
  _.first = _.head = _.take = function(array, n, guard) {
    if (array == null) return void 0;
    return (n != null) && !guard ? slice.call(array, 0, n) : array[0];
  };

  // Returns everything but the last entry of the array. Especially useful on
  // the arguments object. Passing **n** will return all the values in
  // the array, excluding the last N. The **guard** check allows it to work with
  // `_.map`.
  _.initial = function(array, n, guard) {
    return slice.call(array, 0, array.length - ((n == null) || guard ? 1 : n));
  };

  // Get the last element of an array. Passing **n** will return the last N
  // values in the array. The **guard** check allows it to work with `_.map`.
  _.last = function(array, n, guard) {
    if (array == null) return void 0;
    if ((n != null) && !guard) {
      return slice.call(array, Math.max(array.length - n, 0));
    } else {
      return array[array.length - 1];
    }
  };

  // Returns everything but the first entry of the array. Aliased as `tail` and `drop`.
  // Especially useful on the arguments object. Passing an **n** will return
  // the rest N values in the array. The **guard**
  // check allows it to work with `_.map`.
  _.rest = _.tail = _.drop = function(array, n, guard) {
    return slice.call(array, (n == null) || guard ? 1 : n);
  };

  // Trim out all falsy values from an array.
  _.compact = function(array) {
    return _.filter(array, _.identity);
  };

  // Internal implementation of a recursive `flatten` function.
  var flatten = function(input, shallow, output) {
    each(input, function(value) {
      if (_.isArray(value)) {
        shallow ? push.apply(output, value) : flatten(value, shallow, output);
      } else {
        output.push(value);
      }
    });
    return output;
  };

  // Return a completely flattened version of an array.
  _.flatten = function(array, shallow) {
    return flatten(array, shallow, []);
  };

  // Return a version of the array that does not contain the specified value(s).
  _.without = function(array) {
    return _.difference(array, slice.call(arguments, 1));
  };

  // Produce a duplicate-free version of the array. If the array has already
  // been sorted, you have the option of using a faster algorithm.
  // Aliased as `unique`.
  _.uniq = _.unique = function(array, isSorted, iterator, context) {
    if (_.isFunction(isSorted)) {
      context = iterator;
      iterator = isSorted;
      isSorted = false;
    }
    var initial = iterator ? _.map(array, iterator, context) : array;
    var results = [];
    var seen = [];
    each(initial, function(value, index) {
      if (isSorted ? (!index || seen[seen.length - 1] !== value) : !_.contains(seen, value)) {
        seen.push(value);
        results.push(array[index]);
      }
    });
    return results;
  };

  // Produce an array that contains the union: each distinct element from all of
  // the passed-in arrays.
  _.union = function() {
    return _.uniq(concat.apply(ArrayProto, arguments));
  };

  // Produce an array that contains every item shared between all the
  // passed-in arrays.
  _.intersection = function(array) {
    var rest = slice.call(arguments, 1);
    return _.filter(_.uniq(array), function(item) {
      return _.every(rest, function(other) {
        return _.indexOf(other, item) >= 0;
      });
    });
  };

  // Take the difference between one array and a number of other arrays.
  // Only the elements present in just the first array will remain.
  _.difference = function(array) {
    var rest = concat.apply(ArrayProto, slice.call(arguments, 1));
    return _.filter(array, function(value){ return !_.contains(rest, value); });
  };

  // Zip together multiple lists into a single array -- elements that share
  // an index go together.
  _.zip = function() {
    var args = slice.call(arguments);
    var length = _.max(_.pluck(args, 'length'));
    var results = new Array(length);
    for (var i = 0; i < length; i++) {
      results[i] = _.pluck(args, "" + i);
    }
    return results;
  };

  // Converts lists into objects. Pass either a single array of `[key, value]`
  // pairs, or two parallel arrays of the same length -- one of keys, and one of
  // the corresponding values.
  _.object = function(list, values) {
    if (list == null) return {};
    var result = {};
    for (var i = 0, l = list.length; i < l; i++) {
      if (values) {
        result[list[i]] = values[i];
      } else {
        result[list[i][0]] = list[i][1];
      }
    }
    return result;
  };

  // If the browser doesn't supply us with indexOf (I'm looking at you, **MSIE**),
  // we need this function. Return the position of the first occurrence of an
  // item in an array, or -1 if the item is not included in the array.
  // Delegates to **ECMAScript 5**'s native `indexOf` if available.
  // If the array is large and already in sort order, pass `true`
  // for **isSorted** to use binary search.
  _.indexOf = function(array, item, isSorted) {
    if (array == null) return -1;
    var i = 0, l = array.length;
    if (isSorted) {
      if (typeof isSorted == 'number') {
        i = (isSorted < 0 ? Math.max(0, l + isSorted) : isSorted);
      } else {
        i = _.sortedIndex(array, item);
        return array[i] === item ? i : -1;
      }
    }
    if (nativeIndexOf && array.indexOf === nativeIndexOf) return array.indexOf(item, isSorted);
    for (; i < l; i++) if (array[i] === item) return i;
    return -1;
  };

  // Delegates to **ECMAScript 5**'s native `lastIndexOf` if available.
  _.lastIndexOf = function(array, item, from) {
    if (array == null) return -1;
    var hasIndex = from != null;
    if (nativeLastIndexOf && array.lastIndexOf === nativeLastIndexOf) {
      return hasIndex ? array.lastIndexOf(item, from) : array.lastIndexOf(item);
    }
    var i = (hasIndex ? from : array.length);
    while (i--) if (array[i] === item) return i;
    return -1;
  };

  // Generate an integer Array containing an arithmetic progression. A port of
  // the native Python `range()` function. See
  // [the Python documentation](http://docs.python.org/library/functions.html#range).
  _.range = function(start, stop, step) {
    if (arguments.length <= 1) {
      stop = start || 0;
      start = 0;
    }
    step = arguments[2] || 1;

    var len = Math.max(Math.ceil((stop - start) / step), 0);
    var idx = 0;
    var range = new Array(len);

    while(idx < len) {
      range[idx++] = start;
      start += step;
    }

    return range;
  };

  // Function (ahem) Functions
  // ------------------

  // Create a function bound to a given object (assigning `this`, and arguments,
  // optionally). Delegates to **ECMAScript 5**'s native `Function.bind` if
  // available.
  _.bind = function(func, context) {
    if (func.bind === nativeBind && nativeBind) return nativeBind.apply(func, slice.call(arguments, 1));
    var args = slice.call(arguments, 2);
    return function() {
      return func.apply(context, args.concat(slice.call(arguments)));
    };
  };

  // Partially apply a function by creating a version that has had some of its
  // arguments pre-filled, without changing its dynamic `this` context.
  _.partial = function(func) {
    var args = slice.call(arguments, 1);
    return function() {
      return func.apply(this, args.concat(slice.call(arguments)));
    };
  };

  // Bind all of an object's methods to that object. Useful for ensuring that
  // all callbacks defined on an object belong to it.
  _.bindAll = function(obj) {
    var funcs = slice.call(arguments, 1);
    if (funcs.length === 0) funcs = _.functions(obj);
    each(funcs, function(f) { obj[f] = _.bind(obj[f], obj); });
    return obj;
  };

  // Memoize an expensive function by storing its results.
  _.memoize = function(func, hasher) {
    var memo = {};
    hasher || (hasher = _.identity);
    return function() {
      var key = hasher.apply(this, arguments);
      return _.has(memo, key) ? memo[key] : (memo[key] = func.apply(this, arguments));
    };
  };

  // Delays a function for the given number of milliseconds, and then calls
  // it with the arguments supplied.
  _.delay = function(func, wait) {
    var args = slice.call(arguments, 2);
    return setTimeout(function(){ return func.apply(null, args); }, wait);
  };

  // Defers a function, scheduling it to run after the current call stack has
  // cleared.
  _.defer = function(func) {
    return _.delay.apply(_, [func, 1].concat(slice.call(arguments, 1)));
  };

  // Returns a function, that, when invoked, will only be triggered at most once
  // during a given window of time.
  _.throttle = function(func, wait) {
    var context, args, timeout, result;
    var previous = 0;
    var later = function() {
      previous = new Date;
      timeout = null;
      result = func.apply(context, args);
    };
    return function() {
      var now = new Date;
      var remaining = wait - (now - previous);
      context = this;
      args = arguments;
      if (remaining <= 0) {
        clearTimeout(timeout);
        timeout = null;
        previous = now;
        result = func.apply(context, args);
      } else if (!timeout) {
        timeout = setTimeout(later, remaining);
      }
      return result;
    };
  };

  // Returns a function, that, as long as it continues to be invoked, will not
  // be triggered. The function will be called after it stops being called for
  // N milliseconds. If `immediate` is passed, trigger the function on the
  // leading edge, instead of the trailing.
  _.debounce = function(func, wait, immediate) {
    var timeout, result;
    return function() {
      var context = this, args = arguments;
      var later = function() {
        timeout = null;
        if (!immediate) result = func.apply(context, args);
      };
      var callNow = immediate && !timeout;
      clearTimeout(timeout);
      timeout = setTimeout(later, wait);
      if (callNow) result = func.apply(context, args);
      return result;
    };
  };

  // Returns a function that will be executed at most one time, no matter how
  // often you call it. Useful for lazy initialization.
  _.once = function(func) {
    var ran = false, memo;
    return function() {
      if (ran) return memo;
      ran = true;
      memo = func.apply(this, arguments);
      func = null;
      return memo;
    };
  };

  // Returns the first function passed as an argument to the second,
  // allowing you to adjust arguments, run code before and after, and
  // conditionally execute the original function.
  _.wrap = function(func, wrapper) {
    return function() {
      var args = [func];
      push.apply(args, arguments);
      return wrapper.apply(this, args);
    };
  };

  // Returns a function that is the composition of a list of functions, each
  // consuming the return value of the function that follows.
  _.compose = function() {
    var funcs = arguments;
    return function() {
      var args = arguments;
      for (var i = funcs.length - 1; i >= 0; i--) {
        args = [funcs[i].apply(this, args)];
      }
      return args[0];
    };
  };

  // Returns a function that will only be executed after being called N times.
  _.after = function(times, func) {
    if (times <= 0) return func();
    return function() {
      if (--times < 1) {
        return func.apply(this, arguments);
      }
    };
  };

  // Object Functions
  // ----------------

  // Retrieve the names of an object's properties.
  // Delegates to **ECMAScript 5**'s native `Object.keys`
  _.keys = nativeKeys || function(obj) {
    if (obj !== Object(obj)) throw new TypeError('Invalid object');
    var keys = [];
    for (var key in obj) if (_.has(obj, key)) keys[keys.length] = key;
    return keys;
  };

  // Retrieve the values of an object's properties.
  _.values = function(obj) {
    var values = [];
    for (var key in obj) if (_.has(obj, key)) values.push(obj[key]);
    return values;
  };

  // Convert an object into a list of `[key, value]` pairs.
  _.pairs = function(obj) {
    var pairs = [];
    for (var key in obj) if (_.has(obj, key)) pairs.push([key, obj[key]]);
    return pairs;
  };

  // Invert the keys and values of an object. The values must be serializable.
  _.invert = function(obj) {
    var result = {};
    for (var key in obj) if (_.has(obj, key)) result[obj[key]] = key;
    return result;
  };

  // Return a sorted list of the function names available on the object.
  // Aliased as `methods`
  _.functions = _.methods = function(obj) {
    var names = [];
    for (var key in obj) {
      if (_.isFunction(obj[key])) names.push(key);
    }
    return names.sort();
  };

  // Extend a given object with all the properties in passed-in object(s).
  _.extend = function(obj) {
    each(slice.call(arguments, 1), function(source) {
      if (source) {
        for (var prop in source) {
          obj[prop] = source[prop];
        }
      }
    });
    return obj;
  };

  // Return a copy of the object only containing the whitelisted properties.
  _.pick = function(obj) {
    var copy = {};
    var keys = concat.apply(ArrayProto, slice.call(arguments, 1));
    each(keys, function(key) {
      if (key in obj) copy[key] = obj[key];
    });
    return copy;
  };

   // Return a copy of the object without the blacklisted properties.
  _.omit = function(obj) {
    var copy = {};
    var keys = concat.apply(ArrayProto, slice.call(arguments, 1));
    for (var key in obj) {
      if (!_.contains(keys, key)) copy[key] = obj[key];
    }
    return copy;
  };

  // Fill in a given object with default properties.
  _.defaults = function(obj) {
    each(slice.call(arguments, 1), function(source) {
      if (source) {
        for (var prop in source) {
          if (obj[prop] == null) obj[prop] = source[prop];
        }
      }
    });
    return obj;
  };

  // Create a (shallow-cloned) duplicate of an object.
  _.clone = function(obj) {
    if (!_.isObject(obj)) return obj;
    return _.isArray(obj) ? obj.slice() : _.extend({}, obj);
  };

  // Invokes interceptor with the obj, and then returns obj.
  // The primary purpose of this method is to "tap into" a method chain, in
  // order to perform operations on intermediate results within the chain.
  _.tap = function(obj, interceptor) {
    interceptor(obj);
    return obj;
  };

  // Internal recursive comparison function for `isEqual`.
  var eq = function(a, b, aStack, bStack) {
    // Identical objects are equal. `0 === -0`, but they aren't identical.
    // See the Harmony `egal` proposal: http://wiki.ecmascript.org/doku.php?id=harmony:egal.
    if (a === b) return a !== 0 || 1 / a == 1 / b;
    // A strict comparison is necessary because `null == undefined`.
    if (a == null || b == null) return a === b;
    // Unwrap any wrapped objects.
    if (a instanceof _) a = a._wrapped;
    if (b instanceof _) b = b._wrapped;
    // Compare `[[Class]]` names.
    var className = toString.call(a);
    if (className != toString.call(b)) return false;
    switch (className) {
      // Strings, numbers, dates, and booleans are compared by value.
      case '[object String]':
        // Primitives and their corresponding object wrappers are equivalent; thus, `"5"` is
        // equivalent to `new String("5")`.
        return a == String(b);
      case '[object Number]':
        // `NaN`s are equivalent, but non-reflexive. An `egal` comparison is performed for
        // other numeric values.
        return a != +a ? b != +b : (a == 0 ? 1 / a == 1 / b : a == +b);
      case '[object Date]':
      case '[object Boolean]':
        // Coerce dates and booleans to numeric primitive values. Dates are compared by their
        // millisecond representations. Note that invalid dates with millisecond representations
        // of `NaN` are not equivalent.
        return +a == +b;
      // RegExps are compared by their source patterns and flags.
      case '[object RegExp]':
        return a.source == b.source &&
               a.global == b.global &&
               a.multiline == b.multiline &&
               a.ignoreCase == b.ignoreCase;
    }
    if (typeof a != 'object' || typeof b != 'object') return false;
    // Assume equality for cyclic structures. The algorithm for detecting cyclic
    // structures is adapted from ES 5.1 section 15.12.3, abstract operation `JO`.
    var length = aStack.length;
    while (length--) {
      // Linear search. Performance is inversely proportional to the number of
      // unique nested structures.
      if (aStack[length] == a) return bStack[length] == b;
    }
    // Add the first object to the stack of traversed objects.
    aStack.push(a);
    bStack.push(b);
    var size = 0, result = true;
    // Recursively compare objects and arrays.
    if (className == '[object Array]') {
      // Compare array lengths to determine if a deep comparison is necessary.
      size = a.length;
      result = size == b.length;
      if (result) {
        // Deep compare the contents, ignoring non-numeric properties.
        while (size--) {
          if (!(result = eq(a[size], b[size], aStack, bStack))) break;
        }
      }
    } else {
      // Objects with different constructors are not equivalent, but `Object`s
      // from different frames are.
      var aCtor = a.constructor, bCtor = b.constructor;
      if (aCtor !== bCtor && !(_.isFunction(aCtor) && (aCtor instanceof aCtor) &&
                               _.isFunction(bCtor) && (bCtor instanceof bCtor))) {
        return false;
      }
      // Deep compare objects.
      for (var key in a) {
        if (_.has(a, key)) {
          // Count the expected number of properties.
          size++;
          // Deep compare each member.
          if (!(result = _.has(b, key) && eq(a[key], b[key], aStack, bStack))) break;
        }
      }
      // Ensure that both objects contain the same number of properties.
      if (result) {
        for (key in b) {
          if (_.has(b, key) && !(size--)) break;
        }
        result = !size;
      }
    }
    // Remove the first object from the stack of traversed objects.
    aStack.pop();
    bStack.pop();
    return result;
  };

  // Perform a deep comparison to check if two objects are equal.
  _.isEqual = function(a, b) {
    return eq(a, b, [], []);
  };

  // Is a given array, string, or object empty?
  // An "empty" object has no enumerable own-properties.
  _.isEmpty = function(obj) {
    if (obj == null) return true;
    if (_.isArray(obj) || _.isString(obj)) return obj.length === 0;
    for (var key in obj) if (_.has(obj, key)) return false;
    return true;
  };

  // Is a given value a DOM element?
  _.isElement = function(obj) {
    return !!(obj && obj.nodeType === 1);
  };

  // Is a given value an array?
  // Delegates to ECMA5's native Array.isArray
  _.isArray = nativeIsArray || function(obj) {
    return toString.call(obj) == '[object Array]';
  };

  // Is a given variable an object?
  _.isObject = function(obj) {
    return obj === Object(obj);
  };

  // Add some isType methods: isArguments, isFunction, isString, isNumber, isDate, isRegExp.
  each(['Arguments', 'Function', 'String', 'Number', 'Date', 'RegExp'], function(name) {
    _['is' + name] = function(obj) {
      return toString.call(obj) == '[object ' + name + ']';
    };
  });

  // Define a fallback version of the method in browsers (ahem, IE), where
  // there isn't any inspectable "Arguments" type.
  if (!_.isArguments(arguments)) {
    _.isArguments = function(obj) {
      return !!(obj && _.has(obj, 'callee'));
    };
  }

  // Optimize `isFunction` if appropriate.
  if (typeof (/./) !== 'function') {
    _.isFunction = function(obj) {
      return typeof obj === 'function';
    };
  }

  // Is a given object a finite number?
  _.isFinite = function(obj) {
    return isFinite(obj) && !isNaN(parseFloat(obj));
  };

  // Is the given value `NaN`? (NaN is the only number which does not equal itself).
  _.isNaN = function(obj) {
    return _.isNumber(obj) && obj != +obj;
  };

  // Is a given value a boolean?
  _.isBoolean = function(obj) {
    return obj === true || obj === false || toString.call(obj) == '[object Boolean]';
  };

  // Is a given value equal to null?
  _.isNull = function(obj) {
    return obj === null;
  };

  // Is a given variable undefined?
  _.isUndefined = function(obj) {
    return obj === void 0;
  };

  // Shortcut function for checking if an object has a given property directly
  // on itself (in other words, not on a prototype).
  _.has = function(obj, key) {
    return hasOwnProperty.call(obj, key);
  };

  // Utility Functions
  // -----------------

  // Run Underscore.js in *noConflict* mode, returning the `_` variable to its
  // previous owner. Returns a reference to the Underscore object.
  _.noConflict = function() {
    root._ = previousUnderscore;
    return this;
  };

  // Keep the identity function around for default iterators.
  _.identity = function(value) {
    return value;
  };

  // Run a function **n** times.
  _.times = function(n, iterator, context) {
    var accum = Array(n);
    for (var i = 0; i < n; i++) accum[i] = iterator.call(context, i);
    return accum;
  };

  // Return a random integer between min and max (inclusive).
  _.random = function(min, max) {
    if (max == null) {
      max = min;
      min = 0;
    }
    return min + Math.floor(Math.random() * (max - min + 1));
  };

  // List of HTML entities for escaping.
  var entityMap = {
    escape: {
      '&': '&amp;',
      '<': '&lt;',
      '>': '&gt;',
      '"': '&quot;',
      "'": '&#x27;',
      '/': '&#x2F;'
    }
  };
  entityMap.unescape = _.invert(entityMap.escape);

  // Regexes containing the keys and values listed immediately above.
  var entityRegexes = {
    escape:   new RegExp('[' + _.keys(entityMap.escape).join('') + ']', 'g'),
    unescape: new RegExp('(' + _.keys(entityMap.unescape).join('|') + ')', 'g')
  };

  // Functions for escaping and unescaping strings to/from HTML interpolation.
  _.each(['escape', 'unescape'], function(method) {
    _[method] = function(string) {
      if (string == null) return '';
      return ('' + string).replace(entityRegexes[method], function(match) {
        return entityMap[method][match];
      });
    };
  });

  // If the value of the named property is a function then invoke it;
  // otherwise, return it.
  _.result = function(object, property) {
    if (object == null) return null;
    var value = object[property];
    return _.isFunction(value) ? value.call(object) : value;
  };

  // Add your own custom functions to the Underscore object.
  _.mixin = function(obj) {
    each(_.functions(obj), function(name){
      var func = _[name] = obj[name];
      _.prototype[name] = function() {
        var args = [this._wrapped];
        push.apply(args, arguments);
        return result.call(this, func.apply(_, args));
      };
    });
  };

  // Generate a unique integer id (unique within the entire client session).
  // Useful for temporary DOM ids.
  var idCounter = 0;
  _.uniqueId = function(prefix) {
    var id = ++idCounter + '';
    return prefix ? prefix + id : id;
  };

  // By default, Underscore uses ERB-style template delimiters, change the
  // following template settings to use alternative delimiters.
  _.templateSettings = {
    evaluate    : /<%([\s\S]+?)%>/g,
    interpolate : /<%=([\s\S]+?)%>/g,
    escape      : /<%-([\s\S]+?)%>/g
  };

  // When customizing `templateSettings`, if you don't want to define an
  // interpolation, evaluation or escaping regex, we need one that is
  // guaranteed not to match.
  var noMatch = /(.)^/;

  // Certain characters need to be escaped so that they can be put into a
  // string literal.
  var escapes = {
    "'":      "'",
    '\\':     '\\',
    '\r':     'r',
    '\n':     'n',
    '\t':     't',
    '\u2028': 'u2028',
    '\u2029': 'u2029'
  };

  var escaper = /\\|'|\r|\n|\t|\u2028|\u2029/g;

  // JavaScript micro-templating, similar to John Resig's implementation.
  // Underscore templating handles arbitrary delimiters, preserves whitespace,
  // and correctly escapes quotes within interpolated code.
  _.template = function(text, data, settings) {
    var render;
    settings = _.defaults({}, settings, _.templateSettings);

    // Combine delimiters into one regular expression via alternation.
    var matcher = new RegExp([
      (settings.escape || noMatch).source,
      (settings.interpolate || noMatch).source,
      (settings.evaluate || noMatch).source
    ].join('|') + '|$', 'g');

    // Compile the template source, escaping string literals appropriately.
    var index = 0;
    var source = "__p+='";
    text.replace(matcher, function(match, escape, interpolate, evaluate, offset) {
      source += text.slice(index, offset)
        .replace(escaper, function(match) { return '\\' + escapes[match]; });

      if (escape) {
        source += "'+\n((__t=(" + escape + "))==null?'':_.escape(__t))+\n'";
      }
      if (interpolate) {
        source += "'+\n((__t=(" + interpolate + "))==null?'':__t)+\n'";
      }
      if (evaluate) {
        source += "';\n" + evaluate + "\n__p+='";
      }
      index = offset + match.length;
      return match;
    });
    source += "';\n";

    // If a variable is not specified, place data values in local scope.
    if (!settings.variable) source = 'with(obj||{}){\n' + source + '}\n';

    source = "var __t,__p='',__j=Array.prototype.join," +
      "print=function(){__p+=__j.call(arguments,'');};\n" +
      source + "return __p;\n";

    try {
      render = new Function(settings.variable || 'obj', '_', source);
    } catch (e) {
      e.source = source;
      throw e;
    }

    if (data) return render(data, _);
    var template = function(data) {
      return render.call(this, data, _);
    };

    // Provide the compiled function source as a convenience for precompilation.
    template.source = 'function(' + (settings.variable || 'obj') + '){\n' + source + '}';

    return template;
  };

  // Add a "chain" function, which will delegate to the wrapper.
  _.chain = function(obj) {
    return _(obj).chain();
  };

  // OOP
  // ---------------
  // If Underscore is called as a function, it returns a wrapped object that
  // can be used OO-style. This wrapper holds altered versions of all the
  // underscore functions. Wrapped objects may be chained.

  // Helper function to continue chaining intermediate results.
  var result = function(obj) {
    return this._chain ? _(obj).chain() : obj;
  };

  // Add all of the Underscore functions to the wrapper object.
  _.mixin(_);

  // Add all mutator Array functions to the wrapper.
  each(['pop', 'push', 'reverse', 'shift', 'sort', 'splice', 'unshift'], function(name) {
    var method = ArrayProto[name];
    _.prototype[name] = function() {
      var obj = this._wrapped;
      method.apply(obj, arguments);
      if ((name == 'shift' || name == 'splice') && obj.length === 0) delete obj[0];
      return result.call(this, obj);
    };
  });

  // Add all accessor Array functions to the wrapper.
  each(['concat', 'join', 'slice'], function(name) {
    var method = ArrayProto[name];
    _.prototype[name] = function() {
      return result.call(this, method.apply(this._wrapped, arguments));
    };
  });

  _.extend(_.prototype, {

    // Start chaining a wrapped Underscore object.
    chain: function() {
      this._chain = true;
      return this;
    },

    // Extracts the result from a wrapped and chained object.
    value: function() {
      return this._wrapped;
    }

  });

  define('underscore', [], function() {return _;});

}).call(this);

var z = {},
    // pretend to be underscore without the page weight
    _ = {
        extend: function(obj, ext) {
            for (var p in ext) {
                obj[p] = ext[p];
            }
        }
    };

var preauth_window;

(function() {
    var win_top = window.top;
    if (win_top.opener) {
        win_top = win_top.opener;
    }
    $('.purchase').click(function(e) {
        $(this).addClass('purchasing').html($(this).data('purchasing-label'));
    });
    $('#setup-preauth').click(function(e) {
        e.preventDefault();
        if (preauth_window) {
            preauth_window.close();
        }
        preauth_window = window.open($(this).attr('href'));
        window.addEventListener('message', function(msg) {
            var result = msg.data;
            if (result == 'complete' || result == 'cancel') {
                preauth_window.close();
                window.location.reload();
            }
        }, false);
    });
    $('.close').click(function() {
        if ($('body').hasClass('success')) {
            win_top.postMessage('moz-pay-success', '*');
        } else {
            win_top.postMessage('moz-pay-cancel', '*');
        }
    });

})();

define('payments/payments',
    ['capabilities', 'l10n', 'notification', 'requests', 'settings', 'urls'],
    function(caps, l10n, notification, requests, settings, urls) {

    var notify = notification.notification;
    var gettext = l10n.gettext;

    function waitForPayment($def, product, webpayJWT, contribStatusURL) {
        var checkFunc = function() {
            requests.get(settings.api_url + urls.api.sign(contribStatusURL)).done(function(result) {
                if (result.status == 'complete') {
                    $def.resolve(product);
                }
            }).fail(function() {
                $def.reject(null, product, 'MKT_SERVER_ERROR');
            });
        };
        var checker = setInterval(checkFunc, 3000);
        var giveUp = setTimeout(function() {
            $def.reject(null, product, 'MKT_INSTALL_ERROR');
        }, 60000);

        checkFunc();

        $def.always(function() {
            clearTimeout(checker);
            clearTimeout(giveUp);
        });
    }

    if (settings.simulate_nav_pay && !caps.navPay) {
        navigator.mozPay = function(jwts) {
            var request = {
                onsuccess: function() {
                    console.warning('[payments][mock] handler did not define request.onsuccess');
                },
                onerror: function() {
                    console.warning('[payments][mock] handler did not define request.onerror');
                }
            };
            console.log('[payments][mock] STUB navigator.mozPay received', jwts);
            console.log('[payments][mock] calling onsuccess() in 3 seconds...');
            setTimeout(function() {
                console.log('[payments][mock] calling onsuccess()');
                request.onsuccess();
            }, 3000);
            return request;
        };
        console.log('[payments] stubbed out navigator.mozPay()');
    }

    function beginPurchase(product) {
        if (!product) return;
        var $def = $.Deferred();

        console.log('[payments] Initiating transaction');

        if (caps.navPay || settings.simulate_nav_pay) {
            requests.post(urls.api.url('prepare_nav_pay'), {app: product.slug}).done(function(result) {
                console.log('[payments] Calling mozPay with JWT: ', result.webpayJWT);
                var request = navigator.mozPay([result.webpayJWT]);
                request.onsuccess = function() {
                    console.log('[payments] navigator.mozPay success');
                    waitForPayment($def, product, result.webpayJWT, result.contribStatusURL);
                };
                request.onerror = function() {
                    if (this.error.name !== 'cancelled') {
                        console.log('navigator.mozPay error:', this.error.name);
                        notify({
                            classes: 'error',
                            message: gettext('Payment failed. Try again later.'),
                            timeout: 5000
                        });
                    }
                    $def.reject(null, product, 'MKT_CANCELLED');
                };
            }).fail(function() {
                $def.reject(null, product, 'MKT_SERVER_ERROR');
            });

        } else {
            $def.reject(null, product, 'MKT_CANCELLED');
        }

        return $def.promise();
    }

    return {
        'purchase': beginPurchase
    };
});

define('views/abuse',
       ['forms', 'l10n', 'notification', 'requests', 'urls', 'z'],
       function(forms, l10n, notification, requests, urls, z) {
    'use strict';

    var gettext = l10n.gettext;
    var notify = notification.notification;

    // XXX: This handles **ALL** abuse form submission.
    z.page.on('submit', '.abuse-form', function(e) {
        e.preventDefault();
        // Submit report abuse form
        var $this = $(this);
        var slug = $this.find('input[name=app]').val();
        var data = $this.serialize();

        forms.toggleSubmitFormState($this);

        requests.post($this.data('action'), data).done(function(data) {
            notify({message: gettext('Abuse reported')});
            z.page.trigger('navigate', urls.reverse('app', [slug]));
        }).fail(function() {
            forms.toggleSubmitFormState($this, true);
            notify({message: gettext('Error while submitting report')});
        });
    });

    return function(builder, args) {
        builder.start('detail/abuse.html', {slug: args[0]});

        builder.z('type', 'leaf');
        builder.z('title', gettext('Report Abuse'));
    };
});

define('views/app',
    ['capabilities', 'l10n', 'utils', 'requests', 'urls', 'z', 'templates', 'overflow'],
    function(caps, l10n, utils, requests, urls, z, nunjucks, overflow) {
    'use strict';

    z.page.on('click', '#product-rating-status .toggle', utils._pd(function() {
        // Show/hide scary content-rating disclaimers to developers.
        $(this).closest('.toggle').siblings('div').toggleClass('hidden');

    })).on('click', '.show-toggle', utils._pd(function() {
        var $this = $(this),
            newTxt = $this.attr('data-toggle-text');
        // Toggle "more..." or "less..." text.
        $this.attr('data-toggle-text', $this.text());
        $this.text(newTxt);
        // Toggle description.
        $this.closest('.blurbs').find('.collapsed').toggle();

    })).on('click', '.approval-pitch', utils._pd(function() {
        $('#preapproval-shortcut').submit();

    })).on('click', '.product-details .icon', utils._pd(function(e) {
        // When I click on the icon, append `#id=<id>` to the URL.
        window.location.hash = 'id=' + $('.product').data('product')['id'];
        e.stopPropagation();
    }));

    // Init desktop abuse form modal trigger.
    // The modal is responsive even if this handler isn't removed.
    if (caps.widescreen) {
        z.page.on('click', '.abuse .button', function(e) {
            e.preventDefault();
            e.stopPropagation();
            z.body.trigger('decloak');
            $('.report-abuse.modal').addClass('show');
        });
    }

    return function(builder, args) {
        builder.start('detail/main.html', {slug: args[0]});

        builder.z('type', 'leaf');
        builder.z('reload_on_login', true);
        builder.z('title', gettext('Loading...'));
        builder.z('pagetitle', gettext('App Details'));

        builder.onload('app-data', function() {
            builder.z('title', builder.results['app-data'].name);
            z.page.trigger('populatetray');
            overflow.init();
        }).onload('ratings', function() {
            var reviews = $('.detail .reviews li');
            if (reviews.length < 3) return;

            for (var i = 0; i < reviews.length - 2; i += 2) {
                var hgt = Math.max(reviews.eq(i).find('.review-inner').height(),
                                   reviews.eq(i + 1).find('.review-inner').height());
                reviews.eq(i).find('.review-inner').height(hgt);
                reviews.eq(i + 1).find('.review-inner').height(hgt);
            }
        });
    };
});

define('views/category',
    ['capabilities', 'models', 'underscore', 'urls', 'utils', 'z'],
    function(capabilities, models, _, urls, utils, z) {
    'use strict';

    var cat_models = models('category');

    return function(builder, args, params) {
        var category = args[0];
        params = params || {};

        var model = cat_models.lookup(category);

        builder.z('type', 'root');
        builder.z('title', (model && model.name) || category);
        builder.z('show_cats', true);
        builder.z('cat', category);

        if ('src' in params) {
            delete params.src;
        }

        builder.start('category/main.html', {
            category: category,
            category_name: category,
            endpoint: urls.api.url('category', [category], params),
            sort: params.sort
        });
    };
});

define('views/debug',
    ['buckets', 'cache', 'capabilities', 'notification', 'utils', 'z'],
    function(buckets, cache, capabilities, notification, utils, z) {
    'use strict';

    var debugEnabled = localStorage.getItem('debug-enabled');
    var label = $(document.getElementById('debug-status'));
    z.doc.on('click', '#toggle-debug', function() {
        debugEnabled = localStorage.getItem('debug-enabled');
        if (debugEnabled === 'yes') {
            notification.notification({message: 'debug mode disabled', timeout: 1000});
            localStorage.setItem('debug-enabled', 'no');
            label.text('no');
        } else {
            notification.notification({message: 'debug mode enabled', timeout: 1000});
            localStorage.setItem('debug-enabled', 'yes');
            label.text('yes');
        }
    }).on('click', '.cache-menu a', function(e) {
        e.preventDefault();
        var data = cache.get($(this).data('url'));
        data = JSON.stringify(data, null, '  ');
        $('#cache-inspector').html(utils.escape_(data));
    });

    return function debug_view(builder, args) {
        builder.start('debug.html', {
            cache: cache.raw,
            capabilities: capabilities,
            dbg: debugEnabled || 'no',
            profile: buckets.get_profile()
        });

        builder.z('type', 'leaf');
    };
});

define('views/featured', ['urls', 'z'], function(urls, z) {

    return function(builder, args, __, params) {
        var category = args[0] || '';
        params = params || {};

        if (category === 'all' || category === undefined) {
            category = '';
        } else {
            builder.z('parent', urls.reverse('category', [category]));
        }

        builder.z('type', 'search');
        builder.z('search', params.name || category);
        builder.z('title', params.name || category);

        builder.start('featured.html', {
            category: category,
            endpoint: urls.api.url('category', [category])
        });
    };

});

define('views/feedback',
       ['buckets', 'capabilities', 'forms', 'l10n', 'notification', 'requests', 'z'],
       function(buckets, caps, forms, l10n, notification, requests, z) {

    var gettext = l10n.gettext;
    var notify = notification.notification;
    var nunjucks = require('templates');
    var urls = require('urls');
    var utils = require('utils');

    z.page.on('submit', '.feedback-form', function(e) {
        e.preventDefault();

        var $this = $(this);
        var data = utils.getVars($this.serialize());
        data.chromeless = caps.chromeless ? 'Yes' : 'No';
        data.from_url = window.location.pathname;
        data.profile = buckets.get_profile();

        forms.toggleSubmitFormState($this);

        requests.post(urls.api.url('feedback'), data).done(function(data) {
            $this.find('textarea').val('');
            forms.toggleSubmitFormState($this, true);
            $('.cloak').trigger('dismiss');
            notify({message: gettext('Feedback submitted. Thanks!')});
        }).fail(function() {
            forms.toggleSubmitFormState($this, true);
            notify({
                message: gettext('There was a problem submitting your feedback. Try again soon.')
            });
        });
    });

    // Init desktop feedback form modal trigger.
    // The modal is responsive even if this handler isn't removed.
    if (caps.widescreen) {
        z.page.on('loaded', function() {
            z.page.append(
                nunjucks.env.getTemplate('settings/feedback.html').render(require('helpers'))
            );
        });
        z.body.on('click', '.submit-feedback', function(e) {
            e.preventDefault();
            e.stopPropagation();
            z.body.trigger('decloak');
            $('.feedback.modal').addClass('show');
        });
    }

    return function(builder, args) {
        builder.start('settings/feedback.html').done(function() {
            $('.feedback').removeClass('modal');
        });

        builder.z('type', 'leaf');
        builder.z('title', gettext('Feedback'));
    };
});

define('views/homepage',
    ['l10n', 'underscore', 'urls'],
    function(l10n, _, urls) {
    'use strict';

    var gettext = l10n.gettext;

    return function(builder, args, params) {
        params = params || {};

        builder.z('title', '');  // We don't want a title on the homepage.

        builder.z('type', 'root');
        builder.z('search', params.name);
        builder.z('title', params.name);

        builder.z('cat', 'all');
        builder.z('show_cats', true);

        if ('src' in params) {
            delete params.src;
        }

        builder.start('category/main.html', {
            endpoint: urls.api.url('category', [''], params),
            category_name: gettext('All Categories'),
            sort: params.sort
        });
    };
});

define('views/not_found', ['l10n'], function(l10n) {

    var gettext = l10n.gettext;

    return function(builder) {
        builder.start('not_found.html');

        builder.z('type', 'leaf');
        builder.z('title', gettext('Not Found'));
    };
});

define('views/privacy', ['l10n'], function(l10n) {
    'use strict';

    var gettext = l10n.gettext;

    return function(builder) {
        builder.start('privacy.html');

        builder.z('type', 'leaf');
        builder.z('title', gettext('Privacy Policy'));
    };
});

define('views/purchases', ['l10n', 'urls', 'z'],
    function(l10n, urls, z) {
    'use strict';

    var gettext = l10n.gettext;

    return function(builder, args) {
        builder.start('user/purchases.html');

        builder.z('type', 'root');
        builder.z('reload_on_login', true);
        builder.z('title', gettext('My Apps'));
    };
});

define('views/search',
    ['capabilities', 'l10n', 'underscore', 'utils', 'z'],
    function(capabilities, l10n, _, utils, z) {

    var _pd = utils._pd;
    var gettext = l10n.gettext;
    var ngettext = l10n.ngettext;

    // Clear search field on 'cancel' search suggestions.
    $('#site-header').on('click', '.header-button.cancel', _pd(function() {
        $('#site-search-suggestions').trigger('dismiss');
        $('#search-q').val('');

    })).on('click', '.header-button, .search-clear', _pd(function(e) {
        var $this = $(this),
            $btns = $('.header-button');

        if ($this.hasClass('search-clear')) {
            $('#search-q').val('').focus();
        }
    }));

    // Default to the graphical view at desktop widths and traditional
    // list view at lesser widths.
    var expand = capabilities.widescreen;
    if ('expand-listings' in localStorage) {
        // If we've set this value in localStorage before, then use it.
        expand = localStorage['expand-listings'] === 'true';
    }

    function setTrays(expanded) {
        if (expanded !== undefined) {
            expand = expanded;
        }
        $('ol.listing').toggleClass('expanded', expanded);
        $('.expand-toggle').toggleClass('active', expand);
        localStorage.setItem('expand-listings', expanded);
        if (expanded) {
            z.page.trigger('populatetray');
        }
    }

    z.body.on('click', '.expand-toggle', _pd(function() {
        setTrays(expand = !expand);
    }));

    z.page.on('loaded', function() {
        var $q = $('#search-q');
        $q.val(z.context.search);
        // If this is a search results or "my apps" page.
        if ($('#search-results').length || $('#account-settings .listing').length) {
            setTrays(expand);
        }
    }).on('reloaded_chrome', function() {
        setTrays(expand);
    }).on('loaded_more', function() {
        z.page.trigger('populatetray');
        // Update "Showing 1—{total}" text.
        z.page.find('.total-results').text(z.page.find('.item.app').length);
    });

    return function(builder, args, params) {
        if ('sort' in params && params.sort == 'relevancy') {
            delete params.sort;
        }

        builder.z('type', 'search');
        builder.z('search', params.q);
        builder.z('title', params.q || gettext('Search Results'));

        builder.start(
            'search/main.html',
            {params: _.extend({}, params)}
        );
    };

});

define('views/settings',
    ['l10n', 'notification', 'requests', 'urls', 'user', 'utils', 'z'],
    function(l10n, notification, requests, urls, user, utils, z) {

    var _pd = utils._pd;
    var gettext = l10n.gettext;
    var notify = notification.notification;

    function update_settings() {
        var acc_sett = $('.account-settings');
        if (!acc_sett.length) {
            return;
        }
        acc_sett.find('[name=display_name]').val(user.get_setting('display_name'));
        acc_sett.find('[name=email]').val(user.get_setting('email'));
        acc_sett.find('[name=region]').val(user.get_setting('region'));
        z.page.trigger('reload_chrome');
    }

    z.page.on('submit', 'form.account-settings', _pd(function(e) {
        e.stopPropagation();
        var completion = $.Deferred();
        completion.done(function() {
            update_settings();
            notify({message: gettext('Settings saved')});
        }).fail(function() {
            notify({message: gettext('Settings could not be saved')});
        });

        if (!user.logged_in()) {
            user.update_settings({region: $('[name=region]').val()});
            completion.resolve();
            return;
        }
        var data = utils.getVars($(this).serialize());
        user.update_settings(data);
        requests.patch(urls.api.url('settings'), data)
                .done(completion.resolve)
                .fail(completion.reject);
    })).on('logged_in', update_settings);

    return function(builder) {
        builder.start('settings/main.html');

        builder.z('type', 'root settings');
        builder.z('title', gettext('Account Settings'));
        builder.done();
    };
});

define('views/terms', ['l10n'], function(l10n) {
    'use strict';

    var gettext = l10n.gettext;

    return function(builder) {
        builder.start('terms.html');

        builder.z('type', 'leaf');
        builder.z('title', gettext('Terms of Use'));
    };
});

define('views/tests', ['assert'], function() {
    return function(builder) {
        var started = 0;
        var passed = 0;
        var failed = 0;

        function is_done() {
            var ndone = passed + failed;
            var progress = $('progress');
            progress.attr('value', ndone / started);
            if (ndone === started) {
                console.log('Tests completed.');
                $('<b>Completed ' + ndone + ' tests.</b>').insertAfter(progress);
            }
        }

        window.test = function(name, runner) {
            started++;
            is_done();
            setTimeout(function() {
                var infobox = $('<li><b>' + name + '</b> <span>Running...</span></li>');
                $('ol.tests').append(infobox);
                var completion = function() {
                    passed++;
                    $('#c_passed').text(passed);
                    infobox.find('span').text('Passed').css('background-color', 'lime');
                    is_done();
                };
                var has_failed = function(message) {
                    console.error(name, message);
                    failed++;
                    infobox.find('span').html('Failed<br>' + message).css('background-color', 'pink');
                    $('#c_failed').text(failed);
                };
                try {
                    console.log('Starting ' + name);
                    infobox.find('span').text('Started').css('background-color', 'goldenrod');
                    runner(completion, has_failed);
                } catch (e) {
                    has_failed(e.message);
                }
            }, 0);
            $('#c_started').text(started);
        };
        builder.start('tests.html');

        builder.z('type', 'leaf');
        builder.z('title', 'Unit Tests');
    };
});

define('views/app/abuse',
       ['forms', 'l10n', 'notification', 'requests', 'urls', 'z'],
       function(forms, l10n, notification, requests, urls, z) {

    var gettext = l10n.gettext;
    var notify = notification.notification;

    z.page.on('submit', '.abuse-form', function(e) {
        e.preventDefault();
        // Submit report abuse form
        var $this = $(this);
        var slug = $this.find('input[name=app]').val();
        var data = $this.serialize();

        forms.toggleSubmitFormState($this);

        requests.post($this.data('action'), data).done(function(data) {
            notify({message: gettext('Abuse reported')});
            z.page.trigger('navigate', urls.reverse('app', [slug]));
        }).fail(function() {
            forms.toggleSubmitFormState($this, true);
            notify({message: gettext('Error while submitting report')});
        });
    });

    return function(builder, args) {
        builder.start('detail/abuse.html', {slug: args[0]}).done(function() {
            $('.report-abuse').removeClass('modal');
        });

        builder.z('type', 'leaf');
        builder.z('parent', urls.reverse('app', [args[0]]));
        builder.z('title', gettext('Report Abuse'));
    };
});

define('views/app/privacy', ['l10n', 'urls'], function(l10n, urls) {

    var gettext = l10n.gettext;

    return function(builder, args) {
        builder.start('detail/privacy.html', {slug: args[0]});

        builder.z('type', 'leaf');
        builder.z('parent', urls.reverse('app', [args[0]]));
        builder.z('title', gettext('Privacy Policy'));
    };
});

define('views/app/ratings', ['l10n', 'urls'], function(l10n, urls) {

    var gettext = l10n.gettext;

    return function(builder, args) {
        var slug = args[0];
        builder.start('ratings/main.html', {
            'slug': slug
        });

        builder.z('type', 'leaf');
        builder.z('reload_on_login', true);
        builder.z('parent', urls.reverse('app', [slug]));
        builder.z('title', gettext('Reviews'));
    };
});

define('views/app/ratings/add',
    ['login', 'l10n', 'urls', 'user', 'z'],
    function(login, l10n, urls, user, z) {

    var gettext = l10n.gettext;

    return function(builder, args) {
        var slug = args[0];

        // If the user isn't logged in, redirect them to the detail page and
        // open a login window. If they complete the login, click the Write
        // Review button if it exists.
        if (!user.logged_in()) {
            z.page.trigger('navigate', urls.reverse('app', [slug]));
            setTimeout(function() {
                login.login().done(function() {
                    $('#add-review').click();
                });
            }, 0);
            return;
        }

        builder.start('ratings/write.html', {'slug': slug}).done(function() {
            $('.compose-review').removeClass('modal');
        });

        builder.z('type', 'leaf');
        builder.z('parent', urls.reverse('app/ratings', [slug]));
        builder.z('title', gettext('Write a Review'));
    };
});

define('views/app/ratings/edit',
    ['l10n', 'notification', 'ratings', 'requests', 'settings', 'urls', 'user', 'utils', 'z'],
    function(l10n, notification, ratings, requests, settings, urls, user, utils, z) {

    var gettext = l10n.gettext;
    var notify = notification.notification;
    var forms = require('forms');

    z.page.on('submit', '.edit-review-form', function(e) {
        e.preventDefault();
        var $this = $(this);
        var uri = $this.data('uri');
        var slug = $this.data('slug');
        var _data = utils.getVars($this.serialize());

        forms.toggleSubmitFormState($this);

        requests.put(
            settings.api_url + urls.api.sign(uri),
            _data
        ).done(function() {
            notify({message: gettext('Review updated successfully')});

            ratings._rewriter(slug, function(data) {
                for (var i = 0; i < data.objects.length; i++) {
                    if (data.objects[i].resource_uri === uri) {
                        data.objects[i].body = _data.body;
                        data.objects[i].rating = _data.rating;
                    }
                }
                return data;
            });

            z.page.trigger('navigate', urls.reverse('app', [slug]));
        }).fail(function() {
            forms.toggleSubmitFormState($this, true);
            notify({message: gettext('There was a problem updating your review')});
        });
    });

    return function(builder, args) {
        var slug = args[0];

        // If the user isn't logged in, divert them to the app detail page.
        // I'm not concerned with trying to log them in because they shouldn't
        // have even gotten to this page in their current state anyway.
        if (!user.logged_in()) {
            z.page.trigger('navigate', urls.reverse('app', [slug]));
            return;
        }

        builder.start('ratings/edit.html', {'slug': slug}).done(function() {
            $('.edit-review-form .cancel').click(utils._pd(function() {
                z.page.trigger('navigate', urls.reverse('app', [slug]));
            }));
        });

        // If we hit the API and find out that there's no review for the user,
        // just bump them over to the Write a Review page.
        builder.onload('main', function(data) {
            if (data.meta.total_count === 0) {
                z.page.trigger('divert', urls.reverse('app/ratings/add', [slug]));
            }
        });

        builder.z('type', 'leaf');
        builder.z('reload_on_login', true);
        builder.z('parent', urls.reverse('app/ratings', [slug]));
        builder.z('title', gettext('Edit Review'));
    };
});

(function() {var templates = {};
templates["_macros/emaillink.html"] = (function() {function root(env, context, frame, runtime) {
var lineno = null;
var colno = null;
var output = "";
try {
output += "\n\n";
var macro_t_1 = runtime.makeMacro(
["email"], 
["title", "class"], 
function (l_email, kwargs) {
frame = frame.push();
kwargs = kwargs || {};
frame.set("email", l_email);
frame.set("title", kwargs.hasOwnProperty("title") ? kwargs["title"] : runtime.contextOrFrameLookup(context, frame, "None"));
frame.set("class", kwargs.hasOwnProperty("class") ? kwargs["class"] : runtime.contextOrFrameLookup(context, frame, "None"));
var output= "";
output += "\n  <a";
if(runtime.contextOrFrameLookup(context, frame, "class")) {
output += " class=\"";
output += runtime.suppressValue(runtime.contextOrFrameLookup(context, frame, "class"), env.autoesc);
output += "\"";
}
output += " href=\"mailto:";
output += runtime.suppressValue(l_email, env.autoesc);
output += "\">";
output += runtime.suppressValue(runtime.contextOrFrameLookup(context, frame, "title"), env.autoesc);
output += "</a>\n";
frame = frame.pop();
return new runtime.SafeString(output);
});
context.addExport("emaillink");
context.setVariable("emaillink", macro_t_1);
output += "\n";
return output;
} catch (e) {
  runtime.handleError(e, lineno, colno);
}
}
return {
root: root
};
})();
templates["_macros/forms.html"] = (function() {function root(env, context, frame, runtime) {
var lineno = null;
var colno = null;
var output = "";
try {
var macro_t_1 = runtime.makeMacro(
[], 
[], 
function (kwargs) {
frame = frame.push();
kwargs = kwargs || {};
var output= "";
output += "\n  <input type=\"text\" name=\"sprout\" value=\"potato\" class=\"potato-captcha\">\n  <input type=\"text\" name=\"tuber\" class=\"potato-captcha\">\n";
frame = frame.pop();
return new runtime.SafeString(output);
});
context.addExport("potato_captcha");
context.setVariable("potato_captcha", macro_t_1);
output += "\n";
return output;
} catch (e) {
  runtime.handleError(e, lineno, colno);
}
}
return {
root: root
};
})();
templates["_macros/market_button.html"] = (function() {function root(env, context, frame, runtime) {
var lineno = null;
var colno = null;
var output = "";
try {
var macro_t_1 = runtime.makeMacro(
["app", "classes", "data_attrs"], 
[], 
function (l_app, l_classes, l_data_attrs, kwargs) {
frame = frame.push();
kwargs = kwargs || {};
frame.set("app", l_app);
frame.set("classes", l_classes);
frame.set("data_attrs", l_data_attrs);
var output= "";
output += "\n  ";
var t_2 = (runtime.memberLookup((l_app),"price", env.autoesc)?runtime.memberLookup((l_app),"price_locale", env.autoesc):(lineno = 1, colno = 51, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "_"), "_", ["Free"])));
frame.set("price", t_2);
if(!frame.parent) {
context.setVariable("price", t_2);
context.addExport("price");
}
output += "\n  ";
var t_3 = l_classes || [];
frame.set("classes", t_3);
if(!frame.parent) {
context.setVariable("classes", t_3);
context.addExport("classes");
}
output += "\n  <button class=\"button product install ";
output += runtime.suppressValue(env.getFilter("join")(t_3," "), env.autoesc);
output += "\" ";
output += runtime.suppressValue(env.getFilter("make_data_attrs")(l_data_attrs), env.autoesc);
output += ">\n    ";
output += runtime.suppressValue((runtime.memberLookup((runtime.memberLookup((l_app),"user", env.autoesc)),"installed", env.autoesc) || runtime.memberLookup((runtime.memberLookup((l_app),"user", env.autoesc)),"purchased", env.autoesc)?(lineno = 4, colno = 6, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "_"), "_", ["Install"])):t_2), env.autoesc);
output += "\n  </button>\n";
frame = frame.pop();
return new runtime.SafeString(output);
});
context.addExport("market_button");
context.setVariable("market_button", macro_t_1);
output += "\n";
return output;
} catch (e) {
  runtime.handleError(e, lineno, colno);
}
}
return {
root: root
};
})();
templates["_macros/market_tile.html"] = (function() {function root(env, context, frame, runtime) {
var lineno = null;
var colno = null;
var output = "";
try {
var includeTemplate = env.getTemplate("_macros/stars.html");
output += includeTemplate.render(context.getVariables(), frame.push());
output += "\n";
var includeTemplate = env.getTemplate("_macros/market_button.html");
output += includeTemplate.render(context.getVariables(), frame.push());
output += "\n\n";
var macro_t_1 = runtime.makeMacro(
["app"], 
["link", "src", "classes", "data_attrs", "force_button"], 
function (l_app, kwargs) {
frame = frame.push();
kwargs = kwargs || {};
frame.set("app", l_app);
frame.set("link", kwargs.hasOwnProperty("link") ? kwargs["link"] : runtime.contextOrFrameLookup(context, frame, "False"));
frame.set("src", kwargs.hasOwnProperty("src") ? kwargs["src"] : runtime.contextOrFrameLookup(context, frame, "None"));
frame.set("classes", kwargs.hasOwnProperty("classes") ? kwargs["classes"] : runtime.contextOrFrameLookup(context, frame, "None"));
frame.set("data_attrs", kwargs.hasOwnProperty("data_attrs") ? kwargs["data_attrs"] : runtime.contextOrFrameLookup(context, frame, "None"));
frame.set("force_button", kwargs.hasOwnProperty("force_button") ? kwargs["force_button"] : runtime.contextOrFrameLookup(context, frame, "False"));
var output= "";
output += "\n  ";
var t_2 = (runtime.contextOrFrameLookup(context, frame, "link")?"a":"div");
frame.set("tag", t_2);
if(!frame.parent) {
context.setVariable("tag", t_2);
context.addExport("tag");
}
output += "\n  ";
var t_3 = runtime.contextOrFrameLookup(context, frame, "classes") || [];
frame.set("classes", t_3);
if(!frame.parent) {
context.setVariable("classes", t_3);
context.addExport("classes");
}
output += "\n  <";
output += runtime.suppressValue(t_2, env.autoesc);
output += " class=\"product mkt-tile ";
output += runtime.suppressValue(env.getFilter("join")(t_3," "), env.autoesc);
output += "\"\n    ";
if(runtime.contextOrFrameLookup(context, frame, "link")) {
output += " href=\"";
output += runtime.suppressValue(env.getFilter("urlparams")((lineno = 7, colno = 24, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "url"), "url", ["app",[runtime.memberLookup((l_app),"slug", env.autoesc)]])),runtime.makeKeywordArgs({"src": runtime.contextOrFrameLookup(context, frame, "src")})), env.autoesc);
output += "\"";
}
output += "\n    ";
output += runtime.suppressValue(env.getFilter("make_data_attrs")(runtime.contextOrFrameLookup(context, frame, "data_attrs")), env.autoesc);
output += "\n    ";
output += runtime.suppressValue(env.getFilter("dataproduct")(l_app), env.autoesc);
output += "\n    ";
if(runtime.contextOrFrameLookup(context, frame, "link")) {
output += "itemscope itemtype=\"http://schema.org/SoftwareApplication\"";
}
output += ">\n    <img class=\"icon\" alt=\"\" src=\"";
output += runtime.suppressValue(runtime.memberLookup((runtime.memberLookup((l_app),"icons", env.autoesc)),64, env.autoesc), env.autoesc);
output += "\" height=\"64\" width=\"64\" itemprop=\"image\">\n    <div class=\"info\">\n      <h3 itemprop=\"name\">";
output += runtime.suppressValue(runtime.memberLookup((l_app),"name", env.autoesc), env.autoesc);
output += "</h3>\n      ";
if(runtime.memberLookup((l_app),"listed_authors", env.autoesc)) {
output += "\n        ";
output += "\n        <div class=\"author lineclamp vital\" itemprop=\"creator\">";
output += runtime.suppressValue(runtime.memberLookup((runtime.memberLookup((runtime.memberLookup((l_app),"listed_authors", env.autoesc)),0, env.autoesc)),"name", env.autoesc), env.autoesc);
output += "</div>\n      ";
}
output += "\n      <div class=\"price vital\">";
output += runtime.suppressValue((runtime.memberLookup((l_app),"price", env.autoesc)?runtime.memberLookup((l_app),"price_locale", env.autoesc):(lineno = 18, colno = 68, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "_"), "_", ["Free"]))), env.autoesc);
output += "</div>\n      <div class=\"rating vital";
output += runtime.suppressValue((!runtime.memberLookup((runtime.memberLookup((l_app),"ratings", env.autoesc)),"count", env.autoesc)?" unrated":""), env.autoesc);
output += "\" itemprop=\"aggregateRating\" itemscope itemtype=\"http://schema.org/AggregateRating\">\n        ";
if(!runtime.contextOrFrameLookup(context, frame, "link")) {
output += "\n          <a href=\"";
output += runtime.suppressValue((lineno = 21, colno = 23, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "url"), "url", ["app/ratings",[runtime.memberLookup((l_app),"slug", env.autoesc)]])), env.autoesc);
output += "\" class=\"rating_link\">\n        ";
}
output += "\n        ";
output += runtime.suppressValue((lineno = 23, colno = 14, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "stars"), "stars", [runtime.memberLookup((runtime.memberLookup((l_app),"ratings", env.autoesc)),"average", env.autoesc)])), env.autoesc);
output += "\n        ";
if(runtime.memberLookup((runtime.memberLookup((l_app),"ratings", env.autoesc)),"count", env.autoesc)) {
output += "\n          <span class=\"cnt short\">\n            ";
output += runtime.suppressValue((lineno = 26, colno = 14, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "_"), "_", ["({n})",runtime.makeKeywordArgs({"n": "<span itemprop=\"reviewCount\">" + runtime.memberLookup((runtime.memberLookup((l_app),"ratings", env.autoesc)),"count", env.autoesc) + "</span>"})])), env.autoesc);
output += "\n          </span>\n          <span class=\"cnt long\">\n            ";
output += runtime.suppressValue((lineno = 29, colno = 20, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "_plural"), "_plural", ["{n} Review","{n} Reviews",runtime.makeKeywordArgs({"n": runtime.memberLookup((runtime.memberLookup((l_app),"ratings", env.autoesc)),"count", env.autoesc)})])), env.autoesc);
output += "\n          </span>\n        ";
}
else {
output += "\n          ";
output += "\n          <span class=\"cnt short\">";
output += runtime.suppressValue((lineno = 33, colno = 36, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "_"), "_", ["(0)"])), env.autoesc);
output += "</span>\n          <span class=\"cnt long\">";
output += runtime.suppressValue((lineno = 34, colno = 35, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "_"), "_", ["Not yet rated"])), env.autoesc);
output += "</span>\n        ";
}
output += "\n        ";
if(!runtime.contextOrFrameLookup(context, frame, "link")) {
output += "</a>";
}
output += "\n      </div>\n      ";
if(runtime.contextOrFrameLookup(context, frame, "force_button") || (runtime.memberLookup((l_app),"current_version", env.autoesc) && !runtime.contextOrFrameLookup(context, frame, "link"))) {
output += "\n        ";
output += runtime.suppressValue((lineno = 39, colno = 22, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "market_button"), "market_button", [l_app,runtime.makeKeywordArgs({"classes": t_3,"data_attrs": {"manifest_url": runtime.memberLookup((l_app),"manifest_url", env.autoesc)}})])), env.autoesc);
output += "\n      ";
}
output += "\n    </div>\n    ";
frame = frame.push();
var t_5 = runtime.memberLookup((l_app),"notices", env.autoesc);
for(var t_4=0; t_4 < t_5.length; t_4++) {
var t_6 = t_5[t_4];
frame.set("notice", t_6);
output += "\n      <div class=\"bad-app\">";
output += runtime.suppressValue(t_6, env.autoesc);
output += "</div>\n    ";
}
frame = frame.pop();
output += "\n  </";
output += runtime.suppressValue(t_2, env.autoesc);
output += ">\n  <div class=\"tray previews full\"></div>\n";
frame = frame.pop();
return new runtime.SafeString(output);
});
context.addExport("market_tile");
context.setVariable("market_tile", macro_t_1);
output += "\n";
return output;
} catch (e) {
  runtime.handleError(e, lineno, colno);
}
}
return {
root: root
};
})();
templates["_macros/more_button.html"] = (function() {function root(env, context, frame, runtime) {
var lineno = null;
var colno = null;
var output = "";
try {
var macro_t_1 = runtime.makeMacro(
["next_page_url"], 
[], 
function (l_next_page_url, kwargs) {
frame = frame.push();
kwargs = kwargs || {};
frame.set("next_page_url", l_next_page_url);
var output= "";
output += "\n<li class=\"loadmore\">\n  <button class=\"alt\" data-url=\"";
output += runtime.suppressValue(env.getFilter("safe")((runtime.memberLookup((runtime.contextOrFrameLookup(context, frame, "settings")),"api_url", env.autoesc) + l_next_page_url)), env.autoesc);
output += "\">";
output += runtime.suppressValue((lineno = 2, colno = 77, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "_"), "_", ["More"])), env.autoesc);
output += "</button>\n</li>\n";
frame = frame.pop();
return new runtime.SafeString(output);
});
context.addExport("more_button");
context.setVariable("more_button", macro_t_1);
output += "\n";
return output;
} catch (e) {
  runtime.handleError(e, lineno, colno);
}
}
return {
root: root
};
})();
templates["_macros/rating.html"] = (function() {function root(env, context, frame, runtime) {
var lineno = null;
var colno = null;
var output = "";
try {
var includeTemplate = env.getTemplate("_macros/stars.html");
output += includeTemplate.render(context.getVariables(), frame.push());
output += "\n\n";
var macro_t_1 = runtime.makeMacro(
["this"], 
["detailpage"], 
function (l_this, kwargs) {
frame = frame.push();
kwargs = kwargs || {};
frame.set("this", l_this);
frame.set("detailpage", kwargs.hasOwnProperty("detailpage") ? kwargs["detailpage"] : false);
var output= "";
output += "\n<li data-report-uri=\"";
output += runtime.suppressValue(runtime.memberLookup((l_this),"report_spam", env.autoesc), env.autoesc);
output += "\" data-rating=\"";
output += runtime.suppressValue(runtime.memberLookup((l_this),"rating", env.autoesc), env.autoesc);
output += "\"\n    class=\"review";
output += runtime.suppressValue((runtime.memberLookup((l_this),"is_flagged", env.autoesc)?" flagged":""), env.autoesc);
output += " c\"\n    itemprop=\"review\" itemscope itemtype=\"http://schema.org/Review\">\n  <div class=\"review-inner\">\n    ";
output += runtime.suppressValue((lineno = 7, colno = 10, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "stars"), "stars", [runtime.memberLookup((l_this),"rating", env.autoesc),runtime.makeKeywordArgs({"detailpage": runtime.contextOrFrameLookup(context, frame, "detailpage"),"aggregate": runtime.contextOrFrameLookup(context, frame, "False")})])), env.autoesc);
output += "\n    <span class=\"byline\">\n      ";
output += runtime.suppressValue((lineno = 9, colno = 8, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "_"), "_", ["by {author}",runtime.makeKeywordArgs({"author": "<strong itemprop=\"author\">" + (lineno = 10, colno = 55, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "escape"), "escape", [runtime.memberLookup((runtime.memberLookup((l_this),"user", env.autoesc)),"display_name", env.autoesc)])) + "</strong>"})])), env.autoesc);
output += "\n      ";
if(runtime.memberLookup((l_this),"version", env.autoesc) && !runtime.memberLookup((runtime.memberLookup((l_this),"version", env.autoesc)),"latest", env.autoesc)) {
output += "\n        ";
output += runtime.suppressValue((lineno = 12, colno = 10, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "_"), "_", ["for previous version {version}",runtime.makeKeywordArgs({"version": runtime.memberLookup((runtime.memberLookup((l_this),"version", env.autoesc)),"name", env.autoesc)})])), env.autoesc);
output += "\n      ";
}
output += "\n    </span>\n    <div class=\"body\" itemprop=\"reviewBody\">\n      ";
output += runtime.suppressValue(env.getFilter("nl2br")(env.getFilter("escape")(runtime.memberLookup((l_this),"body", env.autoesc))), env.autoesc);
output += "\n    </div>\n    ";
if(!runtime.contextOrFrameLookup(context, frame, "detailpage")) {
output += "\n      <ul class=\"actions only-if-logged-in\">\n        ";
if(runtime.memberLookup((l_this),"is_flagged", env.autoesc)) {
output += "\n          <li class=\"flagged\">";
output += runtime.suppressValue((lineno = 21, colno = 32, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "_"), "_", ["Flagged for review"])), env.autoesc);
output += "</li>\n        ";
}
output += "\n        ";
if(runtime.memberLookup((l_this),"is_author", env.autoesc)) {
output += "\n          <li><a class=\"edit\"\n                 href=\"";
output += runtime.suppressValue((lineno = 25, colno = 27, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "url"), "url", ["app/ratings/edit",[runtime.contextOrFrameLookup(context, frame, "slug")]])), env.autoesc);
output += "\">";
output += runtime.suppressValue((lineno = 25, colno = 60, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "_"), "_", ["Edit"])), env.autoesc);
output += "</a></li>\n          <li><a class=\"delete post\" data-action=\"delete\" href=\"#\"\n                 data-href=\"";
output += runtime.suppressValue(runtime.memberLookup((l_this),"resource_uri", env.autoesc), env.autoesc);
output += "\"\n                 data-app=\"";
output += runtime.suppressValue(runtime.contextOrFrameLookup(context, frame, "slug"), env.autoesc);
output += "\">";
output += runtime.suppressValue((lineno = 28, colno = 37, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "_"), "_", ["Delete"])), env.autoesc);
output += "</a></li>\n        ";
}
else {
output += "\n          <li><a class=\"flag post\" data-action=\"report\" href=\"#\">";
output += runtime.suppressValue((lineno = 30, colno = 67, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "_"), "_", ["Report"])), env.autoesc);
output += "</a></li>\n        ";
}
output += "\n      </ul>\n      ";
output += "\n      <time itemprop=\"datePublished\">";
output += runtime.suppressValue(env.getFilter("replace")(runtime.memberLookup((l_this),"posted", env.autoesc)," 00:00:00",""), env.autoesc);
output += "</time>\n    ";
}
output += "\n  </div>\n</li>\n";
frame = frame.pop();
return new runtime.SafeString(output);
});
context.addExport("rating");
context.setVariable("rating", macro_t_1);
output += "\n";
return output;
} catch (e) {
  runtime.handleError(e, lineno, colno);
}
}
return {
root: root
};
})();
templates["_macros/stars.html"] = (function() {function root(env, context, frame, runtime) {
var lineno = null;
var colno = null;
var output = "";
try {
var macro_t_1 = runtime.makeMacro(
["rating"], 
["detailpage", "aggregate"], 
function (l_rating, kwargs) {
frame = frame.push();
kwargs = kwargs || {};
frame.set("rating", l_rating);
frame.set("detailpage", kwargs.hasOwnProperty("detailpage") ? kwargs["detailpage"] : false);
frame.set("aggregate", kwargs.hasOwnProperty("aggregate") ? kwargs["aggregate"] : runtime.contextOrFrameLookup(context, frame, "True"));
var output= "";
output += "\n  ";
var t_2 = env.getFilter("round")(l_rating);
frame.set("rating", t_2);
if(!frame.parent) {
context.setVariable("rating", t_2);
context.addExport("rating");
}
output += "\n  ";
var t_3 = (runtime.contextOrFrameLookup(context, frame, "aggregate")?"ratingValue":"reviewRating");
frame.set("rating_itemprop", t_3);
if(!frame.parent) {
context.setVariable("rating_itemprop", t_3);
context.addExport("rating_itemprop");
}
output += "\n  <meta itemprop=\"worstRating\" content=\"1\">\n  <span class=\"stars";
output += runtime.suppressValue((runtime.contextOrFrameLookup(context, frame, "detailpage")?" large":""), env.autoesc);
output += " large stars-";
output += runtime.suppressValue(t_2, env.autoesc);
output += "\" title=\"";
output += runtime.suppressValue(runtime.contextOrFrameLookup(context, frame, "title"), env.autoesc);
output += "\">\n    ";
output += runtime.suppressValue((lineno = 5, colno = 6, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "_"), "_", ["Rated {stars} out of {maxstars} stars",runtime.makeKeywordArgs({"stars": "<span itemprop=\"" + t_3 + "\">" + t_2 + "</span>","maxstars": "<span itemprop=\"bestRating\">5</span>"})])), env.autoesc);
output += "\n  </span>\n";
frame = frame.pop();
return new runtime.SafeString(output);
});
context.addExport("stars");
context.setVariable("stars", macro_t_1);
output += "\n";
return output;
} catch (e) {
  runtime.handleError(e, lineno, colno);
}
}
return {
root: root
};
})();
templates["cat_dropdown.html"] = (function() {function root(env, context, frame, runtime) {
var lineno = null;
var colno = null;
var output = "";
try {
output += "<div class=\"dropdown secondary-header\">\n  <a class=\"cat-all cat-icon\" data-cat-slug=\"all\" href=\"#\">";
output += runtime.suppressValue((lineno = 1, colno = 61, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "_"), "_", ["All Categories"])), env.autoesc);
output += "</a>\n</div>\n";
return output;
} catch (e) {
  runtime.handleError(e, lineno, colno);
}
}
return {
root: root
};
})();
templates["cat_list.html"] = (function() {function root(env, context, frame, runtime) {
var lineno = null;
var colno = null;
var output = "";
try {
output += "<menu class=\"cat-menu cat-icons hidden c\">\n  <li>\n    <a class=\"cat-all\" data-cat-slug=\"all\"\n       href=\"";
output += runtime.suppressValue((lineno = 3, colno = 17, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "url"), "url", ["homepage"])), env.autoesc);
output += "\">";
output += runtime.suppressValue((lineno = 3, colno = 34, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "_"), "_", ["All Categories"])), env.autoesc);
output += "</a>\n  </li>\n";
frame = frame.push();
var t_2 = runtime.contextOrFrameLookup(context, frame, "categories");
for(var t_1=0; t_1 < t_2.length; t_1++) {
var t_3 = t_2[t_1];
frame.set("cat", t_3);
output += "\n  <li>\n      <a class=\"cat-";
output += runtime.suppressValue(runtime.memberLookup((t_3),"slug", env.autoesc), env.autoesc);
output += "\" data-cat-slug=\"";
output += runtime.suppressValue(runtime.memberLookup((t_3),"slug", env.autoesc), env.autoesc);
output += "\"\n         href=\"";
output += runtime.suppressValue((lineno = 8, colno = 19, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "url"), "url", ["category",[runtime.memberLookup((t_3),"slug", env.autoesc)]])), env.autoesc);
output += "\">";
output += runtime.suppressValue(runtime.memberLookup((t_3),"name", env.autoesc), env.autoesc);
output += "</a>\n  </li>\n";
}
frame = frame.pop();
output += "\n</menu>\n";
return output;
} catch (e) {
  runtime.handleError(e, lineno, colno);
}
}
return {
root: root
};
})();
templates["category/main.html"] = (function() {function root(env, context, frame, runtime) {
var lineno = null;
var colno = null;
var output = "";
try {
var includeTemplate = env.getTemplate("_macros/market_tile.html");
output += includeTemplate.render(context.getVariables(), frame.push());
output += "\n";
var includeTemplate = env.getTemplate("_macros/more_button.html");
output += includeTemplate.render(context.getVariables(), frame.push());
output += "\n\n";
var t_1 = (lineno = 3, colno = 23, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "url"), "url", ["featured",[runtime.contextOrFrameLookup(context, frame, "category") || "all"]]));
frame.set("featured_url", t_1);
if(!frame.parent) {
context.setVariable("featured_url", t_1);
context.addExport("featured_url");
}
output += "\n";
var t_2 = env.getFilter("urlparams")(t_1,runtime.makeKeywordArgs({"src": "category-featured"}));
frame.set("featured_url", t_2);
if(!frame.parent) {
context.setVariable("featured_url", t_2);
context.addExport("featured_url");
}
output += "\n\n";
var t_3 = (runtime.contextOrFrameLookup(context, frame, "category")?(lineno = 6, colno = 23, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "url"), "url", ["category",[runtime.contextOrFrameLookup(context, frame, "category")]])):(lineno = 6, colno = 68, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "url"), "url", ["homepage"])));
frame.set("category_url", t_3);
if(!frame.parent) {
context.setVariable("category_url", t_3);
context.addExport("category_url");
}
output += "\n\n";
var t_4 = env.getFilter("urlparams")(t_3,runtime.makeKeywordArgs({"src": "category-popular"}));
frame.set("popular_url", t_4);
if(!frame.parent) {
context.setVariable("popular_url", t_4);
context.addExport("popular_url");
}
output += "\n";
var t_5 = env.getFilter("urlparams")(t_3,runtime.makeKeywordArgs({"sort": "created","src": "category-new"}));
frame.set("new_url", t_5);
if(!frame.parent) {
context.setVariable("new_url", t_5);
context.addExport("new_url");
}
output += "\n\n";
var t_6 = (runtime.contextOrFrameLookup(context, frame, "category")?env.getFilter("urlparams")((lineno = 11, colno = 21, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "url"), "url", ["search"])),runtime.makeKeywordArgs({"cat": runtime.contextOrFrameLookup(context, frame, "category")})):(lineno = 11, colno = 76, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "url"), "url", ["search"])));
frame.set("search_url", t_6);
if(!frame.parent) {
context.setVariable("search_url", t_6);
context.addExport("search_url");
}
output += "\n";
var t_7 = (runtime.contextOrFrameLookup(context, frame, "sort") == "created"?env.getFilter("urlparams")(t_6,runtime.makeKeywordArgs({"sort": runtime.contextOrFrameLookup(context, frame, "sort")})):t_6);
frame.set("search_url", t_7);
if(!frame.parent) {
context.setVariable("search_url", t_7);
context.addExport("search_url");
}
output += "\n\n";
output += runtime.suppressValue(env.getExtension("defer")["run"](context,runtime.makeKeywordArgs({"url": env.getFilter("urlunparam")(runtime.contextOrFrameLookup(context, frame, "endpoint"),["sort"]),"pluck": "featured","as": "app"}),function() {var t_8 = "";t_8 += "\n  <section id=\"featured\" class=\"main category featured full c\">\n    <header class=\"featured-header c\">\n      <h3>";
t_8 += runtime.suppressValue((lineno = 17, colno = 12, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "_"), "_", ["Featured Apps"])), env.autoesc);
t_8 += "</h3>\n      <a href=\"";
t_8 += runtime.suppressValue(t_2, env.autoesc);
t_8 += "\" class=\"view-all\">";
t_8 += runtime.suppressValue((lineno = 18, colno = 50, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "_"), "_", ["View All"])), env.autoesc);
t_8 += "</a>\n    </header>\n    <ol class=\"grid c\">\n      ";
frame = frame.push();
var t_10 = runtime.contextOrFrameLookup(context, frame, "this");
for(var t_9=0; t_9 < t_10.length; t_9++) {
var t_11 = t_10[t_9];
frame.set("result", t_11);
t_8 += "\n        <li>";
t_8 += runtime.suppressValue((lineno = 22, colno = 24, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "market_tile"), "market_tile", [t_11,runtime.makeKeywordArgs({"link": true,"src": "featured"})])), env.autoesc);
t_8 += "</li>\n      ";
}
frame = frame.pop();
t_8 += "\n    </ol>\n  </section>\n";
return t_8;
}
,function() {var t_12 = "";t_12 += "\n";
t_12 += "\n";
return t_12;
}
,function() {var t_13 = "";t_13 += "\n";
return t_13;
}
,function() {var t_14 = "";t_14 += "\n";
return t_14;
}
), env.autoesc);
output += "\n\n<section id=\"gallery\" class=\"main category gallery full c\">\n";
output += runtime.suppressValue(env.getExtension("defer")["run"](context,runtime.makeKeywordArgs({"url": runtime.contextOrFrameLookup(context, frame, "endpoint"),"pluck": "objects","as": "app","paginate": "ol.listing"}),function() {var t_15 = "";t_15 += "\n  ";
var t_16 = runtime.memberLookup((runtime.memberLookup((runtime.contextOrFrameLookup(context, frame, "response")),"meta", env.autoesc)),"total_count", env.autoesc) > runtime.memberLookup((runtime.memberLookup((runtime.contextOrFrameLookup(context, frame, "response")),"meta", env.autoesc)),"limit", env.autoesc);
frame.set("paginated", t_16);
if(!frame.parent) {
context.setVariable("paginated", t_16);
context.addExport("paginated");
}
t_15 += "\n  ";
if(t_16) {
t_15 += "\n    <header class=\"featured-header c\">\n      <nav class=\"tabs\">\n        <a";
if(!runtime.contextOrFrameLookup(context, frame, "sort")) {
t_15 += " class=\"active\"";
}
t_15 += " href=\"";
t_15 += runtime.suppressValue(t_4, env.autoesc);
t_15 += "\" data-preserve-scroll>";
t_15 += runtime.suppressValue((lineno = 39, colno = 90, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "_"), "_", ["Popular"])), env.autoesc);
t_15 += "</a>\n        <a";
if(runtime.contextOrFrameLookup(context, frame, "sort") == "created") {
t_15 += " class=\"active\"";
}
t_15 += " href=\"";
t_15 += runtime.suppressValue(t_5, env.autoesc);
t_15 += "\" data-preserve-scroll>";
t_15 += runtime.suppressValue((lineno = 40, colno = 95, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "_"), "_", ["New"])), env.autoesc);
t_15 += "</a>\n      </nav>\n      <a href=\"";
t_15 += runtime.suppressValue(t_7, env.autoesc);
t_15 += "\" class=\"view-all\">";
t_15 += runtime.suppressValue((lineno = 42, colno = 48, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "_"), "_", ["View All"])), env.autoesc);
t_15 += "</a>\n    </header>\n  ";
}
t_15 += "\n  <ol class=\"container listing grid-if-desktop search-listing c\">\n    ";
frame = frame.push();
var t_18 = runtime.contextOrFrameLookup(context, frame, "this");
for(var t_17=0; t_17 < t_18.length; t_17++) {
var t_19 = t_18[t_17];
frame.set("result", t_19);
t_15 += "\n      <li class=\"item result app c\">\n        ";
t_15 += runtime.suppressValue((lineno = 48, colno = 20, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "market_tile"), "market_tile", [t_19,runtime.makeKeywordArgs({"link": true,"force_button": true,"src": runtime.contextOrFrameLookup(context, frame, "sort")})])), env.autoesc);
t_15 += "\n      </li>\n    ";
}
frame = frame.pop();
t_15 += "\n\n    ";
t_15 += "\n    ";
if(runtime.memberLookup((runtime.memberLookup((runtime.contextOrFrameLookup(context, frame, "response")),"meta", env.autoesc)),"next", env.autoesc)) {
t_15 += "\n      ";
t_15 += runtime.suppressValue((lineno = 54, colno = 18, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "more_button"), "more_button", [runtime.memberLookup((runtime.memberLookup((runtime.contextOrFrameLookup(context, frame, "response")),"meta", env.autoesc)),"next", env.autoesc)])), env.autoesc);
t_15 += "\n    ";
}
t_15 += "\n  </ol>\n";
return t_15;
}
,function() {var t_20 = "";t_20 += "\n  <p class=\"spinner padded alt\"></p>\n";
return t_20;
}
,function() {var t_21 = "";t_21 += "\n  <p class=\"no-results\">\n    ";
t_21 += runtime.suppressValue((lineno = 61, colno = 6, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "_"), "_", ["No apps in this category"])), env.autoesc);
t_21 += "\n  </p>\n";
return t_21;
}
,function() {var t_22 = "";t_22 += "\n  <p class=\"no-results\">\n    ";
t_22 += "\n    ";
t_22 += runtime.suppressValue((lineno = 66, colno = 6, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "_"), "_", ["No apps in this category, try again later"])), env.autoesc);
t_22 += "\n  </p>\n";
return t_22;
}
), env.autoesc);
output += "\n</section>\n";
return output;
} catch (e) {
  runtime.handleError(e, lineno, colno);
}
}
return {
root: root
};
})();
templates["debug.html"] = (function() {function root(env, context, frame, runtime) {
var lineno = null;
var colno = null;
var output = "";
try {
output += "<section class=\"main infobox\">\n  <div>\n    <style>\n      dt {\n        clear: left;\n        float: left;\n      }\n      dd {\n        float: left;\n      }\n    </style>\n    <h2>Debug</h2>\n    <p>\n      <button id=\"toggle-debug\">Debug Mode: <b id=\"debug-status\">";
output += runtime.suppressValue(runtime.contextOrFrameLookup(context, frame, "dbg"), env.autoesc);
output += "</b></button>\n    </p>\n\n    <dl class=\"settings c\">\n      ";
frame = frame.push();
var t_2 = (lineno = 17, colno = 36, runtime.callWrap(runtime.memberLookup((runtime.contextOrFrameLookup(context, frame, "settings")),"items", env.autoesc), "settings[\"items\"]", []));
for(var t_1=0; t_1 < t_2.length; t_1++) {
var t_3 = t_2[t_1];
frame.set("setting", t_3);
output += "\n        <dt>";
output += runtime.suppressValue(runtime.memberLookup((t_3),0, env.autoesc), env.autoesc);
output += "</dt>\n        <dd>";
output += runtime.suppressValue(runtime.memberLookup((t_3),1, env.autoesc) || "––", env.autoesc);
output += "</dd>\n      ";
}
frame = frame.pop();
output += "\n    </dl>\n\n    <dl class=\"capabilities c\">\n      ";
frame = frame.push();
var t_5 = (lineno = 24, colno = 36, runtime.callWrap(runtime.memberLookup((runtime.contextOrFrameLookup(context, frame, "capabilities")),"items", env.autoesc), "capabilities[\"items\"]", []));
for(var t_4=0; t_4 < t_5.length; t_4++) {
var t_6 = t_5[t_4];
frame.set("cap", t_6);
output += "\n        <dt>";
output += runtime.suppressValue(runtime.memberLookup((t_6),0, env.autoesc), env.autoesc);
output += "</dt>\n        <dd>";
output += runtime.suppressValue(runtime.memberLookup((t_6),1, env.autoesc), env.autoesc);
output += "</dd>\n      ";
}
frame = frame.pop();
output += "\n      <dt>Feature Profile</dt>\n      <dd>";
output += runtime.suppressValue(runtime.contextOrFrameLookup(context, frame, "profile"), env.autoesc);
output += "</dd>\n    </dl>\n\n    <h3>Cache</h3>\n\n    <pre id=\"cache-inspector\"></pre>\n\n    <ul class=\"cache-menu\">\n      ";
frame = frame.push();
var t_8 = (lineno = 37, colno = 26, runtime.callWrap(runtime.memberLookup((runtime.contextOrFrameLookup(context, frame, "cache")),"keys", env.autoesc), "cache[\"keys\"]", []));
for(var t_7=0; t_7 < t_8.length; t_7++) {
var t_9 = t_8[t_7];
frame.set("k", t_9);
output += "\n        <li><a href=\"#\" data-url=\"";
output += runtime.suppressValue(t_9, env.autoesc);
output += "\">";
output += runtime.suppressValue(env.getFilter("urlparams")(t_9,runtime.makeKeywordArgs({"_user": "REDACTED"})), env.autoesc);
output += "</a></li>\n      ";
}
frame = frame.pop();
output += "\n    </ul>\n  </div>\n</section>\n";
return output;
} catch (e) {
  runtime.handleError(e, lineno, colno);
}
}
return {
root: root
};
})();
templates["detail/abuse.html"] = (function() {function root(env, context, frame, runtime) {
var lineno = null;
var colno = null;
var output = "";
try {
var includeTemplate = env.getTemplate("_macros/forms.html");
output += includeTemplate.render(context.getVariables(), frame.push());
output += "\n\n<div class=\"main report-abuse modal c\">\n  <div>\n    <div class=\"secondary-header\">\n      <h2>";
output += runtime.suppressValue((lineno = 5, colno = 12, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "_"), "_", ["Report Abuse"])), env.autoesc);
output += "</h2>\n      <a href=\"#\" class=\"close btn-cancel\">";
output += runtime.suppressValue((lineno = 6, colno = 45, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "_"), "_", ["Close"])), env.autoesc);
output += "</a>\n    </div>\n    <form method=\"post\" class=\"abuse-form form-modal\" data-action=\"";
output += runtime.suppressValue((lineno = 8, colno = 71, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "api"), "api", ["app_abuse"])), env.autoesc);
output += "\">\n      <p class=\"brform simple-field c\">\n        <textarea name=\"text\" required></textarea>\n      </p>\n      <p class=\"form-footer\">\n        ";
output += runtime.suppressValue((lineno = 13, colno = 23, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "potato_captcha"), "potato_captcha", [])), env.autoesc);
output += "\n        <input type=\"hidden\" name=\"app\" value=\"";
output += runtime.suppressValue(runtime.contextOrFrameLookup(context, frame, "slug"), env.autoesc);
output += "\">\n        <button type=\"submit\">";
output += runtime.suppressValue((lineno = 15, colno = 32, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "_"), "_", ["Send Report"])), env.autoesc);
output += "</button>\n      </p>\n    </form>\n  </div>\n</div>\n";
return output;
} catch (e) {
  runtime.handleError(e, lineno, colno);
}
}
return {
root: root
};
})();
templates["detail/main.html"] = (function() {function root(env, context, frame, runtime) {
var lineno = null;
var colno = null;
var output = "";
try {
var includeTemplate = env.getTemplate("_macros/emaillink.html");
output += includeTemplate.render(context.getVariables(), frame.push());
output += "\n";
var includeTemplate = env.getTemplate("_macros/market_tile.html");
output += includeTemplate.render(context.getVariables(), frame.push());
output += "\n";
var includeTemplate = env.getTemplate("_macros/rating.html");
output += includeTemplate.render(context.getVariables(), frame.push());
output += "\n";
var includeTemplate = env.getTemplate("_macros/stars.html");
output += includeTemplate.render(context.getVariables(), frame.push());
output += "\n\n";
var t_1 = (lineno = 5, colno = 19, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "api"), "api", ["app",[runtime.contextOrFrameLookup(context, frame, "slug")]]));
frame.set("endpoint", t_1);
if(!frame.parent) {
context.setVariable("endpoint", t_1);
context.addExport("endpoint");
}
output += "\n\n<div class=\"detail\" itemscope itemtype=\"http://schema.org/SoftwareApplication\">\n<section class=\"main product-details listing expanded c\">\n  ";
output += runtime.suppressValue(env.getExtension("defer")["run"](context,runtime.makeKeywordArgs({"url": t_1,"as": "app","key": runtime.contextOrFrameLookup(context, frame, "slug"),"id": "app-data"}),function() {var t_2 = "";t_2 += "\n    ";
t_2 += runtime.suppressValue((lineno = 10, colno = 16, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "market_tile"), "market_tile", [runtime.contextOrFrameLookup(context, frame, "this")])), env.autoesc);
t_2 += "\n  ";
return t_2;
}
,function() {var t_3 = "";t_3 += "\n    <div class=\"product mkt-tile\">\n      <div class=\"info\">\n        <h3>";
t_3 += runtime.suppressValue((lineno = 14, colno = 14, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "_"), "_", ["Loading..."])), env.autoesc);
t_3 += "</h3>\n        <div class=\"price vital\">";
t_3 += runtime.suppressValue((lineno = 15, colno = 35, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "_"), "_", ["Loading..."])), env.autoesc);
t_3 += "</div>\n        <div class=\"rating vital unrated\">\n          ";
t_3 += runtime.suppressValue((lineno = 17, colno = 16, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "stars"), "stars", [0])), env.autoesc);
t_3 += "\n        </div>\n      </div>\n    </div>\n    <div class=\"tray previews full\"></div>\n  ";
return t_3;
}
,null,function() {var t_4 = "";t_4 += "\n    <div>\n      <h2>";
t_4 += runtime.suppressValue((lineno = 24, colno = 12, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "_"), "_", ["Oh no!"])), env.autoesc);
t_4 += "</h2>\n      <p>";
t_4 += runtime.suppressValue((lineno = 25, colno = 11, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "_"), "_", ["The page you were looking for was not found."])), env.autoesc);
t_4 += "</p>\n    </div>\n  ";
return t_4;
}
), env.autoesc);
output += "\n</section>\n\n<section class=\"main\" id=\"installed\">\n  <div>\n    <p>\n      ";
output += runtime.suppressValue((lineno = 33, colno = 8, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "_"), "_", ["Installed!"])), env.autoesc);
output += "\n    </p>\n    <p class=\"how mac\">\n      ";
output += runtime.suppressValue((lineno = 36, colno = 8, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "_"), "_", ["Launch this app from your <b>Applications</b> directory."])), env.autoesc);
output += "\n    </p>\n    <p class=\"how windows\">\n      ";
output += runtime.suppressValue((lineno = 39, colno = 8, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "_"), "_", ["Launch this app from your <b>Windows desktop</b> or <b>Start &#9658; All Programs</b>."])), env.autoesc);
output += "\n    </p>\n    <p class=\"how linux\">\n      ";
output += runtime.suppressValue((lineno = 42, colno = 8, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "_"), "_", ["Launch this app from your <b>dash</b>, <b>Application picker</b>, or <b>Applications menu</b>."])), env.autoesc);
output += "\n    </p>\n  </div>\n</section>\n<div id=\"purchased-message\"></div>\n\n<section class=\"main blurbs prose infobox\">\n  <div>\n    ";
output += runtime.suppressValue(env.getExtension("defer")["run"](context,runtime.makeKeywordArgs({"url": t_1,"as": "app","key": runtime.contextOrFrameLookup(context, frame, "slug")}),function() {var t_5 = "";t_5 += "\n      ";
var t_6 = runtime.memberLookup((runtime.memberLookup((runtime.contextOrFrameLookup(context, frame, "this")),"summary", env.autoesc)),"length", env.autoesc) + runtime.memberLookup((runtime.contextOrFrameLookup(context, frame, "description")),"length", env.autoesc) > 700;
frame.set("super_long", t_6);
if(!frame.parent) {
context.setVariable("super_long", t_6);
context.addExport("super_long");
}
t_5 += "\n      <p class=\"summary\" itemprop=\"description\">\n        ";
t_5 += runtime.suppressValue(env.getFilter("nl2br")(runtime.memberLookup((runtime.contextOrFrameLookup(context, frame, "this")),"summary", env.autoesc)), env.autoesc);
t_5 += "\n        ";
if(t_6) {
t_5 += "\n          <a href=\"#\" class=\"show-toggle\" data-toggle-text=\"";
t_5 += runtime.suppressValue((lineno = 55, colno = 62, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "_"), "_", ["Less&hellip;"])), env.autoesc);
t_5 += "\">";
t_5 += runtime.suppressValue((lineno = 55, colno = 83, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "_"), "_", ["More&hellip;"])), env.autoesc);
t_5 += "</a>\n        ";
}
t_5 += "\n      </p>\n\n      ";
if(runtime.memberLookup((runtime.memberLookup((runtime.contextOrFrameLookup(context, frame, "this")),"description", env.autoesc)),"length", env.autoesc) || runtime.memberLookup((runtime.contextOrFrameLookup(context, frame, "this")),"is_packaged", env.autoesc)) {
t_5 += "\n        <div";
if(t_6) {
t_5 += " class=\"collapsed\"";
}
t_5 += ">\n          ";
if(runtime.memberLookup((runtime.memberLookup((runtime.contextOrFrameLookup(context, frame, "this")),"description", env.autoesc)),"length", env.autoesc)) {
t_5 += "\n            <h3>";
t_5 += runtime.suppressValue((lineno = 62, colno = 18, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "_"), "_", ["Description"])), env.autoesc);
t_5 += "</h3>\n            <div class=\"description\">";
t_5 += runtime.suppressValue(env.getFilter("nl2br")(runtime.memberLookup((runtime.contextOrFrameLookup(context, frame, "this")),"description", env.autoesc)), env.autoesc);
t_5 += "</div>\n          ";
}
t_5 += "\n          ";
if(runtime.memberLookup((runtime.contextOrFrameLookup(context, frame, "this")),"is_packaged", env.autoesc)) {
t_5 += "\n            <h3>";
t_5 += runtime.suppressValue((lineno = 66, colno = 18, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "_"), "_", ["Version"])), env.autoesc);
t_5 += "</h3>\n            <div class=\"package-version\">\n              ";
t_5 += runtime.suppressValue((lineno = 68, colno = 16, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "_"), "_", ["Latest version: {version}",runtime.makeKeywordArgs({"version": runtime.memberLookup((runtime.memberLookup((runtime.contextOrFrameLookup(context, frame, "this")),"current_version", env.autoesc)),"version", env.autoesc)})])), env.autoesc);
t_5 += "\n            </div>\n          ";
}
t_5 += "\n        </div>\n      ";
}
t_5 += "\n    ";
return t_5;
}
,function() {var t_7 = "";t_7 += "\n      <p class=\"spinner alt\"></p>\n    ";
return t_7;
}
,null,null), env.autoesc);
output += "\n  </div>\n</section>\n\n<section class=\"main reviews-wrapper c\">\n  <div class=\"reviews\">\n    ";
output += runtime.suppressValue(env.getExtension("defer")["run"](context,runtime.makeKeywordArgs({"url": (lineno = 82, colno = 25, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "apiParams"), "apiParams", ["reviews",{"app": runtime.contextOrFrameLookup(context, frame, "slug")}])),"id": "ratings"}),function() {var t_8 = "";t_8 += "\n      <h3>";
t_8 += runtime.suppressValue((lineno = 83, colno = 12, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "_"), "_", ["Reviews"])), env.autoesc);
t_8 += "</h3>\n      ";
if(runtime.memberLookup((runtime.memberLookup((runtime.contextOrFrameLookup(context, frame, "this")),"meta", env.autoesc)),"total_count", env.autoesc)) {
t_8 += "\n        <ul class=\"ratings-placeholder-inner\">\n          ";
frame = frame.push();
var t_10 = (lineno = 86, colno = 40, runtime.callWrap(runtime.memberLookup((runtime.memberLookup((runtime.contextOrFrameLookup(context, frame, "this")),"objects", env.autoesc)),"slice", env.autoesc), "this[\"objects\"][\"slice\"]", [0,2]));
for(var t_9=0; t_9 < t_10.length; t_9++) {
var t_11 = t_10[t_9];
frame.set("rat", t_11);
t_8 += "\n            ";
t_8 += runtime.suppressValue((lineno = 87, colno = 19, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "rating"), "rating", [t_11,runtime.makeKeywordArgs({"detailpage": true})])), env.autoesc);
t_8 += "\n          ";
}
frame = frame.pop();
t_8 += "\n        </ul>\n        <div class=\"";
t_8 += runtime.suppressValue((!runtime.memberLookup((runtime.memberLookup((runtime.contextOrFrameLookup(context, frame, "this")),"user", env.autoesc)),"developed", env.autoesc)?"split":"full"), env.autoesc);
t_8 += "\">\n          <a class=\"button alt average-rating\" href=\"";
t_8 += runtime.suppressValue((lineno = 91, colno = 57, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "url"), "url", ["app/ratings",[runtime.contextOrFrameLookup(context, frame, "slug")]])), env.autoesc);
t_8 += "\">\n            <span>\n              ";
t_8 += runtime.suppressValue((lineno = 93, colno = 22, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "_plural"), "_plural", ["{n} Review","{n} Reviews",runtime.makeKeywordArgs({"n": runtime.memberLookup((runtime.memberLookup((runtime.contextOrFrameLookup(context, frame, "this")),"meta", env.autoesc)),"total_count", env.autoesc)})])), env.autoesc);
t_8 += "\n            </span>\n            ";
t_8 += runtime.suppressValue((lineno = 96, colno = 18, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "stars"), "stars", [runtime.memberLookup((runtime.memberLookup((runtime.contextOrFrameLookup(context, frame, "this")),"info", env.autoesc)),"average", env.autoesc),runtime.makeKeywordArgs({"detailpage": true})])), env.autoesc);
t_8 += "\n          </a>\n        </div>\n      ";
}
else {
t_8 += "\n        <p class=\"not-rated\">\n          ";
t_8 += runtime.suppressValue((lineno = 101, colno = 12, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "_"), "_", ["App not yet rated"])), env.autoesc);
t_8 += "\n        </p>\n      ";
}
t_8 += "\n      ";
if(!(lineno = 104, colno = 28, runtime.callWrap(runtime.memberLookup((runtime.contextOrFrameLookup(context, frame, "user")),"logged_in", env.autoesc), "user[\"logged_in\"]", [])) || runtime.memberLookup((runtime.memberLookup((runtime.contextOrFrameLookup(context, frame, "this")),"user", env.autoesc)),"can_rate", env.autoesc) || runtime.memberLookup((runtime.memberLookup((runtime.contextOrFrameLookup(context, frame, "this")),"user", env.autoesc)),"has_rated", env.autoesc)) {
t_8 += "\n        <div class=\"";
t_8 += runtime.suppressValue((runtime.memberLookup((runtime.memberLookup((runtime.contextOrFrameLookup(context, frame, "this")),"objects", env.autoesc)),"length", env.autoesc)?"split":" full"), env.autoesc);
t_8 += "\">\n          ";
if((lineno = 106, colno = 28, runtime.callWrap(runtime.memberLookup((runtime.contextOrFrameLookup(context, frame, "user")),"logged_in", env.autoesc), "user[\"logged_in\"]", [])) && runtime.memberLookup((runtime.memberLookup((runtime.contextOrFrameLookup(context, frame, "this")),"user", env.autoesc)),"has_rated", env.autoesc)) {
t_8 += "\n            <a class=\"button alt\" id=\"edit-review\" href=\"";
t_8 += runtime.suppressValue((lineno = 107, colno = 61, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "url"), "url", ["app/ratings/edit",[runtime.contextOrFrameLookup(context, frame, "slug")]])), env.autoesc);
t_8 += "\">\n              ";
t_8 += runtime.suppressValue((lineno = 108, colno = 16, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "_"), "_", ["Edit Your Review"])), env.autoesc);
t_8 += "</a>\n          ";
}
else {
t_8 += "\n            <a class=\"button alt\" id=\"add-review\" href=\"#\"\n               data-action=\"add\" data-app=\"";
t_8 += runtime.suppressValue(runtime.contextOrFrameLookup(context, frame, "slug"), env.autoesc);
t_8 += "\">\n              ";
t_8 += runtime.suppressValue((lineno = 112, colno = 16, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "_"), "_", ["Write a Review"])), env.autoesc);
t_8 += "</a>\n          ";
}
t_8 += "\n        </div>\n      ";
}
t_8 += "\n\n    ";
return t_8;
}
,function() {var t_12 = "";t_12 += "\n      <p class=\"spinner alt padded\"></p>\n    ";
return t_12;
}
,null,function() {var t_13 = "";t_13 += "\n    ";
return t_13;
}
), env.autoesc);
output += "\n  </div>\n</section>\n\n<section class=\"main infobox support c\">\n  <div>\n    ";
output += runtime.suppressValue(env.getExtension("defer")["run"](context,runtime.makeKeywordArgs({"url": t_1,"as": "app","key": runtime.contextOrFrameLookup(context, frame, "slug")}),function() {var t_14 = "";t_14 += "\n      <ul class=\"c\">\n        ";
if(runtime.memberLookup((runtime.contextOrFrameLookup(context, frame, "this")),"support_email", env.autoesc)) {
t_14 += "\n          <li class=\"support-email\">\n            ";
t_14 += runtime.suppressValue((lineno = 130, colno = 22, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "emaillink"), "emaillink", [runtime.memberLookup((runtime.contextOrFrameLookup(context, frame, "this")),"support_email", env.autoesc),(lineno = 130, colno = 44, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "_"), "_", ["Support Email"])),runtime.makeKeywordArgs({"class": "button alt"})])), env.autoesc);
t_14 += "\n          </li>\n        ";
}
t_14 += "\n        ";
if(runtime.memberLookup((runtime.contextOrFrameLookup(context, frame, "this")),"support_url", env.autoesc)) {
t_14 += "\n          <li class=\"support-url\">\n            <a class=\"button alt\" rel=\"external\" ";
t_14 += runtime.suppressValue(env.getFilter("external_href")(runtime.memberLookup((runtime.contextOrFrameLookup(context, frame, "this")),"support_url", env.autoesc)), env.autoesc);
t_14 += ">\n              ";
t_14 += runtime.suppressValue((lineno = 136, colno = 16, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "_"), "_", ["Support Site"])), env.autoesc);
t_14 += "</a>\n          </li>\n        ";
}
t_14 += "\n        ";
if(runtime.memberLookup((runtime.contextOrFrameLookup(context, frame, "this")),"homepage", env.autoesc)) {
t_14 += "\n          <li class=\"homepage\">\n            <a class=\"button alt\" rel=\"external\" ";
t_14 += runtime.suppressValue(env.getFilter("external_href")(runtime.memberLookup((runtime.contextOrFrameLookup(context, frame, "this")),"homepage", env.autoesc)), env.autoesc);
t_14 += ">";
t_14 += runtime.suppressValue((lineno = 141, colno = 81, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "_"), "_", ["Homepage"])), env.autoesc);
t_14 += "</a>\n          </li>\n        ";
}
t_14 += "\n        ";
if(runtime.memberLookup((runtime.contextOrFrameLookup(context, frame, "this")),"privacy_policy", env.autoesc)) {
t_14 += "\n          <li class=\"privacy-policy\">\n            <a class=\"button alt\" href=\"";
t_14 += runtime.suppressValue((lineno = 146, colno = 44, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "url"), "url", ["app/privacy",[runtime.contextOrFrameLookup(context, frame, "slug")]])), env.autoesc);
t_14 += "\">\n            ";
t_14 += runtime.suppressValue((lineno = 147, colno = 14, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "_"), "_", ["Privacy Policy"])), env.autoesc);
t_14 += "</a>\n          </li>\n        ";
}
t_14 += "\n        ";
if(runtime.memberLookup((runtime.contextOrFrameLookup(context, frame, "this")),"public_stats", env.autoesc)) {
t_14 += "\n          <li><a class=\"button alt view-stats\" rel=\"external\" href=\"/statistics/app/";
t_14 += runtime.suppressValue(runtime.contextOrFrameLookup(context, frame, "slug"), env.autoesc);
t_14 += "/\">\n            ";
t_14 += runtime.suppressValue((lineno = 152, colno = 14, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "_"), "_", ["Statistics"])), env.autoesc);
t_14 += "</a></li>\n        ";
}
t_14 += "\n        <li class=\"abuse\">\n          <a class=\"button alt\" href=\"";
t_14 += runtime.suppressValue((lineno = 155, colno = 42, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "url"), "url", ["app/abuse",[runtime.contextOrFrameLookup(context, frame, "slug")]])), env.autoesc);
t_14 += "\">\n          ";
t_14 += runtime.suppressValue((lineno = 156, colno = 12, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "_"), "_", ["Report Abuse"])), env.autoesc);
t_14 += "</a>\n        </li>\n      </ul>\n      ";
if(runtime.memberLookup((runtime.contextOrFrameLookup(context, frame, "settings")),"payment_enabled", env.autoesc)) {
t_14 += "\n        ";
if(runtime.memberLookup((runtime.contextOrFrameLookup(context, frame, "this")),"upsell", env.autoesc)) {
t_14 += "\n          <a id=\"upsell\" class=\"button alt\"\n             href=\"";
t_14 += runtime.suppressValue(env.getFilter("urlparams")(runtime.memberLookup((runtime.memberLookup((runtime.contextOrFrameLookup(context, frame, "this")),"upsell", env.autoesc)),"url", env.autoesc),runtime.makeKeywordArgs({"src": "mkt-detail-upsell"})), env.autoesc);
t_14 += "\">\n             <span class=\"avail\">";
t_14 += runtime.suppressValue((lineno = 163, colno = 35, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "_"), "_", ["Premium version available"])), env.autoesc);
t_14 += "</span>\n             <img class=\"icon\" src=\"";
t_14 += runtime.suppressValue(runtime.memberLookup((runtime.memberLookup((runtime.contextOrFrameLookup(context, frame, "upsell")),"icons", env.autoesc)),16, env.autoesc), env.autoesc);
t_14 += "\">\n             <span class=\"name\">";
t_14 += runtime.suppressValue(runtime.memberLookup((runtime.memberLookup((runtime.contextOrFrameLookup(context, frame, "this")),"upsell", env.autoesc)),"name", env.autoesc), env.autoesc);
t_14 += "</span>\n          </a>\n        ";
}
t_14 += "\n      ";
}
t_14 += "\n    ";
return t_14;
}
,null,null,null), env.autoesc);
output += "\n  </div>\n</section>\n\n";
var includeTemplate = env.getTemplate("detail/abuse.html");
output += includeTemplate.render(context.getVariables(), frame.push());
output += "\n\n<div class=\"content_ratings\">\n  ";
output += runtime.suppressValue(env.getExtension("defer")["run"](context,runtime.makeKeywordArgs({"url": t_1,"as": "app","key": runtime.contextOrFrameLookup(context, frame, "slug")}),function() {var t_15 = "";t_15 += "\n    ";
if(runtime.memberLookup((runtime.contextOrFrameLookup(context, frame, "this")),"content_ratings", env.autoesc)) {
t_15 += "\n      <div class=\"content-ratings-wrapper main infobox c\">\n        <div>\n          <h3>\n            ";
t_15 += runtime.suppressValue((lineno = 181, colno = 14, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "_"), "_", ["Rating by the <a href=\"{dejus_url}\" title=\"{dejus}\">DEJUS</a>",runtime.makeKeywordArgs({"dejus_url": runtime.memberLookup((runtime.contextOrFrameLookup(context, frame, "settings")),"DEJUS_URL", env.autoesc),"dejus": runtime.memberLookup((runtime.contextOrFrameLookup(context, frame, "settings")),"DEJUS", env.autoesc)})])), env.autoesc);
t_15 += "\n          </h3>\n          <div class=\"content-ratings\">\n            ";
frame = frame.push();
var t_17 = (lineno = 186, colno = 54, runtime.callWrap(runtime.memberLookup((runtime.memberLookup((runtime.contextOrFrameLookup(context, frame, "this")),"content_ratings", env.autoesc)),"values", env.autoesc), "this[\"content_ra\"][\"values\"]", []));
for(var t_16=0; t_16 < t_17.length; t_16++) {
var t_18 = t_17[t_16];
frame.set("rating", t_18);
t_15 += "\n              <div class=\"content-rating c\">\n                <div class=\"icon icon-";
t_15 += runtime.suppressValue(runtime.memberLookup((t_18),"name", env.autoesc), env.autoesc);
t_15 += "\" title=\"";
t_15 += runtime.suppressValue(runtime.memberLookup((t_18),"name", env.autoesc), env.autoesc);
t_15 += "\">";
t_15 += runtime.suppressValue(runtime.memberLookup((t_18),"name", env.autoesc), env.autoesc);
t_15 += "</div>\n                <p class=\"description\">";
t_15 += runtime.suppressValue(runtime.memberLookup((t_18),"description", env.autoesc), env.autoesc);
t_15 += "</p>\n              </div>\n            ";
}
frame = frame.pop();
t_15 += "\n          </div>\n        </div>\n      </div>\n    ";
}
t_15 += "\n  ";
return t_15;
}
,null,null,null), env.autoesc);
output += "\n</div>\n\n</div>\n";
return output;
} catch (e) {
  runtime.handleError(e, lineno, colno);
}
}
return {
root: root
};
})();
templates["detail/preview_tray.html"] = (function() {function root(env, context, frame, runtime) {
var lineno = null;
var colno = null;
var output = "";
try {
output += "<div class=\"slider shots\">\n  <ul class=\"content\">";
output += runtime.suppressValue(env.getFilter("safe")(runtime.contextOrFrameLookup(context, frame, "previews")), env.autoesc);
output += "</ul>\n</div>\n<div class=\"dots\">";
output += runtime.suppressValue(env.getFilter("safe")(runtime.contextOrFrameLookup(context, frame, "dots")), env.autoesc);
output += "</div>\n";
return output;
} catch (e) {
  runtime.handleError(e, lineno, colno);
}
}
return {
root: root
};
})();
templates["detail/privacy.html"] = (function() {function root(env, context, frame, runtime) {
var lineno = null;
var colno = null;
var output = "";
try {
output += "<section class=\"app-privacy-policy main full c\">\n  ";
output += runtime.suppressValue(env.getExtension("defer")["run"](context,runtime.makeKeywordArgs({"url": (lineno = 1, colno = 17, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "api"), "api", ["app",[runtime.contextOrFrameLookup(context, frame, "slug")]])),"as": "app","key": runtime.contextOrFrameLookup(context, frame, "slug")}),function() {var t_1 = "";t_1 += "\n    <header class=\"secondary-header c\">\n      <h2>";
t_1 += runtime.suppressValue((lineno = 3, colno = 12, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "_"), "_", ["Privacy Policy: {app}",runtime.makeKeywordArgs({"app": runtime.memberLookup((runtime.contextOrFrameLookup(context, frame, "this")),"name", env.autoesc)})])), env.autoesc);
t_1 += "</h2>\n    </header>\n    <a href=\"";
t_1 += runtime.suppressValue((lineno = 5, colno = 17, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "url"), "url", ["app",[runtime.memberLookup((runtime.contextOrFrameLookup(context, frame, "this")),"slug", env.autoesc)]])), env.autoesc);
t_1 += "\" class=\"back-to-app\">";
t_1 += runtime.suppressValue((lineno = 5, colno = 62, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "_"), "_", ["Back to {app}",runtime.makeKeywordArgs({"app": runtime.memberLookup((runtime.contextOrFrameLookup(context, frame, "this")),"name", env.autoesc)})])), env.autoesc);
t_1 += "</a>\n    <article class=\"prose\">\n      ";
t_1 += runtime.suppressValue(env.getFilter("nl2br")(runtime.memberLookup((runtime.contextOrFrameLookup(context, frame, "this")),"privacy_policy", env.autoesc)), env.autoesc);
t_1 += "\n    </article>\n  ";
return t_1;
}
,function() {var t_2 = "";t_2 += "\n    <article>\n      ";
t_2 += runtime.suppressValue((lineno = 11, colno = 8, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "_"), "_", ["Loading Privacy Policy..."])), env.autoesc);
t_2 += "\n    </article>\n  ";
return t_2;
}
,null,null), env.autoesc);
output += "\n</section>\n";
return output;
} catch (e) {
  runtime.handleError(e, lineno, colno);
}
}
return {
root: root
};
})();
templates["detail/single_preview.html"] = (function() {function root(env, context, frame, runtime) {
var lineno = null;
var colno = null;
var output = "";
try {
output += "<li itemscope itemtype=\"http://schema.org/ImageObject\">\n  <meta itemprop=\"caption\" content=\"";
output += runtime.suppressValue(runtime.contextOrFrameLookup(context, frame, "caption"), env.autoesc);
output += "\">\n  <a class=\"screenshot thumbnail ";
output += runtime.suppressValue(runtime.contextOrFrameLookup(context, frame, "typeclass"), env.autoesc);
output += "\"\n     href=\"";
output += runtime.suppressValue(runtime.contextOrFrameLookup(context, frame, "image_url"), env.autoesc);
output += "\" title=\"";
output += runtime.suppressValue(runtime.contextOrFrameLookup(context, frame, "caption"), env.autoesc);
output += "\">\n    <img alt=\"";
output += runtime.suppressValue(runtime.contextOrFrameLookup(context, frame, "caption"), env.autoesc);
output += "\" src=\"";
output += runtime.suppressValue(runtime.contextOrFrameLookup(context, frame, "thumbnail_url"), env.autoesc);
output += "\" draggable=\"false\" itemprop=\"contentURL\">\n  </a>\n</li>\n";
return output;
} catch (e) {
  runtime.handleError(e, lineno, colno);
}
}
return {
root: root
};
})();
templates["errors/fragment.html"] = (function() {function root(env, context, frame, runtime) {
var lineno = null;
var colno = null;
var output = "";
try {
output += "<span class=\"fragment-error\">\n<b>";
output += runtime.suppressValue((lineno = 1, colno = 5, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "_"), "_", ["Oh no!"])), env.autoesc);
output += "</b><br>\n";
output += runtime.suppressValue((lineno = 2, colno = 2, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "_"), "_", ["An error occurred."])), env.autoesc);
output += "\n</span>\n";
return output;
} catch (e) {
  runtime.handleError(e, lineno, colno);
}
}
return {
root: root
};
})();
templates["featured.html"] = (function() {function root(env, context, frame, runtime) {
var lineno = null;
var colno = null;
var output = "";
try {
var includeTemplate = env.getTemplate("_macros/market_tile.html");
output += includeTemplate.render(context.getVariables(), frame.push());
output += "\n\n<section id=\"search-results\" class=\"main full c\">\n  ";
output += runtime.suppressValue(env.getExtension("defer")["run"](context,runtime.makeKeywordArgs({"url": runtime.contextOrFrameLookup(context, frame, "endpoint"),"pluck": "featured","as": "app"}),function() {var t_1 = "";t_1 += "\n    <header class=\"secondary-header c\">\n      <h2>";
t_1 += runtime.suppressValue((lineno = 5, colno = 12, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "_"), "_", ["Featured"])), env.autoesc);
t_1 += "</h2>\n      <a href=\"#\" class=\"expand-toggle\" title=\"";
t_1 += runtime.suppressValue((lineno = 6, colno = 49, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "_"), "_", ["Expand"])), env.autoesc);
t_1 += "\"></a>\n    </header>\n    <ol class=\"container listing search-listing c\">\n      ";
frame = frame.push();
var t_3 = runtime.contextOrFrameLookup(context, frame, "this");
for(var t_2=0; t_2 < t_3.length; t_2++) {
var t_4 = t_3[t_2];
frame.set("result", t_4);
t_1 += "\n        <li class=\"item result app c\">\n          ";
t_1 += runtime.suppressValue((lineno = 11, colno = 22, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "market_tile"), "market_tile", [t_4,runtime.makeKeywordArgs({"link": true,"force_button": true,"src": "featured"})])), env.autoesc);
t_1 += "\n        </li>\n      ";
}
frame = frame.pop();
t_1 += "\n    </ol>\n  ";
return t_1;
}
,function() {var t_5 = "";t_5 += "\n    <p class=\"spinner alt\"></p>\n  ";
return t_5;
}
,function() {var t_6 = "";t_6 += "\n    <p class=\"no-results\">\n      ";
t_6 += runtime.suppressValue((lineno = 19, colno = 8, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "_"), "_", ["No featured apps found"])), env.autoesc);
t_6 += "\n    </p>\n  ";
return t_6;
}
,null), env.autoesc);
output += "\n</section>\n";
return output;
} catch (e) {
  runtime.handleError(e, lineno, colno);
}
}
return {
root: root
};
})();
templates["footer.html"] = (function() {function root(env, context, frame, runtime) {
var lineno = null;
var colno = null;
var output = "";
try {
output += "<div id=\"directory-footer\" class=\"main full c\">\n  <div class=\"group\">\n    <a class=\"button alt devhub\" href=\"/developers/\">";
output += runtime.suppressValue((lineno = 2, colno = 55, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "_"), "_", ["Develop Apps"])), env.autoesc);
output += "</a>\n  </div>\n  <div class=\"group links\">\n    <a href=\"/developers/\">";
output += runtime.suppressValue((lineno = 5, colno = 29, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "_"), "_", ["Developer Hub"])), env.autoesc);
output += "</a>\n    <a href=\"#\" class=\"submit-feedback\">";
output += runtime.suppressValue((lineno = 6, colno = 42, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "_"), "_", ["Feedback"])), env.autoesc);
output += "</a>\n    <a href=\"https://support.mozilla.org/products/marketplace\">";
output += runtime.suppressValue((lineno = 7, colno = 65, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "_"), "_", ["Support"])), env.autoesc);
output += "</a>\n  </div>\n  <div class=\"language group links\">\n    <a href=\"";
output += runtime.suppressValue((lineno = 10, colno = 17, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "url"), "url", ["settings"])), env.autoesc);
output += "\" class=\"region region-";
output += runtime.suppressValue((lineno = 10, colno = 70, runtime.callWrap(runtime.memberLookup((runtime.contextOrFrameLookup(context, frame, "user")),"get_setting", env.autoesc), "user[\"get_settin\"]", ["region"])), env.autoesc);
output += "\">\n      ";
output += runtime.suppressValue(runtime.memberLookup((runtime.contextOrFrameLookup(context, frame, "REGIONS")),(lineno = 11, colno = 31, runtime.callWrap(runtime.memberLookup((runtime.contextOrFrameLookup(context, frame, "user")),"get_setting", env.autoesc), "user[\"get_settin\"]", ["region"])), env.autoesc), env.autoesc);
output += "</a>\n  </div>\n</div>\n<div id=\"footer\">\n  <div class=\"pad\">\n    <h1 id=\"footzilla\"><a href=\"https://www.mozilla.org/\">mozilla</a></h1>\n    <p>\n      ";
output += runtime.suppressValue((lineno = 18, colno = 8, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "_"), "_", ["Except where otherwise <a href=\"{legal_url}\">noted</a>, content on this site is licensed under the <a href=\"{cc_url}\">Creative Commons Attribution Share-Alike License v3.0</a> or any later version.",runtime.makeKeywordArgs({"legal_url": "http://www.mozilla.org/about/legal.html#site","cc_url": "http://creativecommons.org/licenses/by-sa/3.0/"})])), env.autoesc);
output += "\n    </p>\n    <ul>\n      <li><a href=\"";
output += runtime.suppressValue((lineno = 23, colno = 23, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "url"), "url", ["privacy"])), env.autoesc);
output += "\">";
output += runtime.suppressValue((lineno = 23, colno = 39, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "_"), "_", ["Privacy Policy"])), env.autoesc);
output += "</a></li>\n      <li><a href=\"";
output += runtime.suppressValue((lineno = 24, colno = 23, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "url"), "url", ["terms"])), env.autoesc);
output += "\">";
output += runtime.suppressValue((lineno = 24, colno = 37, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "_"), "_", ["Terms of Use"])), env.autoesc);
output += "</a></li>\n      <li><a href=\"http://mozilla.com/legal/fraud-report/index.html\">\n        ";
output += runtime.suppressValue((lineno = 26, colno = 10, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "_"), "_", ["Report Trademark Abuse"])), env.autoesc);
output += "</a></li>\n    </ul>\n  </div>\n</div>\n";
return output;
} catch (e) {
  runtime.handleError(e, lineno, colno);
}
}
return {
root: root
};
})();
templates["header.html"] = (function() {function root(env, context, frame, runtime) {
var lineno = null;
var colno = null;
var output = "";
try {
output += "<nav role=\"navigation\">\n  <a href=\"#\" id=\"nav-back\" class=\"header-button icon back\" title=\"";
output += runtime.suppressValue((lineno = 1, colno = 69, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "_"), "_", ["Back"])), env.autoesc);
output += "\"><b>";
output += runtime.suppressValue((lineno = 1, colno = 85, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "_"), "_", ["Back"])), env.autoesc);
output += "</b></a>\n  <h1 class=\"site\"><a href=\"";
output += runtime.suppressValue((lineno = 2, colno = 32, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "url"), "url", ["homepage"])), env.autoesc);
output += "\"><span class=\"wordmark\">Firefox Marketplace</span></a></h1>\n  <span class=\"flex-shift\"></span>\n  <form novalidate method=\"GET\" id=\"search\" class=\"search\" action=\"";
output += runtime.suppressValue((lineno = 4, colno = 71, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "url"), "url", ["search"])), env.autoesc);
output += "\">\n    <label for=\"search-q\">";
output += runtime.suppressValue((lineno = 5, colno = 28, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "_"), "_", ["Search"])), env.autoesc);
output += "</label>\n    <div id=\"site-search-suggestions\" data-src=\"\"></div>\n    <input id=\"search-q\" class=\"query-input\" type=\"search\" name=\"q\" title=\"\"\n         autocomplete=\"off\" placeholder=\"";
output += runtime.suppressValue((lineno = 8, colno = 43, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "_"), "_", ["Search"])), env.autoesc);
output += "\" required\n         value=\"";
output += runtime.suppressValue(runtime.memberLookup((runtime.memberLookup((runtime.contextOrFrameLookup(context, frame, "z")),"context", env.autoesc)),"search", env.autoesc) || "", env.autoesc);
output += "\">\n    <a href=\"#\" class=\"close search-clear\" title=\"";
output += runtime.suppressValue((lineno = 10, colno = 52, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "_"), "_", ["Clear"])), env.autoesc);
output += "\">";
output += runtime.suppressValue((lineno = 10, colno = 66, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "_"), "_", ["Clear"])), env.autoesc);
output += "</a>\n  </form>\n  <span class=\"flex-span\"></span>\n  <div class=\"act-tray\">\n    <a href=\"";
output += runtime.suppressValue((lineno = 14, colno = 17, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "url"), "url", ["settings"])), env.autoesc);
output += "\" class=\"header-button icon settings\" title=\"";
output += runtime.suppressValue((lineno = 14, colno = 77, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "_"), "_", ["Settings"])), env.autoesc);
output += "\"></a>\n    <div class=\"account-links only-logged-in\">\n      <ul>\n        <li>\n          <a href=\"";
output += runtime.suppressValue((lineno = 18, colno = 23, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "url"), "url", ["settings"])), env.autoesc);
output += "\">\n            <b>";
output += runtime.suppressValue((lineno = 19, colno = 32, runtime.callWrap(runtime.memberLookup((runtime.contextOrFrameLookup(context, frame, "user")),"get_setting", env.autoesc), "user[\"get_settin\"]", ["email"])), env.autoesc);
output += "</b>\n            ";
output += runtime.suppressValue((lineno = 20, colno = 14, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "_"), "_", ["Edit Account Settings"])), env.autoesc);
output += "</a>\n        </li>\n        <li><a href=\"";
output += runtime.suppressValue((lineno = 22, colno = 25, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "url"), "url", ["purchases"])), env.autoesc);
output += "\">";
output += runtime.suppressValue((lineno = 22, colno = 43, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "_"), "_", ["My Apps"])), env.autoesc);
output += "</a></li>\n        <li><a class=\"submit-feedback\" href=\"#\">";
output += runtime.suppressValue((lineno = 23, colno = 50, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "_"), "_", ["Feedback"])), env.autoesc);
output += "</a></li>\n        <li><a href=\"#\" class=\"logout\">";
output += runtime.suppressValue((lineno = 24, colno = 41, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "_"), "_", ["Sign Out"])), env.autoesc);
output += "</a></li>\n      </ul>\n    </div>\n  </div>\n  <a href=\"#\" class=\"header-button persona\">";
output += runtime.suppressValue((lineno = 28, colno = 46, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "_"), "_", ["Sign In"])), env.autoesc);
output += "</a>\n</nav>\n";
return output;
} catch (e) {
  runtime.handleError(e, lineno, colno);
}
}
return {
root: root
};
})();
templates["home/main.html"] = (function() {function root(env, context, frame, runtime) {
var lineno = null;
var colno = null;
var output = "";
try {
var includeTemplate = env.getTemplate("_macros/market_tile.html");
output += includeTemplate.render(context.getVariables(), frame.push());
output += "\n";
var t_1 = (lineno = 1, colno = 19, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "api"), "api", ["homepage"]));
frame.set("endpoint", t_1);
if(!frame.parent) {
context.setVariable("endpoint", t_1);
context.addExport("endpoint");
}
output += "\n\n<section id=\"featured-home\" class=\"featured full\">\n  ";
output += runtime.suppressValue(env.getExtension("defer")["run"](context,runtime.makeKeywordArgs({"url": t_1,"pluck": "featured","as": "app"}),function() {var t_2 = "";t_2 += "\n    <ul class=\"grid c\">\n      ";
frame = frame.push();
var t_4 = runtime.contextOrFrameLookup(context, frame, "this");
for(var t_3=0; t_3 < t_4.length; t_3++) {
var t_5 = t_4[t_3];
frame.set("app", t_5);
t_2 += "\n        <li>";
t_2 += runtime.suppressValue((lineno = 7, colno = 24, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "market_tile"), "market_tile", [t_5,runtime.makeKeywordArgs({"link": true,"src": "mkt-home"})])), env.autoesc);
t_2 += "</li>\n      ";
}
frame = frame.pop();
t_2 += "\n    </ul>\n  ";
return t_2;
}
,function() {var t_6 = "";t_6 += "\n    <p class=\"spinner spaced\"></p>\n  ";
return t_6;
}
,null,null), env.autoesc);
output += "\n</section>\n<section class=\"main categories\">\n  <h2>";
output += runtime.suppressValue((lineno = 15, colno = 8, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "_"), "_", ["Categories"])), env.autoesc);
output += "</h2>\n  ";
output += runtime.suppressValue(env.getExtension("defer")["run"](context,runtime.makeKeywordArgs({"url": t_1,"pluck": "categories"}),function() {var t_7 = "";t_7 += "\n    <ul class=\"grid\">\n      ";
frame = frame.push();
var t_9 = runtime.contextOrFrameLookup(context, frame, "this");
for(var t_8=0; t_8 < t_9.length; t_8++) {
var t_10 = t_9[t_8];
frame.set("category", t_10);
t_7 += "\n        <li>\n          <a class=\"mkt-tile category\"\n             href=\"";
t_7 += runtime.suppressValue((lineno = 21, colno = 23, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "url"), "url", ["category",[runtime.memberLookup((t_10),"slug", env.autoesc)]])), env.autoesc);
t_7 += "\"\n             data-params=\"";
t_7 += runtime.suppressValue(env.getFilter("escape")(env.getFilter("stringify")({"name": runtime.memberLookup((t_10),"name", env.autoesc)})), env.autoesc);
t_7 += "\">\n            <div class=\"icon cat-";
t_7 += runtime.suppressValue(runtime.memberLookup((t_10),"slug", env.autoesc), env.autoesc);
t_7 += "\"></div>\n            <h3 class=\"linefit\">";
t_7 += runtime.suppressValue(runtime.memberLookup((t_10),"name", env.autoesc), env.autoesc);
t_7 += "</h3>\n          </a>\n        </li>\n      ";
}
frame = frame.pop();
t_7 += "\n    </ul>\n  ";
return t_7;
}
,function() {var t_11 = "";t_11 += "\n    <p class=\"spinner alt spaced\"></p>\n  ";
return t_11;
}
,null,null), env.autoesc);
output += "\n</section>\n";
return output;
} catch (e) {
  runtime.handleError(e, lineno, colno);
}
}
return {
root: root
};
})();
templates["not_found.html"] = (function() {function root(env, context, frame, runtime) {
var lineno = null;
var colno = null;
var output = "";
try {
output += "<section class=\"main infobox\">\n    <div>\n        <h2>";
output += runtime.suppressValue((lineno = 2, colno = 14, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "_"), "_", ["Oh no!"])), env.autoesc);
output += "</h2>\n        <p>";
output += runtime.suppressValue((lineno = 3, colno = 13, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "_"), "_", ["The page you were looking for was not found."])), env.autoesc);
output += "</p>\n    </div>\n</section>\n";
return output;
} catch (e) {
  runtime.handleError(e, lineno, colno);
}
}
return {
root: root
};
})();
templates["privacy.html"] = (function() {function root(env, context, frame, runtime) {
var lineno = null;
var colno = null;
var output = "";
try {
output += "<section class=\"site-privacy-policy main full c\">\n  <header class=\"secondary-header c\">\n    <h2>";
output += runtime.suppressValue((lineno = 2, colno = 10, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "_"), "_", ["Privacy Policy"])), env.autoesc);
output += "</h2>\n  </header>\n  <article class=\"prose\">\n    <p>Note: The proposed full version of the Privacy Policy for the Firefox Marketplace is currently under review and comment on our <a target=\"_blank\" href=\"http://groups.google.com/group/mozilla.governance/topics\">governance mailing list</a>.</p>\n    <p>When the Firefox Marketplace is fully launched, we will ask for your consent to the final Privacy Policy.</p>\n\n    <h3>Firefox Marketplace Privacy Policy</h3>\n    <p>February 23, 2012</p>\n\n    <p>The Firefox Marketplace is a publicly available market maintained by Mozilla that allows developers to distribute their Apps (applications written using open web technologies that can run on multiple platforms) or Add-ons (extensions and themes that allow you to extend the functionality of the Firefox browser) to users for use on any device that can access the open web. &nbsp;This policy describes how Mozilla deals with any info we get with respect to the Firefox Marketplace. We have separate privacy policies for our other products and services.</p>\n\n    <h3>What we consider to be personal information</h3>\n    <p>We consider &quot;personal information&quot; to mean either information which identifies you, like your name or email address; or a combination of several pieces of information which couldn&#39;t identify you on their own, but which could become identifiable to you when put together.</p>\n    <p>Also, if we store personal information with other information that is not personal, we consider the combination to be personal information.</p>\n\n    <h3>How we collect information about you</h3>\n    <p>There are four ways we collect information about you:</p>\n    <ol>\n      <li>You give it to us directly, perhaps through a form (like when you sign up to receive our Marketplace email newsletter updates or when you purchase an App or Add-on);</li>\n      <li>We collect it automatically (like your IP address when your browser makes requests to our web servers);</li>\n      <li>Someone else tells us something about you (like when a payment provider shares your email address after you make a purchase); or</li>\n      <li>We try and understand more about you based on information you&#39;ve already given us (like suggesting what Apps you might be interested in based on your purchase history).</li>\n    </ol>\n\n    <blockquote>\n      <h4>Some specifics</h4>\n      <p>The Firefox Marketplace uses cookies to help Mozilla identify and track visitors, their usage of Firefox Marketplace, and their website access preferences across multiple requests and visits to the Firefox Marketplace in order for us to understand how users use the Firefox Marketplace and to make your experience better. You can opt-out of this practice by following the instructions <a href=\"http://www.mozilla.org/en-US/opt-out.html\">here</a>.</p>\n      <p>When you log in with Persona to the Firefox Marketplace, the Persona service sends us your email address. You can browse the Firefox Marketplace without logging in to Persona, however, you cannot install an App or purchase an Add-on without logging into the Firefox Marketplace with Persona. If you have an existing Mozilla Add-ons account, you will be prompted to sign in with a Persona account before you can install an App or purchase an Add-on.</p>\n      <p>Firefox sends daily messages to Mozilla with metadata that helps ensure that you have the latest updates when you install an Add-on. Please see the <a href=\"http://www.mozilla.org/en-US/legal/privacy/firefox.html\">Firefox Privacy Policy</a> for more information on our Automated Update Service. You can opt out of these messages by following the instructions <a href=\"https://blog.mozilla.com/addons/how-to-opt-out-of-add-on-metadata-updates/\">here</a>.</p>\n      <p>We collect the search terms you enter to find Apps or Add-ons and your interactions with the various parts of the Marketplace to better understand, in the aggregate, how users interact with the Firefox Marketplace. We don&rsquo;t tie this information to your Persona account.</p>\n    </blockquote>\n\n    <h3>What we will do with your info</h3>\n    <p>We use your information to help us provide better products and services to you. When you give us personal information, we will use it in the manner to which you consent.</p>\n\n    <blockquote>\n      <h4>Some specifics</h4>\n      <p>We may use your email address to inform you of transactional messages from the Firefox Marketplace, and you may elect to receive additional communications from us. If you signed up to receive but no longer wish to receive electronic marketing communications from Mozilla about the Firefox Marketplace, you can opt-out from receiving these communications by following the &ldquo;unsubscribe&rdquo; instructions in any such communication you receive. You can manage the email and notification settings for Mozilla-sent email in your Marketplace Profile.</p>\n      <p>If you write App or Add-on reviews, create a collection, or create other content in the Firefox Marketplace, your display name or username will be displayed publicly.</p>\n      <p>You may optionally fill in details of your public user profile, such as a homepage or profile picture, which will be displayed publicly.</p>\n      <p>If you purchase an App, we sign your receipt with the Persona user name (usually an email address) that you registered with the Firefox Marketplace through Persona. Apps you have installed may periodically communicate with Mozilla or an App developer for purposes of receipt/ownership verification, usage information, or other reasons as described in the individual App&rsquo;s privacy policy. You should check an App&rsquo;s privacy policy to make sure you are okay with their information handling practices before installing or using an App.</p>\n      <p>When you purchase an App or Add-on from a developer, they may receive information about you from your selected payment provider, as described in that payment provider&rsquo;s privacy policy.</p>\n      <p>We help you maintain a history of your transactional activity (like which Apps you have purchased). No financial information (such as credit card info that you have used to make purchases in the Firefox Marketplace) is collected, retained or used by Mozilla.</p>\n      <p>For an enhanced Marketplace experience, you may opt in to link your Marketplace account with your accounts on social networks. This is entirely optional and your accounts may be un-linked by you at any time. Once your account is un-linked, we do not continue to store or use information about your social graph or contacts from the social network you had linked. Individual Apps or Add-ons may allow you to link to your social network accounts and you should check the privacy policy of each App or Add-on to understand how they use your info.</p>\n      <p>If you ask us to send an App or Add-on to your phone, we will ask for your phone number and, with your permission, save it for future convenience. You may remove it by editing your Marketplace Profile.</p>\n      <p>If you are a developer who submits an App or Add-on to the Firefox Marketplace, we will ask for detailed information about your product that may be displayed publicly, unless otherwise noted. If you wish to use payments in your product, we will ask for your real legal name and address in order to validate your identity and manage the Firefox Marketplace.</p>\n      <p>Add-ons installed in Firefox and other Mozilla products may check for new versions of those Add-ons with the Firefox Marketplace each day. Additionally, Firefox may check for updates to other metadata related to Add-ons (e.g., updated descriptions, ratings, etc.) as described in the <a href=\"http://www.mozilla.org/en-US/legal/privacy/firefox.html\">Firefox Privacy Policy</a>. &nbsp;In aggregate, these update checks are used by Mozilla to determine the number of active users of an Add-on or App. You may opt out of the metadata transfer as described <a href=\"http://blog.mozilla.com/addons/how-to-opt-out-of-add-on-metadata-updates/\">here</a>, and Add-on updates as described <a href=\"http://blog.mozilla.com/addons/how-to-turn-off-add-on-updates/\">here</a>.</p>\n      <p>The Get Add-ons page of the Add-ons Manager in Firefox may include the Add-ons you have installed in order to provide relevant recommendations of other Add-ons to install, as described in the <a href=\"http://www.mozilla.org/en-US/legal/privacy/firefox.html\">Firefox Privacy Policy</a>. You may opt out of this as described <a href=\"http://blog.mozilla.com/addons/how-to-opt-out-of-add-on-metadata-updates/\">here</a>.</p>\n    </blockquote>\n\n    <h3>When we share your info</h3>\n    <p>Mozilla is an open organization, and we publish information that we think will make our products better or help foster an open web. Whenever we publish information about our users, we&#39;ll remove anything that we believe can identify you.</p>\n    <p>If we share your personal information, we only share it with employees, contractors and service providers who have contractually promised to handle or use the data in ways that are approved by Mozilla. If our corporate structure or status changes (e.g., if we restructure, are acquired, or go bankrupt) we&#39;ll pass on your information to a successor or affiliate.</p>\n\n    <blockquote>\n      <h4>Some specifics</h4>\n      <p>When you install a paid or free App, we send a digital receipt of that App to the developer of the App. This is to facilitate interactions between you and that developer as well as allow the developer to electronically authorize uses of the App. The digital receipt contains your Persona username (usually your email address) as well as other information. You can find a more detailed description of receipts and the information they contain <a href=\"https://wiki.mozilla.org/Apps/WebApplicationReceipt\">here</a>. &nbsp;Additionally, if you request support or a refund for an App or Add-on through the Marketplace, we give the developer your email address so they can reply to you. A developer&rsquo;s use of your email address or digital receipt is subject to their privacy policy. You should check an App&rsquo;s privacy policy to make sure you are okay with their information handling practices before installing or using an App.</p>\n      <p>We share non-personal aggregated statistics with developers on the usage of their software, such as platform (Windows, Android, etc.) and browser version information. We provide the information as a distribution of numbers and not tied to an email address, unique ID or other identifiable piece of information.</p>\n      <p>Mozilla does not currently process payments on its users behalf. When you make a purchase in the Marketplace, the information that you give to your selected payment provider is governed by that provider&rsquo;s privacy policy. &nbsp;A list of third-party vendors that are authorized payment processors for the Marketplace are available here.[Link TBD] &nbsp;Developers may also use their own payment providers &ndash; please check the privacy policy of any payment provider you use to make sure you are comfortable with their privacy practices.</p>\n      <p>A list of third party vendors that process information on Mozilla&rsquo;s behalf related to the Firefox Marketplace can be found here.[Link TBD]</p>\n    </blockquote>\n\n    <h3>How we store and protect your info</h3>\n    <p>We work hard to protect your information. We take steps to make sure that anyone (like an authorized employee or contractor) who sees your personal information has a good reason and is only allowed to do Mozilla-approved things with it.</p>\n    <p>Despite our efforts, we can&#39;t guarantee that malicious agents can&#39;t break in and access your data. If we find out about a security breach, we&#39;ll try hard to let you know so that you can take appropriate protective steps. We only keep information as long as we need to do the thing we collected it for. Once we don&#39;t need it any more, we&#39;ll destroy it unless we are forced by law to keep it longer.</p>\n\n    <h3>International Privacy</h3>\n    <p>Privacy laws and expectations vary from country to country. We&#39;re a global company and our computers are in several different places around the world. We also use service providers whose computers may also be in various countries. This means that any information we have about you might end up on one of those computers in another country, and that country may have a different level of data protection regulation than yours.</p>\n\n    <h3>Legal Process</h3>\n    <p>When a government agency or civil litigant asks for your personal info, we&#39;ll only give it to them if we have a good faith belief that:</p>\n    <ul>\n      <li>the law requires us to or,</li>\n      <li>it is reasonably necessary to do so to prevent harm to someone.</li>\n    </ul>\n    <p>We follow the law whenever we receive requests about you and we&#39;ll notify you any time we are asked to hand over your personal info like this unless we&#39;re legally prohibited from doing so, or circumstances require otherwise.</p>\n\n    <h3>Children</h3>\n    <p>Unless specifically stated otherwise, our services are not directed to individuals under the age of 13. If you are under 13, please do not provide us with your personally identifiable information. If you are the parent and believe that your child who is under 13 has provided us with personally identifiable information, please contact us here.</p>\n\n    <h3>Changes to this Policy and our Contact Information</h3>\n    <p>Sometimes, we change our privacy policies. When we do, we&#39;ll post a notice about the change on the Firefox Marketplace.</p>\n    <p>If you want to make a correction to your information, or you have any questions about our privacy policies, please get in touch with:</p>\n    <address>\n      Mozilla Corporation<br>\n      Attn: Legal Notices &mdash; Privacy<br>\n      650 Castro Street, Suite 300<br>\n      Mountain View, CA 94041-2072<br>\n      Phone: <a href=\"tel:6509030800\">+1-650-903-0800</a><br>\n      <a href=\"//www.mozilla.org/privacy/#contactus\">Send us an email</a>\n    </address>\n  </article>\n</section>\n";
return output;
} catch (e) {
  runtime.handleError(e, lineno, colno);
}
}
return {
root: root
};
})();
templates["ratings/edit.html"] = (function() {function root(env, context, frame, runtime) {
var lineno = null;
var colno = null;
var output = "";
try {
output += runtime.suppressValue(env.getExtension("defer")["run"](context,runtime.makeKeywordArgs({"url": (lineno = 0, colno = 21, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "apiParams"), "apiParams", ["reviews",runtime.makeKeywordArgs({"app": runtime.contextOrFrameLookup(context, frame, "slug"),"user": "mine"})])),"id": "main"}),function() {var t_1 = "";t_1 += "\n  ";
var t_2 = runtime.memberLookup((runtime.memberLookup((runtime.contextOrFrameLookup(context, frame, "this")),"objects", env.autoesc)),0, env.autoesc);
frame.set("this", t_2);
if(!frame.parent) {
context.setVariable("this", t_2);
context.addExport("this");
}
t_1 += "\n  <div class=\"main compose-review\">\n    <header class=\"secondary-header\">\n      <h2>";
t_1 += runtime.suppressValue((lineno = 4, colno = 12, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "_"), "_", ["Edit Review"])), env.autoesc);
t_1 += "</h2>\n    </header>\n    <form class=\"edit-review-form form-modal\" data-uri=\"";
t_1 += runtime.suppressValue(runtime.memberLookup((t_2),"resource_uri", env.autoesc), env.autoesc);
t_1 += "\" data-slug=\"";
t_1 += runtime.suppressValue(runtime.contextOrFrameLookup(context, frame, "slug"), env.autoesc);
t_1 += "\">\n      <p class=\"brform simple-field rating c\">\n        <label for=\"id_rating\">";
t_1 += runtime.suppressValue((lineno = 8, colno = 33, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "_"), "_", ["Rate:"])), env.autoesc);
t_1 += "</label>\n        <select name=\"rating\" id=\"id_rating\" required>\n          ";
frame = frame.push();
var t_4 = (lineno = 10, colno = 25, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "range"), "range", [1,6]));
for(var t_3=0; t_3 < t_4.length; t_3++) {
var t_5 = t_4[t_3];
frame.set("i", t_5);
t_1 += "\n            <option value=\"";
t_1 += runtime.suppressValue(t_5, env.autoesc);
t_1 += "\"";
t_1 += runtime.suppressValue((t_5 == runtime.memberLookup((t_2),"rating", env.autoesc)?" selected":""), env.autoesc);
t_1 += ">";
t_1 += runtime.suppressValue(t_5, env.autoesc);
t_1 += "</option>\n          ";
}
frame = frame.pop();
t_1 += "\n        </select>\n      </p>\n      <p class=\"brform simple-field c\">\n        <textarea id=\"id_body\" rows=\"2\" cols=\"40\" name=\"body\" required maxlength=\"150\">";
t_1 += runtime.suppressValue(runtime.memberLookup((t_2),"body", env.autoesc), env.autoesc);
t_1 += "</textarea>\n        <div class=\"char-count\" data-for=\"id_body\"></div>\n      </p>\n      <footer class=\"form-footer buttons c only-logged-in\">\n        <div class=\"two-up\"><a href=\"#\" class=\"alt cancel button\">";
t_1 += runtime.suppressValue((lineno = 20, colno = 68, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "_"), "_", ["Cancel"])), env.autoesc);
t_1 += "</a></div>\n        <div class=\"two-up\"><button type=\"submit\">";
t_1 += runtime.suppressValue((lineno = 21, colno = 52, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "_"), "_", ["Submit"])), env.autoesc);
t_1 += "</button></div>\n      </footer>\n      <footer class=\"form-footer c only-logged-out\">\n        <p>";
t_1 += runtime.suppressValue((lineno = 24, colno = 13, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "_"), "_", ["Only logged in users may edit reviews."])), env.autoesc);
t_1 += "</p>\n      </footer>\n    </form>\n  </div>\n";
return t_1;
}
,function() {var t_6 = "";t_6 += "\n  <p class=\"spinner alt\"></p>\n";
return t_6;
}
,null,null), env.autoesc);
output += "\n";
return output;
} catch (e) {
  runtime.handleError(e, lineno, colno);
}
}
return {
root: root
};
})();
templates["ratings/main.html"] = (function() {function root(env, context, frame, runtime) {
var lineno = null;
var colno = null;
var output = "";
try {
var includeTemplate = env.getTemplate("_macros/market_tile.html");
output += includeTemplate.render(context.getVariables(), frame.push());
output += "\n";
var includeTemplate = env.getTemplate("_macros/more_button.html");
output += includeTemplate.render(context.getVariables(), frame.push());
output += "\n";
var includeTemplate = env.getTemplate("_macros/rating.html");
output += includeTemplate.render(context.getVariables(), frame.push());
output += "\n\n<section class=\"main c\">\n  <header class=\"secondary-header c\">\n    <h2>";
output += runtime.suppressValue((lineno = 6, colno = 10, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "_"), "_", ["Reviews"])), env.autoesc);
output += "</h2>\n  </header>\n  ";
output += runtime.suppressValue(env.getExtension("defer")["run"](context,runtime.makeKeywordArgs({"url": (lineno = 8, colno = 23, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "apiParams"), "apiParams", ["reviews",{"app": runtime.contextOrFrameLookup(context, frame, "slug")}])),"pluck": "objects","id": "ratings","paginate": ".ratings-placeholder-inner"}),function() {var t_1 = "";t_1 += "\n    <p id=\"add-review\" class=\"primary-button\">\n      ";
if(runtime.memberLookup((runtime.memberLookup((runtime.contextOrFrameLookup(context, frame, "response")),"user", env.autoesc)),"has_rated", env.autoesc)) {
t_1 += "\n        <a class=\"button\" id=\"write-review\" href=\"";
t_1 += runtime.suppressValue((lineno = 11, colno = 54, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "url"), "url", ["app/ratings/edit",[runtime.contextOrFrameLookup(context, frame, "slug")]])), env.autoesc);
t_1 += "\">";
t_1 += runtime.suppressValue((lineno = 11, colno = 87, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "_"), "_", ["Edit Review"])), env.autoesc);
t_1 += "</a>\n      ";
}
else {
t_1 += "\n        <a class=\"button\" id=\"write-review\" href=\"";
t_1 += runtime.suppressValue((lineno = 13, colno = 54, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "url"), "url", ["app/ratings/add",[runtime.contextOrFrameLookup(context, frame, "slug")]])), env.autoesc);
t_1 += "\">";
t_1 += runtime.suppressValue((lineno = 13, colno = 86, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "_"), "_", ["Write a Review"])), env.autoesc);
t_1 += "</a>\n      ";
}
t_1 += "\n    </p>\n    <div class=\"reviews reviews-listing\">\n      <ul class=\"ratings-placeholder-inner\">\n        ";
frame = frame.push();
var t_3 = runtime.contextOrFrameLookup(context, frame, "this");
for(var t_2=0; t_2 < t_3.length; t_2++) {
var t_4 = t_3[t_2];
frame.set("rat", t_4);
t_1 += "\n          ";
t_1 += runtime.suppressValue((lineno = 19, colno = 17, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "rating"), "rating", [t_4])), env.autoesc);
t_1 += "\n        ";
}
frame = frame.pop();
t_1 += "\n\n        ";
t_1 += "\n        ";
if(runtime.memberLookup((runtime.memberLookup((runtime.contextOrFrameLookup(context, frame, "response")),"meta", env.autoesc)),"next", env.autoesc)) {
t_1 += "\n          ";
t_1 += runtime.suppressValue((lineno = 24, colno = 22, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "more_button"), "more_button", [runtime.memberLookup((runtime.memberLookup((runtime.contextOrFrameLookup(context, frame, "response")),"meta", env.autoesc)),"next", env.autoesc)])), env.autoesc);
t_1 += "\n        ";
}
t_1 += "\n      </ul>\n    </div>\n  ";
return t_1;
}
,null,function() {var t_5 = "";t_5 += "\n    <p class=\"no-results\">\n      ";
t_5 += runtime.suppressValue((lineno = 30, colno = 8, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "_"), "_", ["No results found"])), env.autoesc);
t_5 += "\n    </p>\n  ";
return t_5;
}
,null), env.autoesc);
output += "\n</section>\n";
return output;
} catch (e) {
  runtime.handleError(e, lineno, colno);
}
}
return {
root: root
};
})();
templates["ratings/report.html"] = (function() {function root(env, context, frame, runtime) {
var lineno = null;
var colno = null;
var output = "";
try {
output += "<div class=\"main report-spam modal\">\n  <header class=\"secondary-header\">\n    <h2>";
output += runtime.suppressValue((lineno = 2, colno = 10, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "_"), "_", ["Please select a reason:"])), env.autoesc);
output += "</h2>\n    <a href=\"#\" class=\"close btn-cancel\">";
output += runtime.suppressValue((lineno = 3, colno = 43, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "_"), "_", ["Cancel"])), env.autoesc);
output += "</a>\n  </header>\n  <ul class=\"menu alt\">\n    <li>\n      <a class=\"button alt\" href=\"#review_flag_reason_spam\">\n        ";
output += runtime.suppressValue((lineno = 8, colno = 10, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "_"), "_", ["Spam or otherwise non-review content"])), env.autoesc);
output += "\n      </a>\n    </li>\n    <li>\n      <a class=\"button alt\" href=\"#review_flag_reason_language\">\n        ";
output += runtime.suppressValue((lineno = 13, colno = 10, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "_"), "_", ["Inappropriate language/dialog"])), env.autoesc);
output += "\n      </a>\n    </li>\n    <li>\n      <a class=\"button alt\" href=\"#review_flag_reason_bug_support\">\n        ";
output += runtime.suppressValue((lineno = 18, colno = 10, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "_"), "_", ["Misplaced bug report or support request"])), env.autoesc);
output += "\n      </a>\n    </li>\n  </ul>\n  <footer>\n    <button class=\"button cancel fat\">";
output += runtime.suppressValue((lineno = 23, colno = 40, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "_"), "_", ["Cancel"])), env.autoesc);
output += "</button>\n  </footer>\n</div>\n";
return output;
} catch (e) {
  runtime.handleError(e, lineno, colno);
}
}
return {
root: root
};
})();
templates["ratings/write.html"] = (function() {function root(env, context, frame, runtime) {
var lineno = null;
var colno = null;
var output = "";
try {
output += "<div class=\"main compose-review modal\">\n  <header class=\"secondary-header\">\n    <h2>";
output += runtime.suppressValue((lineno = 2, colno = 10, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "_"), "_", ["Write a Review"])), env.autoesc);
output += "</h2>\n    <a href=\"#\" class=\"close btn-cancel\">";
output += runtime.suppressValue((lineno = 3, colno = 43, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "_"), "_", ["Cancel"])), env.autoesc);
output += "</a>\n  </header>\n  <form class=\"add-review-form form-modal\" data-app=\"";
output += runtime.suppressValue(runtime.contextOrFrameLookup(context, frame, "slug"), env.autoesc);
output += "\">\n    <p class=\"brform simple-field rating c\">\n      <label for=\"id_rating\">";
output += runtime.suppressValue((lineno = 7, colno = 31, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "_"), "_", ["Rate:"])), env.autoesc);
output += "</label>\n      <select name=\"rating\" id=\"id_rating\" required>\n          ";
frame = frame.push();
var t_2 = (lineno = 9, colno = 25, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "range"), "range", [1,6]));
for(var t_1=0; t_1 < t_2.length; t_1++) {
var t_3 = t_2[t_1];
frame.set("i", t_3);
output += "\n            <option value=\"";
output += runtime.suppressValue(t_3, env.autoesc);
output += "\">";
output += runtime.suppressValue(t_3, env.autoesc);
output += "</option>\n          ";
}
frame = frame.pop();
output += "\n      </select>\n    </p>\n    <p class=\"brform simple-field c\">\n      <textarea id=\"id_body\" rows=\"2\" cols=\"40\" name=\"body\" required maxlength=\"150\"></textarea>\n      <div class=\"char-count\" data-for=\"id_body\"></div>\n    </p>\n    <footer class=\"form-footer buttons c only-logged-in\">\n      <div class=\"two-up\"><a href=\"#\" class=\"alt cancel button\">";
output += runtime.suppressValue((lineno = 19, colno = 66, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "_"), "_", ["Cancel"])), env.autoesc);
output += "</a></div>\n      <div class=\"two-up\"><button type=\"submit\">";
output += runtime.suppressValue((lineno = 20, colno = 50, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "_"), "_", ["Submit"])), env.autoesc);
output += "</button></div>\n    </footer>\n    <footer class=\"form-footer c only-logged-out\">\n      <p>";
output += runtime.suppressValue((lineno = 23, colno = 11, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "_"), "_", ["Only logged in users may edit reviews."])), env.autoesc);
output += "</p>\n    </footer>\n  </form>\n</div>\n";
return output;
} catch (e) {
  runtime.handleError(e, lineno, colno);
}
}
return {
root: root
};
})();
templates["search/main.html"] = (function() {function root(env, context, frame, runtime) {
var lineno = null;
var colno = null;
var output = "";
try {
var includeTemplate = env.getTemplate("_macros/market_tile.html");
output += includeTemplate.render(context.getVariables(), frame.push());
output += "\n";
var includeTemplate = env.getTemplate("_macros/more_button.html");
output += includeTemplate.render(context.getVariables(), frame.push());
output += "\n\n<section id=\"search-results\" class=\"main full c\">\n  ";
output += runtime.suppressValue(env.getExtension("defer")["run"](context,runtime.makeKeywordArgs({"url": (lineno = 4, colno = 23, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "apiParams"), "apiParams", ["search",runtime.contextOrFrameLookup(context, frame, "params")])),"pluck": "objects","as": "app","paginate": "ol.listing"}),function() {var t_1 = "";t_1 += "\n    <header class=\"secondary-header c\">\n      <h2>\n        ";
t_1 += runtime.suppressValue((lineno = 7, colno = 16, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "_plural"), "_plural", ["<b>{n}</b> Result","<b>{n}</b> Results",runtime.makeKeywordArgs({"n": runtime.memberLookup((runtime.memberLookup((runtime.contextOrFrameLookup(context, frame, "response")),"meta", env.autoesc)),"total_count", env.autoesc)})])), env.autoesc);
t_1 += "\n        <span class=\"subtitle hide-on-mobile\">";
t_1 += runtime.suppressValue((lineno = 8, colno = 48, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "_"), "_", ["Showing <b>1</b>&ndash;<b class=\"total-results\">{total}</b>",runtime.makeKeywordArgs({"total": (lineno = 8, colno = 121, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "len"), "len", [runtime.contextOrFrameLookup(context, frame, "this")]))})])), env.autoesc);
t_1 += "</span>\n      </h2>\n      <a href=\"#\" class=\"expand-toggle\" title=\"";
t_1 += runtime.suppressValue((lineno = 10, colno = 49, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "_"), "_", ["Expand"])), env.autoesc);
t_1 += "\"></a>\n    </header>\n    <ol class=\"container listing search-listing c\">\n      ";
frame = frame.push();
var t_3 = runtime.contextOrFrameLookup(context, frame, "this");
for(var t_2=0; t_2 < t_3.length; t_2++) {
var t_4 = t_3[t_2];
frame.set("result", t_4);
t_1 += "\n        <li class=\"item result app c\">\n          ";
t_1 += runtime.suppressValue((lineno = 15, colno = 22, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "market_tile"), "market_tile", [t_4,runtime.makeKeywordArgs({"link": true,"force_button": true,"src": "search"})])), env.autoesc);
t_1 += "\n        </li>\n      ";
}
frame = frame.pop();
t_1 += "\n\n      ";
t_1 += "\n      ";
if(runtime.memberLookup((runtime.memberLookup((runtime.contextOrFrameLookup(context, frame, "response")),"meta", env.autoesc)),"next", env.autoesc)) {
t_1 += "\n        ";
t_1 += runtime.suppressValue((lineno = 21, colno = 20, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "more_button"), "more_button", [runtime.memberLookup((runtime.memberLookup((runtime.contextOrFrameLookup(context, frame, "response")),"meta", env.autoesc)),"next", env.autoesc)])), env.autoesc);
t_1 += "\n      ";
}
t_1 += "\n    </ol>\n  ";
return t_1;
}
,function() {var t_5 = "";t_5 += "\n    <p class=\"spinner spaced alt\"></p>\n  ";
return t_5;
}
,function() {var t_6 = "";t_6 += "\n    <p class=\"no-results\">\n      ";
t_6 += runtime.suppressValue((lineno = 28, colno = 8, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "_"), "_", ["No results found"])), env.autoesc);
t_6 += "\n    </p>\n  ";
return t_6;
}
,function() {var t_7 = "";t_7 += "\n    <p class=\"no-results\">\n      ";
t_7 += "\n      ";
t_7 += runtime.suppressValue((lineno = 33, colno = 8, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "_"), "_", ["No results found, try again later"])), env.autoesc);
t_7 += "\n    </p>\n  ";
return t_7;
}
), env.autoesc);
output += "\n</section>\n";
return output;
} catch (e) {
  runtime.handleError(e, lineno, colno);
}
}
return {
root: root
};
})();
templates["settings/feedback.html"] = (function() {function root(env, context, frame, runtime) {
var lineno = null;
var colno = null;
var output = "";
try {
var includeTemplate = env.getTemplate("_macros/forms.html");
output += includeTemplate.render(context.getVariables(), frame.push());
output += "\n";
var t_1 = "feedback";
frame.set("current_page", t_1);
if(!frame.parent) {
context.setVariable("current_page", t_1);
context.addExport("current_page");
}
output += "\n\n<div class=\"main feedback modal c\">\n  <div>\n    ";
var includeTemplate = env.getTemplate("settings/nav.html");
output += includeTemplate.render(context.getVariables(), frame.push());
output += "\n    <form method=\"post\" class=\"feedback-form form-modal\">\n      <p class=\"brform simple-field c\">\n        <textarea name=\"feedback\" required></textarea>\n      </p>\n      <p class=\"form-footer\">\n        ";
output += runtime.suppressValue((lineno = 11, colno = 23, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "potato_captcha"), "potato_captcha", [])), env.autoesc);
output += "\n        <button type=\"submit\">";
output += runtime.suppressValue((lineno = 12, colno = 32, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "_"), "_", ["Send"])), env.autoesc);
output += "</button>\n      </p>\n    </form>\n  </div>\n</div>\n";
return output;
} catch (e) {
  runtime.handleError(e, lineno, colno);
}
}
return {
root: root
};
})();
templates["settings/main.html"] = (function() {function root(env, context, frame, runtime) {
var lineno = null;
var colno = null;
var output = "";
try {
output += "<section class=\"main account\" id=\"account-settings\">\n  <header class=\"secondary-header hide-on-mobile c\">\n    <h2>";
output += runtime.suppressValue((lineno = 2, colno = 10, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "_"), "_", ["Account Settings"])), env.autoesc);
output += "</h2>\n  </header>\n\n  ";
var t_1 = "settings";
frame.set("current_page", t_1);
if(!frame.parent) {
context.setVariable("current_page", t_1);
context.addExport("current_page");
}
output += "\n  ";
var includeTemplate = env.getTemplate("settings/nav.html");
output += includeTemplate.render(context.getVariables(), frame.push());
output += "\n\n  <form class=\"form-grid account-settings\"";
output += runtime.suppressValue((!(lineno = 8, colno = 78, runtime.callWrap(runtime.memberLookup((runtime.contextOrFrameLookup(context, frame, "user")),"logged_in", env.autoesc), "user[\"logged_in\"]", []))?" novalidate":""), env.autoesc);
output += ">\n    <div class=\"simple-field c only-logged-in\">\n      <div class=\"form-label label\">\n        <label for=\"email\">";
output += runtime.suppressValue((lineno = 11, colno = 29, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "_"), "_", ["Email"])), env.autoesc);
output += "</label>\n      </div>\n      <div class=\"form-col\">\n        <input type=\"email\" name=\"email\" id=\"email\" readonly value=\"";
output += runtime.suppressValue((lineno = 14, colno = 85, runtime.callWrap(runtime.memberLookup((runtime.contextOrFrameLookup(context, frame, "user")),"get_setting", env.autoesc), "user[\"get_settin\"]", ["email"])), env.autoesc);
output += "\">\n      </div>\n    </div>\n\n    <div class=\"brform simple-field c only-logged-in\">\n      <div class=\"form-label\">\n        <label for=\"display_name\">";
output += runtime.suppressValue((lineno = 20, colno = 36, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "_"), "_", ["Display Name"])), env.autoesc);
output += "</label>\n      </div>\n      <div class=\"form-col\">\n        <input name=\"display_name\" id=\"display_name\" value=\"";
output += runtime.suppressValue((lineno = 23, colno = 77, runtime.callWrap(runtime.memberLookup((runtime.contextOrFrameLookup(context, frame, "user")),"get_setting", env.autoesc), "user[\"get_settin\"]", ["display_name"])), env.autoesc);
output += "\" maxlength=\"50\" type=\"text\" required>\n      </div>\n    </div>\n\n    <div class=\"simple-field c\">\n      <div class=\"form-label\">\n        <label for=\"region\">";
output += runtime.suppressValue((lineno = 29, colno = 30, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "_"), "_", ["Region"])), env.autoesc);
output += "</label>\n      </div>\n      <div class=\"form-col\">\n        <div class=\"pretty-select\">\n          <select name=\"region\" id=\"region\">\n            ";
var t_2 = (lineno = 34, colno = 47, runtime.callWrap(runtime.memberLookup((runtime.contextOrFrameLookup(context, frame, "user")),"get_setting", env.autoesc), "user[\"get_settin\"]", ["region"]));
frame.set("user_region", t_2);
if(!frame.parent) {
context.setVariable("user_region", t_2);
context.addExport("user_region");
}
output += "\n            ";
frame = frame.push();
var t_4 = (lineno = 35, colno = 67, runtime.callWrap(runtime.memberLookup((runtime.memberLookup((runtime.contextOrFrameLookup(context, frame, "settings")),"REGION_CHOICES_SLUG", env.autoesc)),"items", env.autoesc), "settings[\"REGION_CHO\"][\"items\"]", []));
var t_3;
if (runtime.isArray(t_4)) {
for (t_3=0; t_3 < t_4.length; t_3++) {
var t_5 = t_4[t_3][0]
frame.set("code", t_4[t_3][0]);
var t_6 = t_4[t_3][1]
frame.set("region", t_4[t_3][1]);
output += "\n              <option value=\"";
output += runtime.suppressValue(t_5, env.autoesc);
output += "\"";
output += runtime.suppressValue((t_5 == t_2?" selected":""), env.autoesc);
output += ">\n                ";
output += runtime.suppressValue(t_6, env.autoesc);
output += "</option>\n            ";
}
} else {
t_3 = -1;
for(var t_7 in t_4) {
t_3++;
var t_8 = t_4[t_7];
frame.set("code", t_7);
frame.set("region", t_8);
output += "\n              <option value=\"";
output += runtime.suppressValue(t_7, env.autoesc);
output += "\"";
output += runtime.suppressValue((t_7 == t_2?" selected":""), env.autoesc);
output += ">\n                ";
output += runtime.suppressValue(t_8, env.autoesc);
output += "</option>\n            ";
}
}
frame = frame.pop();
output += "\n          </select>\n        </div>\n      </div>\n    </div>\n\n    <footer>\n      <p><button type=\"submit\">";
output += runtime.suppressValue((lineno = 45, colno = 33, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "_"), "_", ["Save Changes"])), env.autoesc);
output += "</button></p>\n      <p class=\"extras\">\n        <a href=\"javascript:\" class=\"button alt logout only-logged-in\">";
output += runtime.suppressValue((lineno = 47, colno = 73, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "_"), "_", ["Sign Out"])), env.autoesc);
output += "</a>\n        <a href=\"javascript:\" class=\"button alt persona only-logged-out\">";
output += runtime.suppressValue((lineno = 48, colno = 75, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "_"), "_", ["Sign In / Sign Up"])), env.autoesc);
output += "</a>\n      </p>\n    </footer>\n  </form>\n\n</section>\n";
return output;
} catch (e) {
  runtime.handleError(e, lineno, colno);
}
}
return {
root: root
};
})();
templates["settings/nav.html"] = (function() {function root(env, context, frame, runtime) {
var lineno = null;
var colno = null;
var output = "";
try {
var macro_t_1 = runtime.makeMacro(
["view_name", "title"], 
[], 
function (l_view_name, l_title, kwargs) {
frame = frame.push();
kwargs = kwargs || {};
frame.set("view_name", l_view_name);
frame.set("title", l_title);
var output= "";
output += "\n<li><a";
if(runtime.contextOrFrameLookup(context, frame, "current_page") == l_view_name) {
output += " class=\"sel\"";
}
output += " href=\"";
output += runtime.suppressValue((lineno = 1, colno = 66, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "url"), "url", [l_view_name])), env.autoesc);
output += "\">\n  ";
output += runtime.suppressValue(l_title, env.autoesc);
output += "</a></li>\n";
frame = frame.pop();
return new runtime.SafeString(output);
});
context.setVariable("_url", macro_t_1);
output += "\n\n<menu class=\"secondary-header toggles c\">\n  ";
output += runtime.suppressValue((lineno = 6, colno = 7, runtime.callWrap(macro_t_1, "_url", ["settings",(lineno = 6, colno = 21, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "_"), "_", ["Account"]))])), env.autoesc);
output += "\n  ";
output += runtime.suppressValue((lineno = 7, colno = 7, runtime.callWrap(macro_t_1, "_url", ["purchases",(lineno = 7, colno = 22, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "_"), "_", ["My Apps"]))])), env.autoesc);
output += "\n  ";
output += runtime.suppressValue((lineno = 8, colno = 7, runtime.callWrap(macro_t_1, "_url", ["feedback",(lineno = 8, colno = 21, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "_"), "_", ["Feedback"]))])), env.autoesc);
output += "\n</menu>\n<div class=\"secondary-header hide-on-mobile\">\n  <h2>";
output += runtime.suppressValue((lineno = 11, colno = 8, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "_"), "_", ["Feedback"])), env.autoesc);
output += "</h2>\n  <a href=\"#\" class=\"close btn-cancel\">";
output += runtime.suppressValue((lineno = 12, colno = 41, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "_"), "_", ["Close"])), env.autoesc);
output += "</a>\n</div>\n";
return output;
} catch (e) {
  runtime.handleError(e, lineno, colno);
}
}
return {
root: root
};
})();
templates["terms.html"] = (function() {function root(env, context, frame, runtime) {
var lineno = null;
var colno = null;
var output = "";
try {
output += "<section class=\"site-terms-of-use main full c\">\n  <header class=\"secondary-header c\">\n    <h2>";
output += runtime.suppressValue((lineno = 2, colno = 10, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "_"), "_", ["Terms of Use"])), env.autoesc);
output += "</h2>\n  </header>\n  <article class=\"prose\">\n    <p>Note: The proposed full version of the Terms of Use for the Firefox Marketplace is currently under review and comment on our <a href=\"http://groups.google.com/group/mozilla.governance/topics\">governance mailing list</a>. &nbsp;When the Firefox Marketplace is fully launched, we will ask for your consent to the final Terms of Use.</p>\n\n    <p>February 23, 2012</p>\n\n    <h3>Summary</h3>\n    <p>This top section is a summary of the terms below. It is provided as an aid to your understanding - but be sure to read the entire document, because when you agree to it, you are indicating you accept all of it, not just this summary:</p>\n    <ul>\n      <li>You must be at least 18 years old to have an account on the Marketplace or have your parent consent and supervise your use of the Marketplace. &nbsp;Regardless, you have to be at least 13 years old.</li>\n      <li>Our use of your data will be in accordance with our <a href=\"";
output += runtime.suppressValue((lineno = 13, colno = 75, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "url"), "url", ["privacy"])), env.autoesc);
output += "\">privacy policy</a>.</li>\n      <li>Developers (not Mozilla) are solely responsible for each App or Add-on, including providing you with support or refunds. We require Developers to provide at least an initial automatic refund period, after which the Developer may approve or deny a refund request, at their discretion.</li>\n      <li>You should make sure you understand the Privacy Policy for each App or Add-on. If you believe any App or Add-on does not comply with our Privacy Guidelines, let us know through the &ldquo;Report Abuse&rdquo; link on the listing page for the App or Add-on and we will take action as we think appropriate.</li>\n      <li>Don&rsquo;t do anything illegal or that could hurt us or others.</li>\n      <li>We&rsquo;re not responsible for your use of the Firefox Marketplace or the actions of other users, including Developers.</li>\n      <li>You&rsquo;ll be responsible for your use or misuse of the Firefox Marketplace, Apps or Add-ons.</li>\n    </ul>\n\n    <h3>Introduction</h3>\n    <p>Mozilla Corporation (&ldquo;Mozilla&rdquo;, &ldquo;us&rdquo; or &ldquo;we&rdquo;) is committed to promoting choice and innovation on the web. &nbsp;That&rsquo;s why Mozilla created the Firefox Marketplace &ndash; a publicly available market that allowing developers to distribute their Apps or Add-ons to users for use on any device that can access the open web.</p>\n    <p>Your use of the Firefox Marketplace is subject to the terms and conditions of this Terms of Use as well as the related Firefox Marketplace policies referred to in these Terms or in the Firefox Marketplace (we will refer to these collectively as the &ldquo;Terms&rdquo;).</p>\n\n    <h3>Eligibility</h3>\n    <p>By using the Firefox Marketplace, you agree that: <strong>(i)</strong> you are at least 18 years old or are acting with the consent and supervision of your parent; and <strong>(ii)</strong> you have full power, capacity, and authority to accept these Terms on behalf of yourself, or if applicable, your employer or other entity that you represent. In any case, you represent that you are at least 13 years of age as the Firefox Marketplace is not available to users under the age of 13.</p>\n\n    <h3>Modifications to the Terms</h3>\n    <p>We reserve the right to change these Terms in our sole discretion and if we do make changes, we will post a notice on the Firefox Marketplace describing the changes that were made, so make sure to check back periodically. &nbsp;We may also notify you through email or on the Marketplace itself. If you have any questions about these Terms or the Firefox Marketplace, please contact us.\n\n    <h3>Definitions</h3>\n    <p>&ldquo;Developers&rdquo; are third party developers who make their Marketplace Content available through the Firefox Marketplace.</p>\n    <p>You can install Add-ons or Apps (together, &ldquo;Marketplace Content&rdquo;) through the Firefox Marketplace:</p>\n    <ul>\n      <li>&ldquo;Add-ons&rdquo; are extensions, themes, search providers, dictionaries, and language packs that allow you to extend the functionality of the Firefox browser.</li>\n      <li>&ldquo;Apps&rdquo; are applications written using open web technologies that can run on multiple platforms.</li>\n      <li>Some Apps and Add-ons may be purchased from developers through the Firefox Marketplace (each, a &ldquo;Purchased&rdquo; App or Add-on and together, &ldquo;Purchased Content&rdquo;).</li>\n    </ul>\n\n    <h3>Marketplace Content</h3>\n    <p>Each individual Developer is the merchant of record for their Marketplace Content. This means that each Developer, not Mozilla (except where we develop our own Apps or Add-ons), is solely responsible for their Add-ons and Apps.</p>\n\n    <h3>Purchased Content</h3>\n    <p>Purchased Content is tied to your Persona account through authentication, a system designed to let you access the content from all of your supported devices. You won&rsquo;t be able to use most Purchased Content without logging in with your Persona account. By purchasing Purchased Content, you agree not to breach these terms, including by intentionally circumventing any authentication mechanism. We may stop providing access to the Firefox Marketplace or suspend your access to Purchased Content if we believe that you have violated these terms. Developers may sell products and services that require you to log in or authenticate using additional credentials aside from Persona.</p>\n\n    <h3>Refunds &amp; Support</h3>\n    <p>Unless otherwise noted, the Marketplace Content listed in the Firefox Marketplace is developed and sold by third-party Developers, not Mozilla. Accordingly, support requests related to Marketplace Content must be made to the Developer of that Marketplace Content, and technical questions related to the operation of the Firefox Marketplace should be made to Mozilla. To request support for Marketplace Content you have purchased, please visit the Account History area of the Firefox Marketplace and select &ldquo;Request Support&rdquo;.</p>\n    <p>If you are unhappy with your Purchased Content, you may request a refund from the Developer by requesting support, as described above. We require Developers to provide at least an initial automatic refund period, after which the Developer may approve or deny your request, at their discretion. For more information about refunds, please see our <a href=\"https://developer.mozilla.org/en-US/docs/Apps/Marketplace_Payments\">Refund and Support policy</a>.</p>\n\n    <h3>Disputes about Marketplace Content</h3>\n    <p>We aren&rsquo;t responsible for any disputes arising from your purchases on the Firefox Marketplace from any Developer and all such disputes, including billing disputes should be submitted, as applicable, to the Developer in question, the payment processor or your credit card company.</p>\n\n    <h3>Additional Terms regarding Marketplace Content</h3>\n    <p>To the extent some of the content on the Firefox Marketplace are covered by separate terms (such as an end user license agreement, an open source license and/or a terms of use for Marketplace Content from a Developer), you agree to comply with such terms. &nbsp;You can find the terms under which Marketplace Content is being distributed on the information page of that Marketplace Content.</p>\n\n    <h3>Privacy</h3>\n    <p>You will be required to provide information about yourself (such as identification or contact details) as part of your registration for and use of the Firefox Marketplace. You agree that any payment information provided to payment providers will always be accurate, correct and up to date. Mozilla will use your information in conjunction with our operation of the Firefox Marketplace in accordance with the information handling practices in the Firefox Marketplace <a href=\"";
output += runtime.suppressValue((lineno = 57, colno = 486, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "url"), "url", ["privacy"])), env.autoesc);
output += "\">Privacy Policy</a>.</p>\n    <p>If you purchase an App from a Developer, Mozilla sends that Developer some of your information, including your Persona username (frequently you email address). Please see our <a href=\"";
output += runtime.suppressValue((lineno = 58, colno = 195, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "url"), "url", ["privacy"])), env.autoesc);
output += "\">Privacy Policy</a> for more detail.</p>\n    <p>While the Firefox Marketplace <a href=\"";
output += runtime.suppressValue((lineno = 59, colno = 50, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "url"), "url", ["site.privacy"])), env.autoesc);
output += "\">Privacy Policy</a> applies to the Firefox Marketplace, it does not cover any Marketplace Content. You should check the privacy policy of a piece of Marketplace Content to discover the privacy practices concerning such Marketplace Content and be comfortable with them before purchasing, installing or using that Marketplace Content.</p>\n    <p>We contractually require our developers to adhere to certain privacy and other guidelines in our <a href=\"https://marketplace.firefox.com/developers/docs/policies/agreement\">Developer Agreement</a>. If you believe that a developer is not adhering to contractual terms or guidelines, please let us know through the &ldquo;Report Abuse&rdquo; link for the relevant Market Content and we will investigate your request and take action, as we think appropriate.</p>\n\n    <h3>Your Submissions</h3>\n    <p>You may upload comments, profile pictures and other content as a part of the features of the Firefox Marketplace (&ldquo;Your Submissions&rdquo;). For clarity, &ldquo;Your Submissions&rdquo; won&rsquo;t include any Apps or Add-ons that you upload to the Firefox Marketplace. By uploading Your Submissions, you hereby grant us a non-exclusive, worldwide, royalty free license to use Your Submissions in connection with the provision and promotion of the Firefox Marketplace. You represent and warrant that Your Submissions will not infringe the rights of any third party and will comply with our Content Guidelines.</p>\n\n    <h3>Digital Millennium Copyright Act Notice</h3>\n    <p>If you are a copyright owner or an agent of a copyright owner and believe that content available by means of one of Mozilla&rsquo;s websites infringes one or more of your copyrights, please immediately notify Mozilla&#39;s Copyright Agent by means of emailed, mailed, or faxed notice (&quot;DMCA Notice&quot;) and include the information described below. You can review 17 U.S.C. &sect; 512(c)(3) of the Digital Millennium Copyright Act for authoritative detail, or consult your own attorney if you need assistance. If Mozilla takes action in response to a DMCA Notice, it will make a good faith attempt to contact the party that made such content available by means of the most recent email address, if any, provided by such party to Mozilla. You may be held liable for damages based on certain material misrepresentations contained in a DMCA Notice. Thus, if you are not sure content located on or linked to by the website infringes your copyright, you should consider first contacting an attorney.</p>\n    <p>All DMCA Notices should include the following:</p>\n    <ol>\n      <li>A signature, electronic or physical, of the owner, or a person authorized to act on behalf of the owner, of an exclusive copyright right that is being infringed;</li>\n      <li>An identification of the copyrighted work or works that you claim have been infringed;</li>\n      <li>A description of the nature and location of the material that you claim to infringe your copyright, in sufficient detail to permit Mozilla to find and positively identify that content, including the URL where it is located;</li>\n      <li>Your name, address, telephone number, and email address where we can contact you; and</li>\n      <li>A statement by you: <strong>(i)</strong> that you believe in good faith that the use of the material that you claim infringes your copyright is not authorized by law, or by the copyright owner or such owner&#39;s agent; and, <strong>(ii)</strong> that all of the information contained in your DMCA Notice is accurate, and under penalty of perjury, that you are either the owner of, or a person authorized to act on behalf an owner of, the exclusive copyright right that is being infringed.</li>\n    </ol>\n    <p>Mozilla&#39;s designated Copyright Agent to receive notifications of claimed infringement is as follows:</p>\n    <address>\n      Harvey Anderson<br>\n      Mozilla Corporation<br>\n      650 Castro Street, Suite 300<br>\n      Mountain View, CA 94041<br>\n      Email: dmcanotice at mozilla dot com<br>\n      Phone Number: <a href=\"tel:6509030800\">650-903-0800</a><br>\n      Fax: 650-903-0875<br>\n    </address>\n    <p>If you fail to comply with all of the requirements of a DMCA notice, Mozilla may not act upon your notice.</p>\n    <p>Mozilla will terminate a user&#39;s account if, under appropriate circumstances, they are determined to be a repeat infringer.</p>\n    <p>The contact information provided above also applies to notices that are based on non-U.S. copyrights or trademarks.</p>\n    <p>Only DMCA Notices, Trademark Notices (which are defined below), and international copyright or trademark notices should go to the copyright agent.</p>\n    <p>Please be advised that any DMCA Notices sent to Mozilla may be sent to third parties (including the accused) and posted on the Internet (including at <a  href=\"http://www.chillingeffects.org/\">http://www.chillingeffects.org/</a>).</p>\n\n    <h3>Trademark Notices</h3>\n    <p>If you are a trademark owner or an agent of a trademark owner and believe that content available by means of one of Mozilla&rsquo;s websites infringes one or more of your trademarks, please immediately notify Mozilla&#39;s Copyright Agent by means of emailed, mailed, or faxed notice (&quot;Trademark Notice&quot;) and include the information described above for DMCA notices. Mozilla handles notices it receives of trademark violations via a process very similar to the DMCA Notice process that is described above for copyrights. In addition to the DMCA Notice requirements, Mozilla requires that the entire Trademark Notice be made by the trademark owner (or her agent) under penalty of perjury.</p>\n\n    <h3>Export</h3>\n    <p>Some of the content you may download from Mozilla through the Firefox Marketplace may have legal restrictions on its export. You agree to comply with all applicable export and re-export control laws and regulations and you confirm that you are not prohibited from receiving exports and services under US or other export laws.</p>\n\n    <h3>General Representation and Warranty</h3>\n    <p>You represent and warrant that your use of the Firefox Marketplace will be in accordance with these Terms, with any applicable laws and regulations, and with any other applicable policy or terms and conditions. For example, if you decide to become a Developer yourself, you must agree to the <a href=\"https://marketplace.firefox.com/developers/docs/policies/agreement\">Developer Agreement</a>.</p>\n\n    <h3>Release and Indemnification</h3>\n    <p>You release Mozilla, its officers, employees, agents and successors from claims, demands and damages of every kind or nature arising out of or related to any disputes with other users, including Developers.</p>\n    <p>You agree to defend, indemnify and hold harmless Mozilla, its contractors and its licensors, and their respective directors, officers, employees and agents from and against any and all third party claims and expenses, including attorneys&#39; fees, arising out of your use of the Firefox Marketplace and Marketplace Content, including but not limited to out of your violation of any representation or warranty contained in these Terms.</p>\n\n    <h3>Disclaimer; Limitation of Liability</h3>\n    <p>For clarity, as used herein, &ldquo;Content&rdquo; includes, without limitation, &ldquo;Marketplace Content&rdquo;.</p>\n    <p>EXCEPT AS OTHERWISE EXPRESSLY STATED, INCLUDING BUT NOT LIMITED TO IN A LICENSE OR OTHER AGREEMENT GOVERNING THE USE OF SPECIFIC CONTENT, ALL CONTENT LOCATED AT OR AVAILABLE FROM THE Firefox Marketplace IS PROVIDED &quot;AS IS,&quot; AND MOZILLA, ITS CONTRACTORS AND ITS LICENSORS MAKE NO REPRESENTATIONS OR WARRANTIES, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE, TITLE OR NON-INFRINGEMENT OF PROPRIETARY RIGHTS. WITHOUT LIMITING THE FOREGOING, MOZILLA, ITS CONTRACTORS AND ITS LICENSORS MAKE NO REPRESENTATION OR WARRANTY THAT CONTENT LOCATED ON THE Firefox Marketplace IS FREE FROM ERROR OR SUITABLE FOR ANY PURPOSE; NOR THAT THE USE OF SUCH CONTENT WILL NOT INFRINGE ANY THIRD PARTY COPYRIGHTS, TRADEMARKS OR OTHER INTELLECTUAL PROPERTY RIGHTS. YOU UNDERSTAND AND AGREE THAT YOU DOWNLOAD OR OTHERWISE OBTAIN CONTENT THROUGH MOZILLA&#39;S WEBSITES AT YOUR OWN DISCRETION AND RISK, AND THAT MOZILLA, ITS CONTRACTORS AND ITS LICENSORS WILL HAVE NO LIABILITY OR RESPONSIBILITY FOR ANY DAMAGE TO YOUR COMPUTER SYSTEM OR DATA THAT RESULTS FROM THE DOWNLOAD OR USE OF SUCH CONTENT.</p>\n    <p>EXCEPT AS OTHERWISE EXPRESSLY STATED, INCLUDING BUT NOT LIMITED TO IN A LICENSE OR OTHER AGREEMENT GOVERNING THE USE OF SPECIFIC CONTENT, IN NO EVENT WILL MOZILLA, ITS CONTRACTORS OR ITS LICENSORS BE LIABLE TO YOU OR ANY OTHER PARTY FOR ANY DIRECT, INDIRECT, SPECIAL, CONSEQUENTIAL OR EXEMPLARY DAMAGES, REGARDLESS OF THE BASIS OR NATURE OF THE CLAIM, RESULTING FROM ANY USE OF THE Firefox Marketplace, OR THE CONTENTS THEREOF OR OF ANY HYPERLINKED WEB SITE, INCLUDING WITHOUT LIMITATION ANY LOST PROFITS, BUSINESS INTERRUPTION, LOSS OF DATA OR OTHERWISE, EVEN IF MOZILLA, ITS CONTRACTORS OR ITS LICENSORS WERE EXPRESSLY ADVISED OF THE POSSIBILITY OF SUCH DAMAGES.</p>\n    <p>SOME JURISDICTIONS MAY NOT ALLOW THE EXCLUSION OF IMPLIED WARRANTIES OR THE EXCLUSION OR LIMITATION OF LIABILITY FOR CERTAIN INCIDENTAL OR CONSEQUENTIAL DAMAGES, SO SOME OF THE ABOVE LIMITATIONS MAY NOT APPLY TO YOU.</p>\n\n    <h3>Governing Law</h3>\n    <p>These Terms shall be governed by the laws of the State of California without regard to conflict of law principles. The provisions of the United Nations Convention on the International Sale of Goods and the Uniform Computer Information Transactions Act, however designated, are excluded and shall not apply to this Agreement or any transactions hereunder. You agree to submit to the personal and exclusive jurisdiction of the state courts and federal courts located within Santa Clara County, California for the purpose of litigating any claims or disputes.</p>\n\n    <h3>Miscellaneous</h3>\n    <p>You may not assign your rights or delegate its obligations under these Terms. &nbsp;These Terms are not intended to benefit, nor shall it be deemed to give rise to, any rights in any third party. &nbsp;These Terms will be governed and construed in accordance with the laws of California, without regard to conflict of law principles. The parties are independent contractors. &nbsp;These Terms shall not be construed to create a joint venture or partnership between the parties. &nbsp;Neither party shall be deemed to be an employee, agent, partner or legal representative of the other for any purpose and neither shall have any right, power or authority to create any obligation or responsibility on behalf of the other. These Terms constitute the entire agreement between the parties with respect to the subject matter hereof. &nbsp;These Terms supersede, and govern, any other prior or collateral agreements with respect to the subject matter hereof. If any provision of these Terms are held or made invalid or unenforceable for any reason, such invalidity shall not affect the remainder of these Terms, and the invalid or unenforceable provisions shall be replaced by a mutually acceptable provision, which being valid, legal and enforceable comes closest to the original intentions of the parties hereto and has like economic effect. &nbsp;The failure of either party at any time or times to require performance of any provision hereof shall in no manner affect the right at a later time to enforce the same. &nbsp;No waiver by either party of the breach of any term or covenant contained in these Terms, whether by conduct or otherwise, in any one or more instances, shall be deemed to be, or construed as, a further or continuing waiver of any such breach or a waiver of the breach of any other term or covenant contained in these Terms.</p>\n  </article>\n</section>\n";
return output;
} catch (e) {
  runtime.handleError(e, lineno, colno);
}
}
return {
root: root
};
})();
templates["tests.html"] = (function() {function root(env, context, frame, runtime) {
var lineno = null;
var colno = null;
var output = "";
try {
output += "<section class=\"main infobox\">\n    <div>\n        <h2>Unit Tests</h2>\n        <progress value=\"0\" />\n        <table>\n            <tr>\n                <th>Started</th>\n                <th>Passed</th>\n                <th>Failed</th>\n            </tr>\n            <tr>\n                <td id=\"c_started\">0</td>\n                <td id=\"c_passed\">0</td>\n                <td id=\"c_failed\">0</td>\n            </tr>\n        </table>\n        <ol class=\"tests\"></ol>\n    </div>\n</section>\n\n<script type=\"text/javascript\" src=\"/tests/apps.js\"></script>\n<script type=\"text/javascript\" src=\"/tests/cache.js\"></script>\n<script type=\"text/javascript\" src=\"/tests/l10n.js\"></script>\n<script type=\"text/javascript\" src=\"/tests/models.js\"></script>\n<script type=\"text/javascript\" src=\"/tests/requests.js\"></script>\n<script type=\"text/javascript\" src=\"/tests/rewriters.js\"></script>\n<script type=\"text/javascript\" src=\"/tests/urls.js\"></script>\n<script type=\"text/javascript\" src=\"/tests/utils.js\"></script>\n";
return output;
} catch (e) {
  runtime.handleError(e, lineno, colno);
}
}
return {
root: root
};
})();
templates["user/purchases.html"] = (function() {function root(env, context, frame, runtime) {
var lineno = null;
var colno = null;
var output = "";
try {
var includeTemplate = env.getTemplate("_macros/market_tile.html");
output += includeTemplate.render(context.getVariables(), frame.push());
output += "\n";
var includeTemplate = env.getTemplate("_macros/more_button.html");
output += includeTemplate.render(context.getVariables(), frame.push());
output += "\n\n<section class=\"main account purchases c\" id=\"account-settings\">\n  ";
var t_1 = "purchases";
frame.set("current_page", t_1);
if(!frame.parent) {
context.setVariable("current_page", t_1);
context.addExport("current_page");
}
output += "\n  ";
var includeTemplate = env.getTemplate("settings/nav.html");
output += includeTemplate.render(context.getVariables(), frame.push());
output += "\n\n  ";
if((lineno = 7, colno = 20, runtime.callWrap(runtime.memberLookup((runtime.contextOrFrameLookup(context, frame, "user")),"logged_in", env.autoesc), "user[\"logged_in\"]", []))) {
output += "\n    ";
output += runtime.suppressValue(env.getExtension("defer")["run"](context,runtime.makeKeywordArgs({"url": (lineno = 8, colno = 19, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "api"), "api", ["installed"])),"pluck": "objects","as": "app","paginate": "ol.listing"}),function() {var t_2 = "";t_2 += "\n      <header class=\"secondary-header hide-on-mobile c\">\n        <h2>\n          ";
t_2 += runtime.suppressValue((lineno = 11, colno = 12, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "_"), "_", ["My Apps"])), env.autoesc);
t_2 += "\n          <span class=\"subtitle\">";
t_2 += runtime.suppressValue((lineno = 12, colno = 35, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "_"), "_", ["Showing <b>1</b>&ndash;<b class=\"total-results\">{total}</b>",runtime.makeKeywordArgs({"total": (lineno = 12, colno = 108, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "len"), "len", [runtime.contextOrFrameLookup(context, frame, "this")]))})])), env.autoesc);
t_2 += "</span>\n        </h2>\n        <a href=\"#\" class=\"expand-toggle\" title=\"";
t_2 += runtime.suppressValue((lineno = 14, colno = 51, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "_"), "_", ["Expand"])), env.autoesc);
t_2 += "\"></a>\n      </header>\n      <ol class=\"container listing only-logged-in c\">\n        ";
frame = frame.push();
var t_4 = runtime.contextOrFrameLookup(context, frame, "this");
for(var t_3=0; t_3 < t_4.length; t_3++) {
var t_5 = t_4[t_3];
frame.set("result", t_5);
t_2 += "\n          <li class=\"item result app c\">\n            ";
t_2 += runtime.suppressValue((lineno = 19, colno = 24, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "market_tile"), "market_tile", [t_5,runtime.makeKeywordArgs({"link": true,"force_button": true})])), env.autoesc);
t_2 += "\n          </li>\n        ";
}
frame = frame.pop();
t_2 += "\n\n        ";
if(runtime.memberLookup((runtime.memberLookup((runtime.contextOrFrameLookup(context, frame, "response")),"meta", env.autoesc)),"next", env.autoesc)) {
t_2 += "\n          ";
t_2 += runtime.suppressValue((lineno = 24, colno = 22, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "more_button"), "more_button", [runtime.memberLookup((runtime.memberLookup((runtime.contextOrFrameLookup(context, frame, "response")),"meta", env.autoesc)),"next", env.autoesc)])), env.autoesc);
t_2 += "\n        ";
}
t_2 += "\n      </ol>\n    ";
return t_2;
}
,function() {var t_6 = "";t_6 += "\n      <p class=\"spinner alt spaced\"></p>\n    ";
return t_6;
}
,function() {var t_7 = "";t_7 += "\n      <header class=\"secondary-header hide-on-mobile c\">\n        <h2>";
t_7 += runtime.suppressValue((lineno = 31, colno = 14, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "_"), "_", ["My Apps"])), env.autoesc);
t_7 += "</h2>\n      </header>\n      <p class=\"no-results only-logged-in\">\n        ";
t_7 += runtime.suppressValue((lineno = 34, colno = 10, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "_"), "_", ["You have no apps"])), env.autoesc);
t_7 += "\n      </p>\n    ";
return t_7;
}
,null), env.autoesc);
output += "\n  ";
}
else {
output += "\n    <header class=\"secondary-header hide-on-mobile c\">\n      <h2>";
output += runtime.suppressValue((lineno = 39, colno = 12, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "_"), "_", ["My Apps"])), env.autoesc);
output += "</h2>\n    </header>\n  ";
}
output += "\n  <footer class=\"only-logged-out\">\n    <article class=\"extras\">\n      <p class=\"notice\">";
output += runtime.suppressValue((lineno = 44, colno = 26, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "_"), "_", ["You must be signed in to view your apps."])), env.autoesc);
output += "</p>\n      <a class=\"button full persona\" href=\"#\">";
output += runtime.suppressValue((lineno = 45, colno = 48, runtime.callWrap(runtime.contextOrFrameLookup(context, frame, "_"), "_", ["Sign in / Sign up"])), env.autoesc);
output += "</a>\n    </article>\n  </footer>\n</section>\n";
return output;
} catch (e) {
  runtime.handleError(e, lineno, colno);
}
}
return {
root: root
};
})();
define("templates", ["nunjucks"], function(nunjucks) {
    nunjucks.env = new nunjucks.Environment([], {autoescape: true});
    nunjucks.env.registerPrecompiled(templates);
    nunjucks.templates = templates;
    console.log("Templates loaded");
    return nunjucks;
});
})();;

require('marketplace');

})(window, void 0);
