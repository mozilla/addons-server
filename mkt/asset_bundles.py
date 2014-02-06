# A list of our CSS and JS assets for jingo-minify.

CSS = {
    'mkt/devreg': (
        # Contains reset, clearfix, etc.
        'css/devreg/base.css',

        # Base styles (body, breadcrumbs, islands, columns).
        'css/devreg/base.styl',
        'css/devreg/breadcrumbs.styl',

        # Typographical styles (font treatments, headings).
        'css/devreg/typography.styl',

        # Header (aux-nav, masthead, site-nav).
        'css/devreg/desktop-account-links.styl',
        'css/devreg/header.styl',

        # Item rows (used on Dashboard).
        'css/devreg/listing.styl',
        'css/devreg/legacy-paginator.styl',

        # Buttons (used for paginator, "Edit" buttons, Refunds page).
        'css/devreg/buttons.styl',

        # Popups, Modals, Tooltips.
        'css/devreg/notification.styl',
        'css/devreg/overlay.styl',
        'css/devreg/popups.styl',
        'css/devreg/device.styl',
        'css/devreg/tooltips.styl',

        # L10n menu ("Localize for ...").
        'css/devreg/l10n.styl',

        # Forms (used for tables on "Manage ..." pages).
        'css/devreg/forms.styl',

        # Tables.
        'css/devreg/data-grid.styl',

        # Landing page
        'css/devreg/landing.styl',

        # "Manage ..." pages.
        'css/devreg/manage.styl',
        'css/devreg/prose.styl',
        'css/devreg/authors.styl',
        'css/devreg/in-app-config.styl',
        'css/devreg/payments.styl',
        'css/devreg/refunds.styl',
        'css/devreg/transactions.styl',
        'css/devreg/status.styl',
        'css/devreg/content_ratings.styl',

        # Image Uploads (used for "Edit Listing" Images and Submission).
        'css/devreg/media.styl',
        'css/devreg/invisible-upload.styl',

        # Submission.
        'css/devreg/submit-progress.styl',
        'css/devreg/submit-terms.styl',
        'css/devreg/submit-manifest.styl',
        'css/devreg/submit-details.styl',
        'css/devreg/validation.styl',
        'css/devreg/submit.styl',
        'css/devreg/tabs.styl',

        # Developer Log In / Registration.
        'css/devreg/login.styl',

        # Footer.
        'css/devreg/footer.styl',
    ),
    'mkt/reviewers': (
        'css/zamboni/editors.styl',
        'css/devreg/consumer-buttons.styl',
        'css/devreg/content_ratings.styl',
        'css/devreg/data-grid.styl',
        'css/devreg/manifest.styl',
        'css/devreg/reviewers.styl',
        'css/devreg/reviewers-header.styl',
        'css/devreg/reviewers-mobile.styl',
        'css/devreg/themes_review.styl',
        'css/devreg/legacy-paginator.styl',
        'css/devreg/files.styl',
    ),
    'mkt/ecosystem': (
        'css/devreg/reset.styl',
        'css/devreg/consumer-typography.styl',
        'css/devreg/login.styl',
        'css/devreg/forms.styl',
        'css/ecosystem/landing.styl',
        'css/ecosystem/documentation.styl',
    ),
    'mkt/in-app-payments': (
        'css/devreg/reset.styl',
        'css/devreg/consumer-typography.styl',
        'css/devreg/buttons.styl',
        'css/devreg/in-app-payments.styl',
    ),
    'mkt/lookup': (
        'css/devreg/manifest.styl',
        'css/devreg/lookup-tool.styl',
        'css/devreg/activity.styl',
    ),
    'mkt/gaia': (
        # Gaia building blocks.
        'css/gaia/action_menu.css',
        'css/gaia/switches.css',
        'css/gaia/value_selector.css',
    ),
    'mkt/operators': (
        'css/devreg/legacy-paginator.styl',
        'css/devreg/data-grid.styl',
        'css/devreg/operators.styl',
    ),
}

