# A list of our CSS and JS assets for jingo-minify.

CSS = {
    'zamboni/css': (
        'css/legacy/main.css',
        'css/legacy/main-mozilla.css',
        'css/legacy/jquery-lightbox.css',
        'css/legacy/autocomplete.css',
        'css/zamboni/zamboni.css',
        'css/global/headerfooter.css',
        'css/zamboni/tags.css',
        'css/zamboni/tabs.css',
        'css/impala/formset.less',
        'css/impala/suggestions.less',
        'css/impala/header.less',
        'css/impala/moz-tab.css',
        'css/impala/footer.less',
        'css/impala/faux-zamboni.less',
        'css/impala/collection-stats.less',
        'css/zamboni/themes.less',
    ),
    'zamboni/files': (
        'css/lib/syntaxhighlighter/shCoreDefault.css',
        'css/zamboni/files.css',
    ),
    'zamboni/admin': (
        'css/zamboni/admin-django.css',
        'css/zamboni/admin-mozilla.css',
        'css/zamboni/admin_features.css',
        # Datepicker styles and jQuery UI core.
        'css/zamboni/jquery-ui/custom-1.7.2.css',
    ),
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
        'css/devreg/menupicker.less',
    ),
    'mkt/splash': (
        'css/mkt/splash.less',
    ),
    'mkt/consumer': (
        'css/mkt/reset.less',
        'css/mkt/typography.less',
        'css/mkt/site.less',
        'css/mkt/banners.less',
        'css/mkt/forms.less',
        'css/mkt/header.less',
        'css/mkt/buttons.less',
        'css/mkt/tile.less',
        'css/mkt/notification.less',
        'css/mkt/detail.less',
        'css/mkt/ratings.less',
        'css/mkt/abuse.less',
        'css/mkt/categories.less',
        'css/mkt/menu.less',
        'css/mkt/infobox.less',
        'css/mkt/promo-grid.less',
        'css/mkt/overlay.less',
        'css/mkt/search.less',
        'css/mkt/paginator.less',
        'css/mkt/suggestions.less',
        'css/mkt/account.less',
        'css/mkt/login.less',
        'css/mkt/purchase.less',
        'css/mkt/lightbox.less',
        'css/mkt/filters.less',
    ),
    'mkt/offline': (
        'css/mkt/reset.less',
        'css/mkt/site.less',
        'css/mkt/header.less',
        'css/mkt/buttons.less',
        'css/mkt/offline.less',
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
}

# Bundle extensions (e.g., desktop).
CSS.update({
    'mkt/consumer-desktop': CSS['mkt/consumer'] + (
        # TODO: Split components into individual, appropriate stylesheets.
        'css/mkt/desktop.less',
        'css/mkt/desktop-tile.less',
        'css/mkt/desktop-header.less',
        'css/mkt/desktop-account-links.less',
        'css/mkt/desktop-filters.less',
        'css/mkt/desktop-forms.less',
        'css/mkt/desktop-account.less',
        'css/mkt/desktop-listing.less',
        'css/mkt/desktop-details.less',
        'css/mkt/desktop-ratings.less',
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

        'js/mkt/gettext.js',
        'js/mkt/tracking.js',
        'js/mkt/modal.js',
        'js/mkt/overlay.js',
        'js/mkt/capabilities.js',
        'js/devreg/init.js',  # This one excludes buttons initialization, etc.
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
        'js/mkt/apps.js',
        'js/mkt/payments.js',
        'js/mkt/install.js',
        'js/mkt/buttons.js',
        'js/mkt/reviewers.js',
        'js/devreg/menupicker.js',
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
