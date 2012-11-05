// is the captured node exempt from fragment loading?
function fragmentFilter(el) {
    var href = el.getAttribute('href') || el.getAttribute('action'),
        $el = $(el);
    return !href || href.substr(0,4) == 'http' ||
            href.substr(0,7) === 'mailto:' ||
            href.substr(0,11) === 'javascript:' ||
            href.substr(0,1) === '#' ||
            href.indexOf('/developers/') !== -1 ||
            href.indexOf('/ecosystem/') !== -1 ||
            href.indexOf('/statistics/') !== -1 ||
            href.indexOf('?modified=') !== -1 ||
            el.getAttribute('target') === '_blank' ||
            $el.hasClass('post') || $el.hasClass('sync');
}

(function(container, nodeFilter) {
    var threshold = 250,
        timeout = false,
        fragmentCache = {},
        cacheHash = '',
        reloadOnNext = false;
    if (z.capabilities.replaceState) {
        var $loading = $('<div>', {'class': 'loading-fragment overlay',
                                   'html': '<em></em>'})
                        .prependTo($('body'));

        // Hijack <form> submission
        z.body.on('submit', 'form', function(e) {
            if (reloadOnNext) return;
            var form = $(this);
            var method = form.attr('method').toLowerCase();
            if (method === 'get') {
                e.preventDefault();
                hijackGET(form);
            } else if (method === 'post') {
                e.preventDefault();
                hijackPOST(form);
            }
            // Not GET or POST? Not interested.
        });

        function hijackGET(form) {
            var action = form.attr('action');
            //strip existing queryparams off the action.
            var link = document.createElement('a');
            link.href = action;
            var path = link.pathname + '?' + form.serialize();
            form.trigger('loadfragment', path);
        }

        function hijackPOST(form) {
            console.log('hijacking POST');
            startLoading();
            var action = form.attr('action') || window.location.href;
            var data = form.serialize();
            if (data) {
                data += '&_hijacked=true';
            } else {
                data = '_hijacked=true';
            }
            $.ajax({
                type: 'POST',
                url: action || window.location,
                data: form.serialize()
            }).done(function(response) {
                // load up the response fragment!
                updateContent(response);
            }).fail(function(response) {
                form.trigger('notify', {
                    title: gettext('Error'),
                    msg: gettext('A server error has occurred.')
                });
                endLoading();
            });
        }

        // capture clicks in our target environment
        z.body.on('click', 'a', function(e) {
            if (reloadOnNext) return;
            var href = this.getAttribute('href');
            if (e.metaKey || e.ctrlKey || e.button !== 0) return;
            if (nodeFilter(this)) {
                return;
            }
            e.preventDefault();
            fetchFragment({path: href});
        });

        // preserve scrollTop like a real boy
        function markScrollTop() {
            var path = window.location.pathname + window.location.search + window.location.hash;
            var state = {path: path, scrollTop: $(document).scrollTop()};
            console.log(format('setting the scrolltop for {0}', path));
            history.replaceState(state, false, path);
        }

        // start the loading indicator
        function startLoading() {
            timeout = setTimeout(function() {
                container.trigger('startfragmentload');
                $loading.addClass('show');
            }, threshold);
            loadTimer = new Date().getTime();
        }

        // end the loading timer and report timing
        function endLoading() {
            clearTimeout(timeout);
            _.delay(function() {
                $loading.removeClass('show');
            }, 400);
            stick.custom({
                'window.performance.timing.fragment.loaded':
                    (new Date()).getTime() - loadTimer
            });
        }

        // handle link clicking and state popping.
        function fetchFragment(state, popped) {
            console.log('fetchFragment');
            var href = state.path;
            startLoading();
            markScrollTop();

            //caching!
            if (fragmentCache[href]) {
                console.log(format('cached {0} at {1}', href, state.scrollTop));
                updateContent(fragmentCache[href], href, popped, {scrollTop: state.scrollTop});
            } else {
                console.log(format('fetching {0} at {1}', href, state.scrollTop));

                // Chrome doesn't obey the Vary header, so we need to keep the fragments
                // from getting cached with the page itself. Remove once Chrome bug #94369
                // has been resolved as fixed.
                var fetch_href = href;
                if (navigator.userAgent.indexOf('Chrome') > -1) {
                    fetch_href += (href.indexOf("?") > -1 ? '&' : '?') + 'frag';
                }

                $.get(fetch_href, function(d, textStatus, xhr) {
                    // Bail if this is not HTML.
                    if (xhr.getResponseHeader('content-type').indexOf('text/html') < 0) {
                        window.location = href;
                        return;
                    }
                    console.log('caching fragment');
                    updateContent(d, href, popped, {scrollTop: state.scrollTop});
                }).error(function(e) {
                    console.log('fetch error!');
                    window.location = href;
                });
            }

        }

        function synchronousLoad(href) {
            // TODO(potch): Save the user's navigation stack.
            window.location.href = href;
        }

        // pump content into our page, clean up after ourselves.
        function updateContent(content, href, popped, opts) {
            opts = opts || {};
            endLoading();

            container.html(content);
            var page = container.find('#page');
            if (!page.length) {
                throw "something has gone terribly wrong";
            }

            // scroll to the right spot.
            $('html, body').scrollTop(opts.scrollTop || 0);

            // Reset our lovelies.
            _.extend(z, {
                body: $(document.body),
                page: $('#container'),
                context: $('#page').data('context')
            });

            // Do we have an instruction to clear a part of the fragment cache?
            var bustCookie = $.cookie('fcbust');
            if (bustCookie) {
                // The `fcbust` is a JSON-encoded list of strings.
                var decoded_prefixes = JSON.parse(bustCookie);

                for (var i = 0; i < decoded_prefixes.length; i++) {
                    var clear_prefix = decoded_prefixes[i];

                    if (clear_prefix === '/') {
                        // If the server is asking us to bust '/', we should just
                        // perform a synchronous load of the page.
                        synchronousLoad(z.context.uri);
                        return;
                    }

                    // Delete all the matching cache entries.
                    _.each(fragmentCache, function(_, key) {
                        // If the prefix doesn't match the cache entry, skip it.
                        if (clear_prefix.length > key.length ||
                            key.substr(0, clear_prefix.length) !== clear_prefix) {
                            return;
                        }

                        delete fragmentCache[key];
                    });
                };

                // Clear out the `fcbust` cookie.
                $.cookie('fcbust', null);
            }

            if (z.context.cache === 'cache') {
                console.log('caching fragment');
                fragmentCache[href] = content;
            }

            // If we have new media, load the next fragment synchronously.
            if (z.context.hash != cacheHash) {
                reloadOnNext = true;
                container.trigger('fragmentpendingsync');
                console.log('performing synchronous load next navigation');
            }

            if (!href) {
                href = z.context.uri;
                console.log('whats the 411' + href);
            }

            // Clear jQuery's data attribute cache for body.
            jQuery.cache[document.body[jQuery.expando]].data = null;

            // We so sneaky.
            document.title = z.context.title;

            var type = z.context.type;

            var newState = {
                path: href,
                type: type,
                title: z.context.title,
                scrollTop: $(document).scrollTop()
            };
            if (!popped) history.pushState(newState, false, href);

            container.trigger('fragmentloaded', [href, popped, newState]);
        }

        $(window).on('popstate', function(e) {
            var state = e.originalEvent.state;
            if (state) {
                fetchFragment(state, true);
            }
        }).on('loadfragment', function(e, href) {
            if (href) fetchFragment({path: href});
        }).on('refreshfragment', function(e) {
            var path = window.location.pathname + window.location.search + window.location.hash;
            if (fragmentCache[path]) {
                delete fragmentCache[path];
            }
            fetchFragment({path: path});
        });

        $(function() {
            // Don't forget to update updateContent too, bro.
            var path = window.location.pathname + window.location.search + window.location.hash;
            var type = z.context.type;
            cacheHash = z.context.hash;
            var state = {
                path: path,
                type: type
            };
            history.replaceState(state, false, path);

            if (z.context.cache === 'cache') {
                console.log('caching fragment');
                fragmentCache[path] = container.html();
            }
            container.trigger('fragmentloaded', [path, false, state]);
        });
        console.log("fragments enabled");
    } else {
        console.warn("fragments not enabled!!");
        $(function() {
            container.trigger('fragmentloaded');
        });
    }
})(z.page, fragmentFilter);
