# A list of our CSS and JS assets for jingo-minify.

CSS = {
    'mkt/devreg': (
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
    'mkt': (
        'css/mkt/reset.less',
        'css/mkt/typography.less',
        'css/mkt/site.less',
        'css/mkt/forms.less',
        'css/mkt/header.less',
        'css/mkt/buttons.less',
        'css/mkt/detail.less',
        'css/mkt/slider.less',
        'css/mkt/overlay.less',
        'css/mkt/search.less',
        'css/mkt/paginator.less',
    ),
    'marketplace-experiments': (
        'marketplace-experiments/css/reset.less',
        'marketplace-experiments/css/site.less',
        'marketplace-experiments/css/header.less',
        'marketplace-experiments/css/detail.less',
        'marketplace-experiments/css/buttons.less',
        'marketplace-experiments/css/slider.less',
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
    'mkt': (
        'js/lib/jquery-1.7.1.js',
        'js/lib/underscore.js',
        'js/mkt/init.js',
        'js/mkt/capabilities.js',
        'js/mkt/fragments.js',
        'js/mkt/slider.js',
        'js/mkt/install.js',
        'js/mkt/search.js',
        'js/mkt/apps.js',
    ),
    'marketplace-experiments': (
        'js/marketplace-experiments/jquery-1.7.1.min.js',
        'js/marketplace-experiments/slider.js',
    ),
}
