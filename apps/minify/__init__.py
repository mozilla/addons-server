# Bundles is a dictionary of two dictionaries, css and js, which list css files
# and js files that can be bundled together.

BUNDLES = {
    'css': {
        # CSS files common to the entire site.
        'common': ('css/main.css', 'css/main-mozilla.css',)
    },
    'js': {
        # JS files common to the entire site.
        'common': (
                'js/__utm.js',
                'js/jquery-compressed.js',
                'js/zamboni/underscore-min.js',
                'js/jquery.cookie.js',
                'js/amo2009/global.js',
                'js/amo2009/slimbox2.js',
                'js/amo2009/addons.js',
                'js/amo2009/install-button.js',
                'js/jquery-ui/jqModal.js',
                'js/amo2009/home.js',
                'js/zamboni/init.js',
            )
    }
}
