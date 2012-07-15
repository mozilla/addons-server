
// is the captured node exempt from fragment loading?
function fragmentFilter(el) {
    var href = el.getAttribute('href') || el.getAttribute('action');
    return !href || href.substr(0,4) == 'http' ||
            href.substr(0,7) === 'mailto:' ||
            href.substr(0,11) === 'javascript:' ||
            href.substr(0,1) === '#' ||
            href.indexOf('/developers/') !== -1 ||
            href.indexOf('/ecosystem/') !== -1 ||
            href.indexOf('/statistics/') !== -1 ||
            href.indexOf('?modified=') !== -1 ||
            el.getAttribute('target') === '_blank' ||
            $(el).hasClass('post');
}

(function(page, nodeFilter) {
    var threshold = 250,
        timeout = false,
        fragmentCache = {};
    if (z.capabilities.replaceState) {
        var $loading = $('<div>', {'class': 'loading balloon',
                                   'html': gettext('Loading&hellip;')})
                        .prependTo($('#site-header'));

        // capture clicks in our target environment
        z.body.on('click', 'a', function(e) {
            var href = this.getAttribute('href');
            if (e.metaKey || e.ctrlKey || e.button !== 0) return;
            if (nodeFilter(this)) {
                return;
            }
            e.preventDefault();
            fetchFragment({path: href});
        });

        // capture form tomfoolery
        // page.on('submit', 'form', function(e) {
        //     return;
        //     window.foo = this;
        //     console.log('gotcha!');
        //     if (nodeFilter(this)) {
        //         return;
        //     }
        //     e.preventDefault();

        //     // extract form info
        //     var url = this.getAttribute('action'),
        //         method = $(this).attr('method') || 'get',
        //         data = $(this).serialize();
        //     $.ajax(url, {
        //         data: data,
        //         type: method,
        //         complete: function() {
        //             window.foo = arguments;
        //         }
        //     });
        // });

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
                $loading.addClass('active');
            }, threshold);
            loadTimer = new Date().getTime();
        }

        // end the loading timer and report timing
        function endLoading() {
            clearTimeout(timeout);
            _.delay(function() {
                $loading.removeClass('active');
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
                    fragmentCache[href] = d;
                    updateContent(d, href, popped, {scrollTop: state.scrollTop});
                }).error(function() {
                    window.location = href;
                });
            }

        }

        // pump content into our page, clean up after ourselves.
        function updateContent(content, href, popped, opts) {
            endLoading();
            var newState = {path: href, scrollTop: $(document).scrollTop()};
            if (!popped) history.pushState(newState, false, href);

            page.html(content);
            $('html, body').scrollTop(opts.scrollTop || 0);
            page.trigger('fragmentloaded', [href, popped]);
            page.trigger('postfragmentloaded', [href, popped]);

            // We so sneaky.
            var $title = page.find('title');
            document.title = $title.text();
            $title.remove();

            // We so classy.
            var $body = $('body');
            if ($body.data('class')) {
                var $newclass = page.find('meta[name=bodyclass]');
                $body.attr('class', $body.data('class') + ' ' +
                                    $newclass.attr('content'));
                $newclass.remove();
            }
        }

        z.page.on('fragmentloaded', function() {
            console.log('get ready...');
            setTimeout(prefetch, 1000);
        });
        function prefetch() {
            var links = z.page.find('[data-prefetch]'),
                href;
            for (var i=0; i<links.length; i++) {
                href = links[i].getAttribute('href');
                if (!fragmentCache[href]) {
                    fetch(href);
                }
            }
        }

        function fetch(href) {
            $.get(href, function(d, textStatus, xhr) {
                // Bail if this is not HTML.
                if (xhr.getResponseHeader('content-type').indexOf('text/html') < 0) {
                    return;
                }
                fragmentCache[href] = d;
            });
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
            var path = window.location.pathname + window.location.search + window.location.hash;
            history.replaceState({path: path}, false, path);
            fragmentCache[path] = page.html();
            page.trigger('fragmentloaded', [path, false]);
            page.trigger('postfragmentloaded', [path, false]);
        });
        console.log("fragments enabled");
    } else {
        console.warn("fragments not enabled!!");
        $(function() {
            page.trigger('fragmentloaded');
            page.trigger('postfragmentloaded');
        });
    }
})(z.page, fragmentFilter);
