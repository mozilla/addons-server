// Do this last- initialize the marketplace!

define('marketplace', ['login', 'notification', 'prefetch', 'tracking', 'feedback'], function() {
    // Initialize analytics tracking.
    z.page.on('fragmentloaded', function(event, href, popped, state) {
        if (!popped) {
            // TODO: Nuke Webtrends once we're exclusively on GA.
            webtrendsAsyncInit();

            // GA track every fragment loaded page.
            _gaq.push(['_trackPageview', href]);
        }
    });
});
require('marketplace');

$('#splash-overlay').addClass('hide');
