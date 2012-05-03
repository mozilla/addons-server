(function() {
    function getButton(product) {
        // Look up button by its manifest URL.
        return $(format('.button[data-manifestUrl="{0}"]', product.manifestUrl));
    }

    function setButton($button, text, cls) {
        if (cls == 'purchasing' || cls == 'installing') {
            // Save the old text of the button if we know we may revert later.
            $button.data('old-text', $button.html());
        }
        $button.html(text);
        if (!(cls == 'purchasing' || cls == 'installing')) {
            $button.removeClass('purchasing installing');
        }
        $button.addClass(cls);
    }

    function revertButton($button) {
        // Cancelled install/purchase. Roll back button to its previous state.
        $button.removeClass('purchasing installing error');
        if ($button.data('old-text')) {
            $button.html($button.data('old-text'));
        }
    }

    $(window).bind('app_purchase_start', function(e, product) {
        setButton(getButton(product), gettext('Purchasing&hellip;'), 'purchasing');
    }).bind('app_purchase_success', function(e, product) {
        setButton(getButton(product), gettext('Purchased'), 'purchased');
    }).bind('app_install_start', function(e, product) {
        var $button = getButton(product);
        setButton(getButton(product), gettext('Installing&hellip;'), 'installing');
    }).bind('app_install_success', function(e, product) {
        setButton(getButton(product), gettext('Installed'), 'installed');
    }).bind('app_purchase_error app_install_error', function(e, product, msg) {
        var $button = getButton(product),
            errSummary;

        // From the old apps.js
        switch (msg) {
            case 'DENIED':
                errSummary = gettext('App installation not allowed.');
                break;
            case 'MANIFEST_URL_ERROR':
                errSummary = gettext('App manifest is malformed.');
                break;
            case 'NETWORK_ERROR':
                errSummary = gettext('App host could not be reached.');
                break;
            case 'MANIFEST_PARSE_ERROR':
                errSummary = gettext('App manifest is unparsable.');
                break;
            case 'INVALID_MANIFEST':
                errSummary = gettext('App manifest is invalid.');
                break;
            default:
                errSummary = gettext('Unknown error.');
                break;
        }

        if (msg) {
            setButton($button, gettext('Error'), 'error');
            var $overlay = $('<div id="install-error" class="overlay"></div>');
            $overlay.append('<section><h3>' + gettext('Error') + '</h3><p>' +
                            errSummary + '</p></section>');
            $('#install-error').remove();
            $('body').append($overlay);
            $overlay.addClass('show');
        } else {
            // Cancelled install. Roll back.
            revertButton($button);
        }
    }).bind('buttons.overlay_dismissed', function() {
        // Dismissed error. Roll back.
        revertButton($('.button.error'));
    }).bind('app_install_disabled', function(e, product) {
        // You're not using a compatible browser.
        var $button = $('.button.product');
        setButton($button, $button.html(), 'disabled');
        $button.parent().append($('#noApps').html());
    });
})();
