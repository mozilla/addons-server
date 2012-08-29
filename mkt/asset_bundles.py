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
        'css/devreg/devhub-popups.less',
        'css/mkt/device.less',
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
        'css/mkt/submit.less',

        # Developer Log In / Registration.
        'css/devreg/login.less',

        # Footer.
        'css/devreg/footer.less',
    ),
    'mkt/devreg-legacy': (
        'css/devreg-legacy/developers.less',  # Legacy galore.
    ),
    'mkt/reviewers': (
        'css/mkt/buttons.less',
        'css/mkt/ratings.less',
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
        'css/mkt/navigation.less',
        'css/mkt/breadcrumbs.less',
        'css/mkt/buttons.less',
        'css/mkt/tile.less',
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
        'css/impala/lightbox.less',
        'css/mkt/lightbox.less',
        'css/mkt/browse.less',
        'css/mkt/filters.less',
    ),
    'mkt/ecosystem': (
        'css/mkt/reset.less',
        'css/mkt/typography.less',
        'css/mkt/login.less',
        'css/ecosystem/site.less',
        'css/ecosystem/header.less',
        'css/ecosystem/buttons.less',
        'css/ecosystem/landing.less',
        'css/mkt/overlay.less',
        'css/ecosystem/documentation.less',
        'css/ecosystem/footer.less',
    ),
    'mkt/xtags': (
        '//raw.github.com/mozilla/xtag-elements/master/alert-popup/alert-popup.css',
        '//raw.github.com/mozilla/xtag-elements/master/dialog-toast/dialog-toast.css',
        '//raw.github.com/mozilla/xtag-elements/master/list-view/listview.css',
        '//raw.github.com/mozilla/xtag-elements/master/slidebox/slidebox.css',
        '//raw.github.com/mozilla/xtag-elements/master/slider/slider.css',
        '//raw.github.com/mozilla/xtag-elements/master/tabbox/tabbox.css',
        '//raw.github.com/mozilla/xtag-elements/master/select-list/select-list.css',
        '//raw.github.com/mozilla/xtag-elements/master/date-time-picker/date-time-picker.css',
        '//raw.github.com/mozilla/xtag-elements/master/dropdown-menu/dropdown-menu.css',
        '//raw.github.com/mozilla/xtag-elements/master/toggle-switch/toggle-switch.css',
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
    ),
    'mkt/themes': (
        'css/mkt/themes.less',
    ),
}

JS = {
    'mkt/devreg': (
        'js/lib/jquery-1.7.1.js',
        'js/lib/webtrends.js',
        'js/lib/underscore.js',
        'js/zamboni/browser.js',
        'js/amo2009/addons.js',
        'js/common/tracking.js',
        'js/devreg/init.js',  # This one excludes buttons initialization, etc.
        'js/mkt/capabilities.js',
        'js/lib/format.js',
        'js/lib/jquery.cookie.js',
        'js/zamboni/storage.js',
        'js/zamboni/tabs.js',
        'js/impala/serializers.js',

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
        'js/common/upload-base.js',
        'js/common/upload-packaged-app.js',
        'js/common/upload-image.js',

        # New stuff.
        'js/devreg/devhub.js',
        'js/devreg/submit-details.js',
        'js/devreg/edit.js',

        # Specific stuff for making payments nicer.
        'js/devreg/paypal.js',
        'js/zamboni/validator.js',
    ),
    'mkt/consumer': (
        'js/lib/jquery-1.8-nofx.js',
        'js/lib/webtrends.js',
        'js/lib/underscore.js',
        'js/lib/format.js',

        # slider lib
        'js/lib/flipsnap.js',

        'js/common/tracking.js',
        'js/mkt/utils.js',
        'js/lib/csrf.js',
        'js/zamboni/browser.js',
        'js/mkt/init.js',
        'js/mkt/browserid.js',
        'js/zamboni/truncation.js',
        'js/common/keys.js',
        'js/mkt/capabilities.js',
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
        'js/zamboni/outgoing_links.js',
        'js/common/upload-image.js',

        # Search suggestions.
        'js/impala/ajaxcache.js',
        'js/impala/suggestions.js',
        'js/impala/site_suggestions.js',

        # Account settings.
        'js/mkt/account.js',

        # Homepage.
        'js/mkt/home.js',

        # Detail page.
        'js/mkt/detail.js',
        'js/mkt/lightbox.js',
        'js/mkt/reviewsparks.js',
        'js/mkt/previews.js',

        # Ratings.
        'js/common/ratingwidget.js',
        'js/mkt/ratings.js',

        # Fix-up outgoing links.
        'js/mkt/outgoing_links.js',

        # Stick.
        'js/lib/stick.js',
    ),
    'mkt/reviewers': (
        'js/mkt/utils.js',
        'js/mkt/apps.js',
        'js/mkt/install.js',
        'js/mkt/buttons.js',
        'js/mkt/reviewers.js',
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
    'mkt/xtags': (
        '//raw.github.com/mozilla/x-tag/master/x-tag.js',
        '//raw.github.com/mozilla/xtag-elements/master/alert-popup/alert-popup.js',
        '//raw.github.com/mozilla/xtag-elements/master/dialog-toast/dialog-toast.js',
        '//raw.github.com/mozilla/xtag-elements/master/list-view/listview.js',
        '//raw.github.com/mozilla/xtag-elements/master/slidebox/slidebox.js',
        '//raw.github.com/mozilla/xtag-elements/master/slider/slider.js',
        '//raw.github.com/mozilla/xtag-elements/master/tabbox/tabbox.js',
        '//raw.github.com/mozilla/xtag-elements/master/select-list/select-list.js',
        '//raw.github.com/mozilla/xtag-elements/master/date-time-picker/date-time-picker.js',
        '//raw.github.com/mozilla/xtag-elements/master/dropdown-menu/dropdown-menu.js',
        '//raw.github.com/mozilla/xtag-elements/master/toggle-switch/toggle-switch.js',
        'js/mkt/xtag-demos.js',
    ),
}
