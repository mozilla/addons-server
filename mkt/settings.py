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

TEMPLATE_CONTEXT_PROCESSORS = (
    'django.contrib.auth.context_processors.auth',
    'django.core.context_processors.debug',
    'django.core.context_processors.media',
    'django.core.context_processors.request',
    'session_csrf.context_processor',

    'django.contrib.messages.context_processors.messages',

    'mkt.site.context_processors.i18n',
    'mkt.site.context_processors.global_settings',
    'mkt.site.context_processors.static_url',
    'jingo_minify.helpers.build_ids',
)

TEMPLATE_CONTEXT_PROCESSORS += ('mkt.experiments.context_processors.fragment',)


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
        'css/hub/forms.less',
        'css/submit/progress.less',
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
    ),
    'marketplace-experiments': (
        'js/marketplace-experiments/jquery-1.7.1.min.js',
        'js/marketplace-experiments/slider.js',
    ),
})

# Feature flags.
POTCH_MARKETPLACE_EXPERIMENTS = False
