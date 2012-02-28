import os

from lib.settings_base import *

# We'll soon need a `settings_test_mkt` to override this.
APP_PREVIEW = True

WAFFLE_TABLE_SUFFIX = 'mkt'

# So temporary. Allow us to link to new devhub URLs from `Addon.get_dev_url()`.
MARKETPLACE = True

# Pretty temporary. Set the correct home for Marketplace. Redirects are sick!
HOME = 'mkt.developers.views.home'

# 403 view to render for CSRF failures.
CSRF_FAILURE_VIEW = 'mkt.site.views.csrf_failure'

# Set log in/log out URLs for redirects to work.
LOGIN_URL = '/login'
LOGOUT_URL = '/logout'

# Let robots tear this place up.
ENGAGE_ROBOTS = True

ROOT_URLCONF = 'mkt.urls'

INSTALLED_APPS = list(INSTALLED_APPS)
INSTALLED_APPS.remove('api')
INSTALLED_APPS.remove('compat')
INSTALLED_APPS.remove('discovery')
INSTALLED_APPS.remove('devhub')
INSTALLED_APPS = tuple(INSTALLED_APPS)

INSTALLED_APPS += (
    'mkt.site',
    'mkt.developers',
    'mkt.hub',
    'mkt.submit',
    'mkt.experiments',
    'devhub',  # Put here so helpers.py doesn't get loaded first.
)
SUPPORTED_NONAPPS += (
    'dev',
    'hub',
    'submit',
    'login',
    'privacy-policy',
    'terms-of-use',
    'users',
)

MIDDLEWARE_CLASSES += (
    'amo.middleware.NoConsumerMiddleware',
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
    '--where=%s' % os.path.join(ROOT, 'mkt')
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
    'mkt.developers',
    'mkt.submit',
    'django.views.i18n.javascript_catalog',
    'django.contrib.auth.views.password_reset',
    'django.contrib.auth.views.password_reset_done',
    'jingo.views.direct_to_template'
)

# Extend the bundles.
MINIFY_BUNDLES['css'].update({
    'mkt/devreg': (
        # TODO: Port "READ ONLY" balloon from devreg-impala/header.less.
        # TODO: Use `hub/css/terms.less` for submission.

        # Contains reset, clearfix, etc.
        'css/devreg/base.css',

        # Base styles (body, breadcrumbs, islands, columns).
        'css/devreg/base.less',

        # Typographical styles (font treatments, headings).
        'css/devreg/typography.less',

        # Header (aux-nav, masthead, site-nav).
        'css/devreg/header.less',

        # Item rows (used on Dashboard).
        'css/devreg/listing.less',
        'css/devreg/paginator.less',

        # Buttons (used for paginator, "Edit" buttons, Refunds page).
        'css/devreg/buttons.less',

        # Popups, Modals, Tooltips.
        'css/devreg/devhub-popups.less',
        'css/devreg/tooltips.less',

        # L10n menu ("Localize for ...").
        'css/devreg/l10n.less',

        # Forms (used for tables on "Manage ..." pages).
        'css/devreg/devhub-forms.less',

        # Landing page
        'css/devreg/landing.less',

        # "Manage ..." pages.
        'css/devreg/manage.less',
        'css/devreg/prose.less',
        'css/devreg/authors.less',
        'css/devreg/in-app-config.less',
        'css/devreg/paypal.less',
        'css/devreg/refunds.less',
        'css/devreg/status.less',

        # Image Uploads (used for "Edit Listing" Images and Submission).
        'css/devreg/media.less',

        # Submission.
        'css/devreg/submit-progress.less',
        'css/devreg/submit-terms.less',
        'css/devreg/submit-manifest.less',
        'css/devreg/submit-details.less',
        'css/devreg/validation.less',

        # Developer Log In / Registration.
        'css/devreg/login.less',

        # Footer.
        'css/devreg/footer.less',
    ),
    'mkt/devreg-legacy': (
        'css/devreg-legacy/developers.less',  # Legacy galore.
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
    'mkt/devreg': (
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
        'js/zamboni/browserid_support.js',
        'js/impala/login.js',

        # Fix-up outgoing links.
        'js/zamboni/outgoing_links.js',

        # Stick.
        'js/lib/stick.js',

        # Developer Hub-specific scripts.
        'js/zamboni/truncation.js',
        'js/zamboni/upload.js',

        # New stuff.
        'js/devreg/devhub.js',
        'js/devreg/submit-details.js',

        # Specific stuff for making payments nicer.
        'js/devreg/paypal.js',
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

CELERY_ROUTES.update({
    # Devhub.
    'mkt.developers.tasks.validator': {'queue': 'devhub'},
    'mkt.developers.tasks.fetch_manifest': {'queue': 'devhub'},
    'mkt.developers.tasks.fetch_icon': {'queue': 'devhub'},
    'mkt.developers.tasks.file_validator': {'queue': 'devhub'},

    # Images.
    'mkt.developers.tasks.resize_icon': {'queue': 'images'},
    'mkt.developers.tasks.resize_preview': {'queue': 'images'},
})

# Paths.
ADDON_ICONS_DEFAULT_PATH = os.path.join(MEDIA_ROOT, 'img/hub')
ADDON_ICONS_DEFAULT_URL = MEDIA_URL + '/img/hub'

# Feature flags.
POTCH_MARKETPLACE_EXPERIMENTS = False
