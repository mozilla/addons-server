# A list of our CSS and JS assets for jingo-minify.

CSS = {
    'mkt/devreg': (
        # Contains reset, clearfix, etc.
        'css/devreg/base.css',

        # Base styles (body, breadcrumbs, islands, columns).
        'css/devreg/base.less',
        'css/devreg/breadcrumbs.less',

        # Typographical styles (font treatments, headings).
        'css/devreg/typography.less',

        # Header (aux-nav, masthead, site-nav).
        'css/devreg/desktop-account-links.less',
        'css/devreg/header.less',

        # Item rows (used on Dashboard).
        'css/devreg/listing.less',
        'css/devreg/legacy-paginator.less',

        # Buttons (used for paginator, "Edit" buttons, Refunds page).
        'css/devreg/buttons.less',

        # Popups, Modals, Tooltips.
        'css/devreg/overlay.less',
        'css/devreg/popups.less',
        'css/devreg/device.less',
        'css/devreg/tooltips.less',

        # L10n menu ("Localize for ...").
        'css/devreg/l10n.less',

        # Forms (used for tables on "Manage ..." pages).
        'css/devreg/forms.less',

        # Tables.
        'css/devreg/data-grid.less',

        # Landing page
        'css/devreg/landing.less',

        # "Manage ..." pages.
        'css/devreg/manage.less',
        'css/devreg/prose.less',
        'css/devreg/authors.less',
        'css/devreg/in-app-config.less',
        'css/devreg/payments.less',
        'css/devreg/refunds.less',
        'css/devreg/transactions.less',
        'css/devreg/status.less',

        # Image Uploads (used for "Edit Listing" Images and Submission).
        'css/devreg/media.less',
        'css/devreg/invisible-upload.less',

        # Submission.
        'css/devreg/submit-progress.less',
        'css/devreg/submit-terms.less',
        'css/devreg/submit-manifest.less',
        'css/devreg/submit-details.less',
        'css/devreg/validation.less',
        'css/devreg/submit.less',
        'css/devreg/tabs.less',

        # Developer Log In / Registration.
        'css/devreg/login.less',

        # Footer.
        'css/devreg/footer.less',
    ),
    'mkt/reviewers': (
        'css/zamboni/editors.css',
        'css/devreg/consumer-buttons.less',
        'css/devreg/ratings.less',
        'css/devreg/data-grid.less',
        'css/devreg/reviewers.less',
        'css/devreg/themes_review.less',
        'css/devreg/legacy-paginator.less',
        'css/devreg/files.less',
    ),
    'mkt/splash': (
        'css/mkt/splash.styl',
    ),
    'mkt/consumer': (
        'css/mkt/reset.styl',
        'css/mkt/typography.styl',
        'css/mkt/site.styl',
        'css/mkt/banners.styl',
        'css/mkt/forms.styl',
        'css/mkt/header.styl',
        'css/mkt/account-links.styl',
        'css/mkt/buttons.styl',
        'css/mkt/tile.styl',
        'css/mkt/notification.styl',
        'css/mkt/detail.styl',
        'css/mkt/ratings.styl',
        'css/mkt/abuse.styl',
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
    'mkt/offline': (
        'css/mkt/reset.styl',
        'css/mkt/site.styl',
        'css/mkt/header.styl',
        'css/mkt/buttons.styl',
        'css/mkt/offline.styl',
    ),
    'mkt/ecosystem': (
        'css/devreg/reset.less',
        'css/devreg/consumer-typography.less',
        'css/devreg/login.less',
        'css/devreg/forms.less',
        'css/ecosystem/landing.less',
        'css/ecosystem/documentation.less',
    ),
    'mkt/in-app-payments': (
        'css/devreg/reset.less',
        'css/devreg/consumer-typography.less',
        'css/devreg/buttons.less',
        'css/devreg/in-app-payments.less',
    ),
    'mkt/stats': (
        'css/devreg/legacy-paginator.less',
        'css/devreg/jquery-ui/jquery-ui-1.10.1.custom.css',
        'css/devreg/stats.less',
    ),
    'mkt/lookup': (
        'css/devreg/lookup-tool.less',
        'css/devreg/activity.less',
    ),
    'mkt/themes': (
        'css/devreg/themes.less',
    ),
    'mkt/gaia': (
        # Gaia building blocks.
        'css/gaia/action_menu.css',
    )
}

# Bundle extensions (e.g., desktop).
CSS.update({
    'mkt/consumer-desktop': CSS['mkt/consumer'] + (
        # TODO: Split components into individual, appropriate stylesheets.
        'css/mkt/desktop.styl',
        'css/mkt/desktop-tile.styl',
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
        'js/mkt/banners.js',
        'js/impala/serializers.js',
        'js/mkt/fragments.js',
        'js/mkt/navigation.js',
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

        'js/mkt/paginator.js',

        # Account settings.
        'js/mkt/account.js',
        'js/mkt/feedback.js',

        # Homepage.
        'js/mkt/home.js',

        # Detail page.
        'js/mkt/detail.js',
        'js/mkt/lightbox.js',
        'js/mkt/previews.js',

        # Ratings.
        'js/common/ratingwidget.js',
        'js/mkt/ratings.js',

        # Fix-up outgoing links.
        'js/mkt/outgoing_links.js',

        # Stick.
        'js/lib/stick.js',

        'js/mkt/prefetch.js',

        'js/mkt/user_state.js',

        'js/mkt/webactivities.js',
        'js/mkt/forms.js',

        # Module initialization.
        'js/mkt/consumer_init.js',
    ),
    'mkt/reviewers': (
        'js/lib/highcharts.src.js',
        'js/zamboni/storage.js',
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
    'mkt/themes': (
        'js/lib/jquery.hoverIntent.js',
        'js/zamboni/personas_core.js',
        'js/zamboni/personas.js',
        'js/mkt/themes.js',
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
