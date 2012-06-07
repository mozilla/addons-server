(function() {
    function toggle($e) {
        // Toggle description + developer comments.
        $e.toggleClass('expanded').closest('section').find('.collapse').toggleClass('show');
    }
    z.page.on('click', 'a.collapse', _pd(function() {
        toggle($(this));
    })).on('click', '.approval-pitch', _pd(function() {
        $('#preapproval-shortcut').submit();
    }));

    // TODO: Target only WebRT.
    if (z.capabilities.mobile) {
        // Smart breadcrumbs to display on detail pages within B2G/WebRT.
        z.page.on('fragmentloaded', function(e, href, popped) {
            // Target breadcrumbs for detail pages only (for now).
            if (z.previous && href.indexOf('/app/') > -1) {
                $('#breadcrumbs li:visible:eq(1)')
                    .replaceWith(format('<li> <a href="{0}">{1}</a> </li>',
                                        z.previous.href, z.previous.title));
            }
            // Strip locale from URL.
            href = href.replace('/' + $('html').attr('lang'), '');
            if (!popped) {
                z.previous = {};
                if (['/', '/search/', '/apps/', '/themes/', '/app/'].startsWith(href)) {
                    // If it's a new page.
                    var title = escape_(z.page.find('h1:eq(0)').text() ||
                                        z.page.find('h2:eq(0)').text());
                    if (title) {
                        z.previous = {'title': title, 'href': href};
                    }
                }
            }
        });
    }
})();
