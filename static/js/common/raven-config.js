(function() {
    var $body = $('body');
    var dsn = $body.data('raven-dsn');
    var urls = $body.data('raven-urls');
    if (dsn && urls) {
        Raven.config(dsn, {
            whitelistUrls: urls,
        }).install();
    } else {
        console.log('Skipping ravenJS installation');
    }
})();
