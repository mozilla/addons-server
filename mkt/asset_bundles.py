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
        'css/devreg/header.less',

        # Item rows (used on Dashboard).
        'css/devreg/listing.less',
        'css/mkt/paginator.less',

        # Buttons (used for paginator, "Edit" buttons, Refunds page).
        'css/devreg/buttons.less',

        # Popups, Modals, Tooltips.
        'css/mkt/overlay.less',
        'css/devreg/devhub-popups.less',
        'css/mkt/device.less',
        'css/devreg/tooltips.less',

        # L10n menu ("Localize for ...").
        'css/devreg/l10n.less',

        # Forms (used for tables on "Manage ..." pages).
        'css/common/forms.less',
        'css/devreg/devhub-forms.less',

        # Tables.
        'css/mkt/data-grid.less',

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
        'css/common/invisible-upload.less',

        # Submission.
        'css/devreg/submit-progress.less',
        'css/devreg/submit-terms.less',
        'css/devreg/submit-manifest.less',
        'css/devreg/submit-details.less',
        'css/devreg/validation.less',
        'css/devreg/submit.less',
        'css/devreg/tabs.less',
        'css/impala/personas.less',
        'css/impala/colorpicker.less',

        # Developer Log In / Registration.
        'css/devreg/login.less',
        'css/mkt/login.less',

        # Footer.
        'css/devreg/footer.less',
    ),
    'mkt/reviewers': (
        'css/mkt/buttons.less',
        'css/mkt/ratings.less',
        'css/mkt/data-grid.less',
        'css/mkt/reviewers.less',
        'css/mkt/themes_review.less',
        'css/mkt/paginator.less',
        'css/mkt/files.less',
    ),
    'mkt/splash': (
        'css/mkt/splash.less',
    ),
    'mkt/consumer': (
        'css/mkt/reset.less',
        'css/mkt/typography.less',
        'css/mkt/site.less',
        'css/mkt/banners.less',
        'css/common/invisible-upload.less',
        'css/common/forms.less',
        'css/mkt/forms.less',
        'css/mkt/header.less',
        'css/mkt/navigation.less',
        'css/mkt/breadcrumbs.less',
        'css/mkt/buttons.less',
        'css/mkt/tile.less',
        'css/mkt/notification.less',
        'css/mkt/detail.less',
        'css/mkt/ratings.less',
        'css/mkt/device.less',
        'css/mkt/abuse.less',
        'css/mkt/categories.less',
        'css/mkt/menu.less',
        'css/mkt/infobox.less',
        'css/mkt/promo-grid.less',
        'css/mkt/overlay.less',
        'css/mkt/search.less',
        'css/mkt/paginator.less',
        'css/mkt/suggestions.less',
        'css/mkt/support.less',
        'css/mkt/account.less',
        'css/mkt/account-purchases.less',
        'css/mkt/login.less',
        'css/mkt/purchase.less',
        'css/devreg/l10n.less',
        'css/mkt/lightbox.less',
        'css/mkt/browse.less',
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
        'css/mkt/reset.less',
        'css/mkt/typography.less',
        'css/mkt/login.less',
        'css/mkt/forms.less',
        'css/ecosystem/landing.less',
        'css/ecosystem/documentation.less',
    ),
    'mkt/in-app-payments': (
        'css/mkt/reset.less',
        'css/mkt/typography.less',
        'css/mkt/buttons.less',
        'css/mkt/in-app-payments.less',
    ),
    'mkt/stats': (
        'css/mkt/stats.less',
    ),
    'mkt/lookup': (
        'css/mkt/lookup-tool.less',
        'css/mkt/activity.less',
    ),
    'mkt/themes': (
        'css/mkt/themes.less',
    ),
}

# Bundle extensions (e.g., desktop).
CSS.update({
    'mkt/consumer-desktop': CSS['mkt/consumer'] + (
        # TODO: Split components into individual, appropriate stylesheets.
        'css/devreg/footer.less',
        'css/mkt/desktop.less',
        'css/mkt/desktop-tile.less',
        'css/mkt/desktop-header.less',
        'css/mkt/desktop-filters.less',
        'css/mkt/desktop-forms.less',
        'css/mkt/desktop-account.less',
        'css/mkt/desktop-listing.less',
        'css/mkt/desktop-details.less',
        'css/mkt/desktop-ratings.less',
    ),
})