JS = {
    'mkt/devreg': (
        # tiny module loader
        'js/lib/amd.js',

        'js/lib/jquery-1.9.1.js',
        'js/lib/underscore.js',
        'js/lib/format.js',
        'js/lib/jquery.cookie.js',
        'js/lib/stick.js',
        'js/lib/csrf.js',
        'js/common/fakefilefield.js',
        'js/devreg/gettext.js',
        'js/devreg/tracking.js',
        'js/devreg/init.js',  # This one excludes buttons initialization, etc.
        'js/devreg/modal.js',
        'js/devreg/overlay.js',
        'js/devreg/capabilities.js',
        'js/devreg/slugify.js',
        'js/devreg/formdata.js',
        'js/devreg/tooltip.js',
        'js/devreg/popup.js',
        'js/devreg/login.js',
        'js/devreg/notification.js',
        'js/devreg/outgoing_links.js',
        'js/devreg/utils.js',

        'js/impala/serializers.js',
        'js/common/keys.js',
        'js/common/upload-base.js',
        'js/common/upload-packaged-app.js',
        'js/common/upload-image.js',

        'js/devreg/l10n.js',

        # jQuery UI
        'js/lib/jquery-ui/jquery-ui-1.10.1.custom.js',
        'js/lib/jquery.minicolors.js',

        'js/devreg/devhub.js',
        'js/devreg/submit.js',
        'js/devreg/tabs.js',
        'js/devreg/edit.js',
        'js/devreg/validator.js',

        # Specific stuff for making payments nicer.
        'js/devreg/payments-enroll.js',
        'js/devreg/payments-manage.js',
        'js/devreg/payments.js',

        # For testing installs.
        'js/devreg/apps.js',
        'js/devreg/test-install.js',

        'js/devreg/tracking_app_submit.js',

        # IARC.
        'js/devreg/content_ratings.js',

        # Module initialization.
        'js/devreg/devreg_init.js',
    ),
    'mkt/reviewers': (
        'js/lib/highcharts.src.js',  # Used by editors.js
        'js/zamboni/storage.js',  # Used by editors.js
        'js/common/buckets.js',
        'js/devreg/reviewers/editors.js',
        'js/lib/jquery.hoverIntent.js',  # Used by jquery.zoomBox
        'js/lib/jquery.zoomBox.js',  # Used by themes_review
        'js/devreg/reviewers/themes_review.js',
        'js/devreg/apps.js',  # Used by install.js
        'js/devreg/reviewers/payments.js',
        'js/devreg/reviewers/install.js',
        'js/devreg/reviewers/buttons.js',
        'js/devreg/manifest.js',  # Used by reviewers.js
        'js/devreg/reviewers/reviewers.js',
        'js/devreg/reviewers/expandable.js',
        'js/devreg/reviewers/mobile_review_actions.js',
        'js/common/fakefilefield.js',
        'js/common/formsets.js',  # TODO: Not used? Only seen in devreg/init.js
        'js/devreg/reviewers/reviewers_init.js',
    ),
    'mkt/in-app-payments': (
        'js/lib/jquery-1.9.1.js',
        'js/devreg/inapp_payments.js',
        'js/lib/csrf.js',
        'js/impala/serializers.js',
        'js/devreg/login.js',
    ),
    'mkt/lookup': (
        'js/common/keys.js',
        'js/impala/ajaxcache.js',
        'js/devreg/suggestions.js',
        'js/devreg/manifest.js',
        'js/devreg/lookup-tool.js',
    ),
    'mkt/ecosystem': (
        'js/devreg/ecosystem.js',
    ),
    'mkt/debug': (
        'js/debug/tinytools.js',
    ),
}


def jquery_migrated():
    new_JS = dict(JS)
    for bundle, files in new_JS.iteritems():
        files = list(files)
        try:
            jquery = files.index('js/lib/jquery-1.9.1.js')
        except ValueError:
            continue
        # Insert jquery-migrate immediately after jquery (before any files
        # requiring jquery are loaded).
        files.insert(jquery + 1, 'js/lib/jquery-migrate-1.1.0.js')
        new_JS[bundle] = tuple(files)
    return new_JS


def less2stylus():
    """
    This will return a dict of the CSS bundles with `.styl` stylesheets
    instead of `.less` ones.

    Put in your local settings::

        try:
            MINIFY_BUNDLES['css'].update(asset_bundles.less2stylus())
        except AttributeError:
            pass

    """
    import os
    ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    def stylus(fn):
        fn_styl = fn.replace('.less', '.styl')
        if os.path.exists(os.path.join(ROOT, 'media', fn_styl)):
            fn = fn_styl
        return fn

    new_CSS = dict(CSS)
    for bundle, files in new_CSS.iteritems():
        new_CSS[bundle] = tuple(stylus(f) for f in files)
    return new_CSS
