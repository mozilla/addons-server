(function(page) {
    var threshold = 250,
        timeout = false;
    if (z.capabilities['replaceState']) {
        var $loading = $('<div>', {'class': 'loading balloon',
                                   'html': gettext('Loading&hellip;')})
                        .prependTo($('#site-header'));

        page.on('click', 'a', function(e) {
            var href = this.getAttribute('href');
            if (e.metaKey || e.ctrlKey || e.button !== 0) return;
            if (!href || href.substr(0,4) == 'http' ||
                href.substr(0,7) === 'mailto:' ||
                href.substr(0,1) === '#' ||
                href.indexOf('/developers/') !== -1 ||
                href.indexOf('/statistics/') !== -1 ||
                href.indexOf('?modified=') !== -1 ||
                this.getAttribute('target') === '_blank') {
                return;
            }
            e.preventDefault();
            fetchFragment({path: href});
        });

        function markScrollTop() {
            var path = window.location.pathname + window.location.search;
            var state = {path: path, scrollTop: $(document).scrollTop()};
            history.replaceState(state, false, path);
        }

        function fetchFragment(state, popped) {
            var href = state.path;
            markScrollTop();
            timeout = setTimeout(function() { $loading.addClass('active'); },
                                 threshold);
            console.log(format('fetching {0} at {1}', href, state.scrollTop));
            $.get(href, function(d, textStatus, xhr) {
                clearTimeout(timeout);

                // Bail if this is not HTML.
                if (xhr.getResponseHeader('content-type').indexOf('text/html') < 0) {
                    window.location = href;
                    return;
                }

                var newState = {path: href, scrollTop: $(document).scrollTop()};
                if (!popped) history.pushState(newState, false, href);
                page.html(d).trigger('fragmentloaded');

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

                _.delay(function() { $loading.removeClass('active'); }, 400);
                $('html, body').scrollTop(state.scrollTop || 0);
            });
        }

        $(window).on('popstate', function(e) {
            var state = e.originalEvent.state;
            if (state) {
                fetchFragment(state, true);
            }
        }).on('loadfragment', function(e, href) {
            if (href) fetchFragment({path: href});
        });

        $(function() {
            var path = window.location.pathname + window.location.search;
            history.replaceState({path: path}, false, path);
            page.trigger('fragmentloaded');
        });
        console.log("fragments enabled");
    } else {
        console.warn("fragments not enabled!!");
        $(function() {
            page.trigger('fragmentloaded');
        });
    }
})(z.page);
