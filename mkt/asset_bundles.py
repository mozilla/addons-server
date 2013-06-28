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
        'css/zamboni/editors.css',
        'css/devreg/consumer-buttons.styl',
        'css/devreg/ratings.styl',
        'css/devreg/data-grid.styl',
        'css/devreg/reviewers.styl',
        'css/devreg/themes_review.styl',
        'css/devreg/legacy-paginator.styl',
        'css/devreg/files.styl',
    ),
    'mkt/splash': (
        'css/mkt/splash.styl',
    ),
    'mkt/consumer': (
        'css/mkt/reset.styl',
        'css/mkt/typography.styl',
        'css/mkt/site.styl',
        'css/mkt/forms.styl',
        'css/mkt/header.styl',
        'css/mkt/account-links.styl',
        'css/mkt/buttons.styl',
        'css/mkt/notification.styl',
        'css/mkt/detail.styl',
        'css/mkt/ratings.styl',
        'css/mkt/categories.styl',
        'css/mkt/menu.styl',
        'css/mkt/infobox.styl',
        'css/mkt/promo-grid.styl',
        'css/mkt/overlay.styl',
        'css/mkt/search.styl',
        'css/mkt/paginator.styl',
        'css/mkt/suggestions.styl',
        'css/mkt/account.styl',
        'css/mkt/login.styl',
        'css/mkt/purchase.styl',
        'css/mkt/lightbox.styl',
        'css/mkt/filters.styl',
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
    'mkt/stats': (
        'css/devreg/legacy-paginator.styl',
        'css/devreg/jquery-ui/jquery-ui-1.10.1.custom.css',
        'css/devreg/stats.styl',
    ),
    'mkt/lookup': (
        'css/devreg/lookup-tool.styl',
        'css/devreg/activity.styl',
    ),
    'mkt/gaia': (
        # Gaia building blocks.
        'css/gaia/action_menu.css',
        'css/gaia/switches.css',
        'css/gaia/value_selector.css',
    )
}

# Bundle extensions (e.g., desktop).
CSS.update({
    'mkt/consumer-desktop': CSS['mkt/consumer'] + (
        # TODO: Split components into individual, appropriate stylesheets.
        'css/mkt/desktop.styl',
        'css/mkt/desktop-filters.styl',
        'css/mkt/desktop-forms.styl',
        'css/mkt/desktop-account.styl',
        'css/mkt/desktop-listing.styl',
        'css/mkt/desktop-details.styl',
        'css/mkt/desktop-ratings.styl',
    ),
})

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
        'js/mkt/gettext.js',
        'js/mkt/tracking.js',
        'js/devreg/init.js',  # This one excludes buttons initialization, etc.
        'js/mkt/modal.js',
        'js/mkt/overlay.js',
        'js/mkt/capabilities.js',
        'js/devreg/slugify.js',
        'js/devreg/formdata.js',
        'js/devreg/tooltip.js',
        'js/devreg/popup.js',
        'js/mkt/login.js',
        'js/mkt/notification.js',
        'js/mkt/outgoing_links.js',
        'js/mkt/utils.js',

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
        'js/mkt/apps.js',
        'js/devreg/test-install.js',

        # Module initialization.
        'js/devreg/devreg_init.js',
    ),
    'mkt/consumer': (
        # tiny module loader
        'js/lib/amd.js',

        'js/lib/jquery-1.9.1.js',
        'js/lib/jquery.cookie.js',
        'js/lib/underscore.js',
        'js/lib/format.js',

        # slider lib
        'js/lib/flipsnap.js',

        'js/mkt/tracking.js',
        'js/mkt/utils.js',
        'js/lib/csrf.js',
        'js/mkt/gettext.js',
        'js/zamboni/browser.js',
        'js/mkt/init.js',
        'js/lib/truncate.js',
        'js/zamboni/truncation.js',
        'js/common/keys.js',
        'js/mkt/capabilities.js',
        'js/impala/serializers.js',
        'js/mkt/potatocaptcha.js',
        'js/mkt/overlay.js',
        'js/mkt/login.js',
        'js/mkt/install.js',
        'js/mkt/payments.js',
        'js/mkt/buttons.js',
        'js/mkt/search.js',
        'js/mkt/apps.js',
        'js/mkt/header.js',

        # ui
        'js/mkt/notification.js',

        # Search suggestions.
        'js/impala/ajaxcache.js',
        'js/impala/suggestions.js',
        'js/mkt/mkt_suggestions.js',

        # Account settings.
        'js/mkt/account.js',
        'js/mkt/feedback.js',

        # Fix-up outgoing links.
        'js/mkt/outgoing_links.js',

        # Stick.
        'js/lib/stick.js',

        'js/mkt/prefetch.js',

        # Module initialization.
        'js/mkt/consumer_init.js',
    ),
    'mkt/reviewers': (
        'js/lib/highcharts.src.js',
        'js/zamboni/storage.js',
        'js/common/buckets.js',
        'js/zamboni/editors.js',
        'js/impala/formset.js',
        'js/lib/jquery.hoverIntent.js',
        'js/lib/jquery.zoomBox.js',
        'js/mkt/themes_review.js',
        'js/mkt/apps.js',
        'js/mkt/payments.js',
        'js/mkt/install.js',
        'js/mkt/buttons.js',
        'js/mkt/reviewers.js',
        'js/devreg/expandable.js',
        'js/devreg/mobile_review_actions.js',
        'js/common/fakefilefield.js',
        'js/common/formsets.js',
        'js/devreg/reviewers_init.js',
    ),
    'mkt/stats': (
        'js/zamboni/storage.js',
        'js/mkt/modal.js',
        'js/lib/highcharts.src.js',
        'js/mkt/stats/csv_keys.js',
        'js/mkt/stats/helpers.js',
        'js/mkt/stats/dateutils.js',
        'js/mkt/stats/manager.js',
        'js/mkt/stats/controls.js',
        'js/mkt/stats/overview.js',
        'js/mkt/stats/topchart.js',
        'js/mkt/stats/chart.js',
        'js/mkt/stats/table.js',
        'js/mkt/stats/chart_column.js',
        'js/mkt/stats/stats.js',
    ),
    'mkt/in-app-payments': (
        'js/lib/jquery-1.9.1.js',
        'js/mkt/inapp_payments.js',
        'js/lib/csrf.js',
        'js/impala/serializers.js',
        'js/mkt/login.js',
    ),
    'mkt/lookup': (
        'js/common/keys.js',
        'js/impala/ajaxcache.js',
        'js/impala/suggestions.js',
        'js/mkt/lookup-tool.js',
    ),
    'mkt/ecosystem': (
        'js/mkt/ecosystem.js',
    ),
    'mkt/debug': (
        'js/debug/tinytools.js',
    ),
}

JS_desktop = list(JS['mkt/consumer'])
if 'js/mkt/consumer_init.js' in JS_desktop:
    JS_desktop.remove('js/mkt/consumer_init.js')
JS_desktop = tuple(JS_desktop)

JS.update({
    'mkt/consumer-desktop': JS_desktop + (
        # This must be the last JS file defined!
        'js/mkt/consumer_init.js',
    ),
})


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
