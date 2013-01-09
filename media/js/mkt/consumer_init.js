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

    // Check for mobile sizing.
    if (z.capabilities.mobile && z.body.hasClass('desktop')) {
        var notification = require('notification');

        notification({
            message: gettext('Click here to view the Mobile Marketplace!')
        }).then(function() {
            $.cookie('mobile', 'true', {path: '/'});
            window.location.reload();
        }).fail(alert);

    }

});
require('marketplace');

$('#splash-overlay').addClass('hide');
