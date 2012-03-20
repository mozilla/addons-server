(function() {
    var threshold = 250,
        timeout = false;
    z.page = $('#page');
    if (z.capabilities['replaceState']) {
        var $loading = $('<div>', {'class': 'loading balloon',
                                   'html': gettext('Loading&hellip;')})
                        .prependTo($('#site-header'));

        z.page.on('click', 'a', function(e) {
            var href = this.getAttribute('href');
            if (!href || href.substr(0,4) == 'http' || href === '#') return;
            e.preventDefault();
            history.pushState({path: href}, false, href);
            fetchFragment(href);
        });

        function fetchFragment(href) {
            timeout = setTimeout(function() { $loading.addClass('active'); },
                                 threshold);
            $.get(href, function(d) {
                clearTimeout(timeout);
                z.page.html(d).trigger('fragmentloaded');
                $loading.removeClass('active');
                $('html, body').animate({scrollTop: 0}, 200);
            });
        }

        $(window).on('popstate', function(e) {
            var state = e.originalEvent.state;
            if (state) {
                fetchFragment(state.path);
            }
        });

        $(function() {
            var path = window.location.pathname + window.location.search;
            history.replaceState({path: path}, false, path);
            z.page.trigger('fragmentloaded');
        });
    }
})();
