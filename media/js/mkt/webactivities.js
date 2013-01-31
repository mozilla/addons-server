define('webactivities', [], function() {
    function init() {
        if (!z.capabilities.webactivities) {
            return;
        }

        // Load up an app
        navigator.mozSetMessageHandler('marketplace-app', function(req) {
            var slug = req.source.data.slug;
            z.win.trigger('loadfragment', '/app/' + encodeURIComponent(slug));
        });

        // Load up the page to leave a rating for the app.
        navigator.mozSetMessageHandler('marketplace-app-rating', function(req) {
            var slug = req.source.data.slug;
            z.win.trigger('loadfragment', '/app/' + encodeURIComponent(slug) + '/reviews/add');
        });

        // Load up a category page
        navigator.mozSetMessageHandler('marketplace-category', function(req) {
            var slug = req.source.data.slug;
            z.win.trigger('loadfragment', '/apps/' + encodeURIComponent(slug));
        });

        // Load up a search
        navigator.mozSetMessageHandler('marketplace-search', function(req) {
            var query = req.source.data.query;
            z.win.trigger('loadfragment', '/search/?q=' + encodeURIComponent(query));
        });
    }
    return {init: init};
});
