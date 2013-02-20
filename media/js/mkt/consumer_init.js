// Do this last - initialize the Marketplace!

(function() {

    var modules = [
        'account',
        'feedback',
        'forms',
        'install',
        'login',
        'notification',
        'potatocaptcha',
        'prefetch',
        'state',
        'tracking',
        'webactivities'
    ];

    define('marketplace', modules, function() {
        // Initialize analytics tracking.
        z.page.on('fragmentloaded', function(event, href, popped, state) {
            // Otherwise we'll track back button hits etc.
            if (!popped) {
                // GA track every fragment loaded page.
                _gaq.push(['_trackPageview', href]);
            }
        });

        // Check for mobile sizing.
        if (z.capabilities.mobile && z.body.hasClass('desktop')) {
            var notification = require('notification');
            notification({
                message: gettext('Click here to view the mobile Marketplace!')
            }).then(function() {
                $.cookie('mobile', 'true', {path: '/'});
                window.location.reload();
            }).fail(alert);
        }

        // This lets you refresh within the app by holding down command + R.
        if (z.capabilities.chromeless) {
            window.addEventListener('keydown', function(e) {
                if (e.keyCode == 82 && e.metaKey) {
                    window.location.reload();
                }
            });
        }

        require('state').init();
        require('webactivities').init();
    });

    require('marketplace');

    $('#splash-overlay').addClass('hide');

})();
