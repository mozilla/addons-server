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
        'css/devreg/paginator.less',

        # Buttons (used for paginator, "Edit" buttons, Refunds page).
        'css/devreg/buttons.less',

        # Popups, Modals, Tooltips.
        'css/devreg/devhub-popups.less',
        'css/devreg/tooltips.less',

        # L10n menu ("Localize for ...").
        'css/devreg/l10n.less',

        # Forms (used for tables on "Manage ..." pages).
        'css/common/forms.less',
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
        'css/common/invisible-upload.less',

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
    'mkt/reviewers': (
        'css/mkt/reviewers.less',
    ),
    'mkt/consumer': (
        'css/mkt/reset.less',
        'css/mkt/typography.less',
        'css/mkt/site.less',
        'css/common/invisible-upload.less',
        'css/common/forms.less',
        'css/mkt/forms.less',
        'css/mkt/header.less',
        'css/mkt/breadcrumbs.less',
        'css/mkt/buttons.less',
        'css/mkt/detail.less',
        'css/mkt/slider.less',
        'css/mkt/overlay.less',
        'css/mkt/search.less',
        'css/mkt/paginator.less',
        'css/mkt/suggestions.less',
        'css/mkt/support.less',
        'css/mkt/account.less',
        'css/mkt/account-purchases.less',
        'css/mkt/home.less',
        'css/mkt/login.less',
        'css/mkt/purchase.less',
        'css/devreg/l10n.less',
    ),
    'mkt/in-app-payments': (
        'css/mkt/reset.less',
        'css/mkt/typography.less',
        'css/mkt/buttons.less',
        'css/mkt/in-app-payments.less',
    ),
    'mkt/in-app-payments-proto': (
        # Temporarily re-using PayPal styles for in-app-payments UI
        # until we actually have a UI.
        'css/impala/base.css',
        'css/legacy/jquery-lightbox.css',
        'css/impala/site.less',
        'css/impala/typography.less',
        'css/global/headerfooter.css',
        'css/impala/forms.less',
        'css/impala/header.less',
        'css/impala/footer.less',
        'css/impala/moz-tab.css',
        'css/impala/hovercards.less',
        'css/impala/toplist.less',
        'css/impala/carousel.less',
        'css/impala/reviews.less',
        'css/impala/buttons.less',
        'css/impala/promos.less',
        'css/impala/addon_details.less',
        'css/impala/policy.less',
        'css/impala/expando.less',
        'css/impala/popups.less',
        'css/impala/l10n.less',
        'css/impala/contributions.less',
        'css/impala/lightbox.less',
        'css/impala/prose.less',
        'css/impala/sharing.less',
        'css/impala/abuse.less',
        'css/impala/paginator.less',
        'css/impala/listing.less',
        'css/impala/versions.less',
        'css/impala/users.less',
        'css/impala/collections.less',
        'css/impala/tooltips.less',
        'css/impala/search.less',
        'css/impala/suggestions.less',
        'css/impala/colorpicker.less',
        'css/impala/personas.less',
        'css/impala/login.less',
        'css/impala/dictionaries.less',
        'css/impala/apps.less',
        'css/impala/formset.less',
        'css/impala/tables.less',
        'css/impala/compat.less',
        'css/impala/localizers.less',
        'css/mkt/in-app-payments-proto.less',
    ),
    'mkt/stats': (
        'css/mkt/stats.less',
    ),
}

JS = {
    'mkt/devreg': (
        'js/lib/jquery-1.6.4.js',
        'js/lib/underscore.js',
        'js/zamboni/browser.js',
        'js/amo2009/addons.js',
        'js/devreg/init.js',  # This one excludes buttons initialization, etc.
        'js/impala/capabilities.js',
        'js/lib/format.js',
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
        'js/common/upload-image.js',

        # New stuff.
        'js/devreg/devhub.js',
        'js/devreg/submit-details.js',

        # Specific stuff for making payments nicer.
        'js/devreg/paypal.js',
        'js/zamboni/validator.js',
    ),
    'mkt/consumer': (
        'js/lib/jquery-1.7.1.js',
        'js/lib/underscore.js',
        'js/lib/format.js',
        'js/mkt/init.js',
        'js/mkt/utils.js',
        'js/mkt/browserid.js',
        'js/zamboni/truncation.js',
        'js/common/keys.js',
        'js/mkt/capabilities.js',
        'js/mkt/fragments.js',
        'js/mkt/overlay.js',
        'js/mkt/slider.js',
        'js/mkt/login.js',
        'js/mkt/install.js',
        'js/mkt/payments.js',
        'js/mkt/buttons.js',
        'js/mkt/search.js',
        'js/mkt/apps.js',
        'js/zamboni/outgoing_links.js',
        'js/common/upload-image.js',

        # Search suggestions.
        'js/impala/ajaxcache.js',
        'js/impala/suggestions.js',

        # Account settings.
        'js/mkt/account.js',
    ),
    'mkt/stats': (
        'js/zamboni/storage.js',
        'js/mkt/modal.js',
        'js/lib/jquery-datepicker.js',
        'js/lib/highcharts.src.js',
        'js/impala/stats/csv_keys.js',
        'js/impala/stats/helpers.js',
        'js/impala/stats/dateutils.js',
        'js/impala/stats/manager.js',
        'js/impala/stats/controls.js',
        'js/impala/stats/overview.js',
        'js/impala/stats/topchart.js',
        'js/impala/stats/chart.js',
        'js/impala/stats/table.js',
        'js/impala/stats/stats.js',
    ),
    'mkt/in-app-payments': (
        'js/lib/jquery-1.7.1.js',
        'js/mkt/inapp_payments.js',
        'js/mkt/browserid.js',
        'js/mkt/login.js',
    ),
    'mkt/in-app-payments-proto': (
        'js/mkt/inapp_payments_proto.js',
    ),
}
