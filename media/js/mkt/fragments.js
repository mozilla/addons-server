if (typeof history.pushState === 'function') {
    $('#page').on('click', 'a', function(e) {
        var href = this.getAttribute('href');
        if (!href || href.substr(0,4) == 'http') return;
        e.preventDefault();
        history.pushState({path: href}, false, href);
        fetchFragment(href);
    });

    function fetchFragment(href) {
        $.get(href, function(d) {
            $('#page').html(d);
        });
    }

    $(window).on('popstate', function(e) {
        var state = e.originalEvent.state;
        if (state) {
            fetchFragment(state.path);
        }
    });

    var path = window.location.pathname;
    history.replaceState({path: path}, false, path);
}
