from lib.settings_base import *

# We'll soon need a `settings_test_mkt` to override this.
APP_PREVIEW = True

# So temporary. Allow us to link to new devhub URLs from `Addon.get_dev_url()`.
MARKETPLACE = True

ROOT_URLCONF = 'mkt.urls'
TEMPLATE_DIRS += (path('mkt/templates'),)
INSTALLED_APPS += (
    'mkt.site',
    'mkt.developers',
    'mkt.hub',
    'mkt.submit',
    'mkt.experiments',
)
SUPPORTED_NONAPPS += (
    'dev',
    'hub',
    'submit',
)

TEMPLATE_CONTEXT_PROCESSORS = list(TEMPLATE_CONTEXT_PROCESSORS)
TEMPLATE_CONTEXT_PROCESSORS.remove('amo.context_processors.global_settings')
TEMPLATE_CONTEXT_PROCESSORS += [
    'mkt.site.context_processors.global_settings',
    'mkt.experiments.context_processors.fragment',
]

# Tests.
NOSE_ARGS = [
    '--with-fixture-bundling',
    '--exclude=default/*',
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
    'users.views.edit',
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
    'devreg': (
        # Popups, Modals, Tooltips.
        'css/devreg/devhub-popups.less',

        # Manage Authors.
        'css/devreg/authors.less',
    ),
    'devreg-legacy': (
        'css/devreg-legacy/main.css',
        'css/devreg-legacy/main-mozilla.css',
        'css/devreg-legacy/headerfooter.css',  # Potch, Remove.
        'css/devreg-legacy/zamboni.css',
        'css/devreg-legacy/formset.less',
        'css/devreg-legacy/header.less',
        'css/devreg-legacy/moz-tab.css',
        'css/devreg-legacy/footer.less',
        'css/devreg-legacy/faux-zamboni.less',

        # Developer Hub-specific styles.
        'css/devreg-legacy/tooltips.less',
        'css/devreg-legacy/developers.css',
        'css/devreg-legacy/docs.less',
        'css/devreg-legacy/developers.less',
        'css/devreg-legacy/formset.less',
        'css/devreg-legacy/devhub-forms.less',
        'css/devreg-legacy/submission.less',
        'css/devreg-legacy/refunds.less',
        'css/devreg-legacy/devhub-buttons.less',
        'css/devreg-legacy/in-app-config.less',
    ),
    'devreg-impala': (
        'css/devreg-impala/base.css',
        'css/devreg-impala/site.less',
        'css/devreg-impala/typography.less',
        'css/devreg-impala/headerfooter.css',  # Potch, Remove.
        'css/devreg-impala/forms.less',
        'css/devreg-impala/header.less',
        'css/devreg-impala/footer.less',
        'css/devreg-impala/moz-tab.css',
        'css/devreg-impala/reviews.less',
        'css/devreg-impala/buttons.less',
        'css/devreg-impala/addon_details.less',
        'css/devreg-impala/policy.less',
        'css/devreg-impala/expando.less',
        'css/devreg-impala/popups.less',
        'css/devreg-impala/l10n.less',
        'css/devreg-impala/contributions.less',
        'css/devreg-impala/prose.less',
        'css/devreg-impala/paginator.less',
        'css/devreg-impala/listing.less',
        'css/devreg-impala/versions.less',
        'css/devreg-impala/users.less',
        'css/devreg-impala/tooltips.less',
        'css/devreg-impala/login.less',
        'css/devreg-impala/apps.less',
        'css/devreg-impala/formset.less',
        'css/devreg-impala/tables.less',

        # Developer Hub-specific styles.
        'css/devreg-impala/developers.less',
        'css/devreg-impala/devhub-listing.less',
        'css/devreg-impala/dashboard.less',
        'css/devreg-impala/devhub-forms.less',
        'css/devreg-impala/submission.less',
        'css/devreg-impala/refunds.less',
    ),
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
    'devreg-legacy': (
        'js/lib/jquery-1.6.4.js',
        'js/lib/underscore.js',
        'js/zamboni/browser.js',
        'js/amo2009/addons.js',
        'js/devreg/init.js',  # This one excludes buttons initialization, etc.
        'js/impala/capabilities.js',
        'js/zamboni/format.js',
        'js/lib/jquery.cookie.js',
        'js/zamboni/storage.js',
        'js/zamboni/tabs.js',

        # jQuery UI.
        'js/lib/jquery-ui/jquery.ui.core.js',
        'js/lib/jquery-ui/jquery.ui.position.js',
        'js/lib/jquery-ui/jquery.ui.widget.js',
        'js/lib/jquery-ui/jquery.ui.mouse.js',
        'js/lib/jquery-ui/jquery.ui.autocomplete.js',
        'js/lib/jquery-ui/jquery.ui.datepicker.js',
        'js/lib/jquery-ui/jquery.ui.sortable.js',

        'js/impala/footer.js',
        'js/zamboni/truncation.js',
        'js/zamboni/helpers.js',
        'js/zamboni/global.js',
        'js/zamboni/l10n.js',
        'js/zamboni/debouncer.js',

        # Users.
        'js/zamboni/users.js',

        # Forms.
        'js/impala/forms.js',

        # Login.
        'js/impala/login.js',

        # Fix-up outgoing links.
        'js/zamboni/outgoing_links.js',

        # Stick.
        'js/lib/stick.js',

        # Developer Hub-specific scripts.
        'js/zamboni/truncation.js',
        'js/zamboni/upload.js',
        'js/zamboni/devhub.js',
        'js/zamboni/validator.js',
    ),
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
