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
            fetchFragment(href);
        });

        function fetchFragment(href, popped) {
            timeout = setTimeout(function() { $loading.addClass('active'); },
                                 threshold);
            console.log(format('fetching {0}', href));
            $.get(href, function(d, textStatus, xhr) {
                clearTimeout(timeout);

                // Bail if this is not HTML.
                if (xhr.getResponseHeader('content-type').indexOf('text/html') < 0) {
                    window.location = href;
                    return;
                }

                if (!popped) history.pushState({path: href}, false, href);
                page.html(d).trigger('fragmentloaded');

                // We so sneaky.
                var $title = page.find('title');
                document.title = $title.text();
                $title.remove();

                var $bodyclass = page.find('meta[name=bodyclass]'),
                    $body = $('body');
                $body.attr('class', $body.data('class') + ' ' + $bodyclass.attr('content'));
                $bodyclass.remove();

                _.delay(function() { $loading.removeClass('active'); }, 400);
                $('html, body').animate({scrollTop: 0}, 200);
            });
        }

        $(window).on('popstate', function(e) {
            var state = e.originalEvent.state;
            if (state) {
                fetchFragment(state.path, true);
            }
        }).on('loadfragment', function(e, href) {
            if (href) fetchFragment(href);
        });

        $(function() {
            var path = window.location.pathname + window.location.search;
            history.replaceState({path: path}, false, path);
            page.trigger('fragmentloaded');
        });
        console.log("fragments enabled");
    } else {
        console.warn("fragments not enabled!!");
        page.trigger('fragmentloaded');
    }
})(z.page);
