(function() {
    z.page = $('#page');
    if (z.capabilities['replaceState']) {
        z.page.on('click', 'a', function(e) {
            var href = this.getAttribute('href');
            if (!href || href.substr(0,4) == 'http' || href === '#') return;
            e.preventDefault();
            history.pushState({path: href}, false, href);
            fetchFragment(href);
        });

        function fetchFragment(href) {
            $.get(href, function(d) {
                z.page.html(d).trigger('fragmentloaded');
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
