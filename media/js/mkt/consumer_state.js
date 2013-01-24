(function() {

    define('state', [], function() {
        var sideEffects = {
            'language': function() {
                // Upon refocus, if `navigator.language` has changed, then let's
                // refresh the page to reset our cookies and get new localized content.
                if (navigator.language.toLowerCase() in z.body.data('locales')) {
                    // TODO: If lang in querystring, then remove.
                    // TODO: Prompt with confirmation before reload.
                    window.location.reload();
                }
            },
            'mozApps': function() {
                // Upon refocus, if `navigator.mozApps.getInstalled()` has changed,
                // then likely an app was deleted, so let's refresh the page container.
                z.page.trigger('refreshfragment');
            },
            'onLine': function() {
                // Upon refocus, if `navigator.onLine` is now `false`, then let's
                // redirect to offline page. The offline page redirects us back
                // when `navigator.onLine` becomes `true`.
                if (navigator.onLine === false) {
                    // TODO: Change this into a confirmation.
                    console.log('user is offline');
                    localStorage.from = window.location.href;
                    window.location = '/offline/home';
                }
            }
        };

        return {
            init: function() {
                function getState(init) {
                    var $def = $.Deferred();

                    // Keep track of user state here. If one of these values changes,
                    // there are side effects in `handleState`.
                    var state = {
                        language: navigator.language,
                        mozApps: {},
                        onLine: navigator.onLine
                    };

                    if (init) {
                        // This already gets called in `init.js`, so let's not duplicate logic.
                        state.mozApps = _.extend({}, z.apps);
                        $def.resolve(state);
                    } else {
                        if (z.capabilities.webApps) {
                            // Get list of installed apps.
                            r = window.navigator.mozApps.getInstalled();
                            r.onsuccess = function() {
                                _.each(r.result, function(v) {
                                    state.mozApps[v.manifestURL] = v;
                                });
                                $def.resolve(state);
                            };
                            r.onerror = function() {
                                // Fail gracefully.
                                $def.resolve(state);
                            };
                        }
                    }

                    return $def.promise();
                }

                function handleState() {
                    console.log('checking state ...');
                    getState().done(function(state) {
                        _.each(state, function(v, k) {
                            if (!_.isEqual(v, z.state[k])) {
                                console.log(k, 'has changed from', JSON.stringify(z.state[k]), 'to', JSON.stringify(v));
                                sideEffects[k].apply();
                            }
                        })
                    });
                }

                getState(true).done(function(state) {
                    z.state = state;
                    window.addEventListener('focus', handleState, false);
                    window.addEventListener('offline', handleState, false);
                    window.addEventListener('visibilitychange', function() {
                        if (document.hidden === false) {
                            handleState();
                        }
                    }, false);
                });
            }
        }
    });

})();
