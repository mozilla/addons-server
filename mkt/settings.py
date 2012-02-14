from lib.settings_base import *

APP_PREVIEW = True
ROOT_URLCONF = 'mkt.urls'
TEMPLATE_DIRS += (path('mkt/templates'),)
INSTALLED_APPS += (
    'mkt.site',
    'mkt.hub',
    'mkt.submit',
    'mkt.experiments',
)
SUPPORTED_NONAPPS += (
    'hub',
    'submit',
)

# Until there are enough context processors to warrant replacing the existing
# ones, let's just override them.
TEMPLATE_CONTEXT_PROCESSORS = list(TEMPLATE_CONTEXT_PROCESSORS)
TEMPLATE_CONTEXT_PROCESSORS.remove('amo.context_processors.global_settings')
TEMPLATE_CONTEXT_PROCESSORS += [
    'mkt.site.context_processors.global_settings',
    'mkt.experiments.context_processors.fragment',
]


NO_ADDONS_MODULES = (
    'addons.views',
    'devhub.views.dashboard',  # The apps dashboard is a different view.
    'devhub.views.submit',  # Addon submit not ok, app submit a-ok.
    'browse.views.personas',
    'browse.views.extensions',
    'browse.views.language_tools',
    'browse.views.themes',
)

# Next level, no consumer for you!
NO_CONSUMER_MODULES = (
    'api',
    'bandwagon.views',
    'browse.views',
    'compat.views',
    'discovery.views',
    'editors.views',
    'files.views',
    'market.views',
    'piston',
    'users.views.purchases',
    'users.views.payments',
    'search.views',
    'sharing.views',
    'tags.views',
    'versions.views',
    'webapps.views',
)

# Specific view modules and methods that we don't want to force login on.
NO_LOGIN_REQUIRED_MODULES = (
    'csp.views.policy',
    'csp.views.report',
    'django.views.i18n.javascript_catalog',
    'django.contrib.auth.views.password_reset',
    'django.contrib.auth.views.password_reset_done'
)

# Extend the bundles.
MINIFY_BUNDLES['css'].update({
    'hub': (
        'css/impala/base.css',
        'css/hub/base.less',
        'css/hub/header.less',
        'css/hub/forms.less',
        'css/submit/flow.less',
        'css/submit/terms.less',
    ),
    'marketplace-experiments': (
        'marketplace-experiments/css/reset.less',
        'marketplace-experiments/css/site.less',
        'marketplace-experiments/css/header.less',
        'marketplace-experiments/css/detail.less',
        'marketplace-experiments/css/buttons.less',
        'marketplace-experiments/css/slider.less',
    ),
})
MINIFY_BUNDLES['js'].update({
    'hub': (
        'js/lib/underscore.js',
        'js/marketplace-experiments/jquery-1.7.1.min.js',
        'js/zamboni/browser.js',
        'js/hub/init.js',
        'js/impala/capabilities.js',
        # PJAX is not ready.
        #'js/lib/jquery.pjax.js',
        'js/lib/jquery.cookie.js',
        'js/zamboni/storage.js',
        'js/impala/serializers.js',

        # Developer Hub-specific stuff.
        #'js/submit/flow-pjax.js',
        'js/submit/flow.js',
    ),
    'marketplace-experiments': (
        'js/marketplace-experiments/jquery-1.7.1.min.js',
        'js/marketplace-experiments/slider.js',
    ),
})

# Feature flags.
POTCH_MARKETPLACE_EXPERIMENTS = False
