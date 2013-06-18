// Do this last - initialize the Marketplace!

(function() {

    var modules = [
        'account',
        'feedback',
        'install',
        'login',
        'notification',
        'potatocaptcha',
        'prefetch',
        'tracking'
    ];

    define('marketplace', modules, function() {
        // Initialize analytics tracking.
        _gaq.push(['_trackPageview']);

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

    });

    require('marketplace');

    $('#splash-overlay').addClass('hide');

})();