CSS.update({
    # Mobile.
    'mkt/consumer-sen': CSS['mkt/consumer'] + (
        'css/mkt/carriers-sen.less',
    ),
    # Desktop.
    'mkt/consumer-desktop-sen': CSS['mkt/consumer-desktop'] + (
        'css/mkt/carriers-sen.less',
        'css/mkt/desktop-carriers-sen.less',
    ),
})

JS = {
    'mkt/devreg': (
        # tiny module loader
        'js/lib/amd.js',

        'js/lib/jquery-1.7.1.js',
        'js/lib/underscore.js',
        'js/zamboni/browser.js',
        'js/amo2009/addons.js',
        'js/mkt/tracking.js',
        'js/devreg/init.js',  # This one excludes buttons initialization, etc.
        'js/mkt/capabilities.js',
        'js/lib/format.js',
        'js/lib/jquery.cookie.js',
        'js/zamboni/storage.js',
        'js/zamboni/tabs.js',
        'js/common/keys.js',
        'js/impala/serializers.js',
        'js/mkt/utils.js',
        'js/mkt/browserid.js',
        'js/mkt/login.js',
        'js/mkt/notification.js',

        # jQuery UI.
        'js/lib/jquery-ui/jquery.ui.core.js',
        'js/lib/jquery-ui/jquery.ui.position.js',
        'js/lib/jquery-ui/jquery.ui.widget.js',
        'js/lib/jquery-ui/jquery.ui.mouse.js',
        'js/lib/jquery-ui/jquery.ui.autocomplete.js',
        'js/lib/jquery-ui/jquery.ui.datepicker.js',
        'js/lib/jquery-ui/jquery.ui.sortable.js',

        'js/lib/truncate.js',
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
        'js/common/upload-base.js',
        'js/common/upload-packaged-app.js',
        'js/common/upload-image.js',

        # New stuff.
        'js/devreg/devhub.js',
        'js/devreg/submit.js',
        'js/devreg/tabs.js',
        'js/devreg/edit.js',
        'js/impala/persona_creation.js',
        'js/lib/jquery.minicolors.js',

        # Specific stuff for making payments nicer.
        'js/devreg/payments.js',
        'js/zamboni/validator.js',
        'js/mkt/overlay.js',

        # Module initialization.
        'js/devreg/devreg_init.js',
    ),
    'mkt/consumer': (
        # tiny module loader
        'js/lib/amd.js',

        'js/lib/jquery-1.8.js',
        'js/lib/jquery.cookie.js',
        'js/lib/underscore.js',
        'js/lib/format.js',

        # slider lib
        'js/lib/flipsnap.js',

        'js/mkt/tracking.js',
        'js/mkt/utils.js',
        'js/lib/csrf.js',
        'js/zamboni/browser.js',
        'js/mkt/init.js',
        'js/mkt/browserid.js',
        'js/lib/truncate.js',
        'js/zamboni/truncation.js',
        'js/common/keys.js',
        'js/mkt/capabilities.js',
        'js/mkt/banners.js',
        'js/impala/serializers.js',
        'js/mkt/fragments.js',
        'js/mkt/navigation.js',
        'js/mkt/recaptcha.js',
        'js/mkt/overlay.js',
        'js/mkt/login.js',
        'js/mkt/install.js',
        'js/mkt/payments.js',
        'js/mkt/buttons.js',
        'js/mkt/search.js',
        'js/mkt/apps.js',
        'js/mkt/typography.js',

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

        # Module initialization.
        'js/mkt/consumer_init.js',
    ),
    'mkt/reviewers': (
        'js/lib/amd.js',
        'js/mkt/utils.js',
        'js/mkt/apps.js',
        'js/mkt/payments.js',
        'js/mkt/install.js',
        'js/mkt/buttons.js',
        'js/mkt/reviewers.js',
        'js/devreg/reviewers_init.js',
    ),
    'mkt/stats': (
        'js/zamboni/storage.js',
        'js/mkt/modal.js',
        'js/lib/jquery-datepicker.js',
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
        'js/lib/jquery-1.7.1.js',
        'js/mkt/inapp_payments.js',
        'js/lib/csrf.js',
        'js/impala/serializers.js',
        'js/mkt/browserid.js',
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
