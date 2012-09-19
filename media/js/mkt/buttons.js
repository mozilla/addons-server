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
        setButton(getButton(product), gettext('Purchasing'), 'purchasing');
    }).bind('app_purchase_success', function(e, product) {
        var $button = getButton(product),
            purchasedMark = '<span class="approval checkmark purchased">';
        purchasedMark += gettext('Purchased') + '</span>';
        product['isPurchased'] = true;

        // Remove "PayPal pre-approval" badge if it exists.
        var $aMark = $button.siblings('.checkmark');
        if ($aMark.length) {
            $aMark.remove();
        }

        // Add a "Purchased" badge.
        $button.data('product', product).after(purchasedMark);

        setButton($button, gettext('Purchased'), 'purchased');
    }).bind('app_install_start', function(e, product) {
        var $button = getButton(product);
        setButton($button, '<span class="spin"></span>',
                  'installing');

        // Reset button if we've clicked outside of the doorhanger (albeit twice).
        $(document.body).on('click', function() {
            revertButton($button);
        });

        // Reset button if it's been 30 seconds without user action.
        setTimeout(function() {
            if ($button.hasClass('installing')) {
                revertButton($button);
            }
        }, 30000);
    }).bind('app_install_success', function(e, product, installedNow) {
        var $button = getButton(product);
        if (installedNow) {
            var $installed = $('#installed'),
                $how = $installed.find('.' + z.nav.platform);
            // Supported: Mac, Windows, or Linux.
            if ($how.length) {
                $installed.show();
                $how.show();
            }
        }
        setButton($button, gettext('Installed'), 'installed');
    }).bind('app_purchase_error app_install_error', function(e, product, msg) {
        var $button = getButton(product),
            errSummary;

        // TODO: We should remove this eventually.
        console.log('Error code:', msg);

        switch (msg) {
            // mozApps error codes, defined in
            // https://developer.mozilla.org/en-US/docs/Apps/Apps_JavaScript_API/Error_object
            case 'MKT_CANCELLED':
            case 'DENIED':
                msg = 'cancelled';
                break;
            case 'MANIFEST_URL_ERROR':
                errSummary = gettext('The manifest could not be found at the given location.');
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
            // Marketplace specific error codes.
            case 'MKT_SERVER_ERROR':
                errSummary = gettext('Internal server error.');
                break;
            case 'MKT_INSTALL_ERROR':
                errSummary = gettext('Internal server error on app installation.');
                break;
            default:
                errSummary = gettext('Unknown error.');
                break;
        }

        if (msg && msg != 'cancelled') {
            var $btnContainer = $('.app-install');
            setButton($button, gettext('Error'), 'error');

            if ($btnContainer.length) { // Reviewers page.
                var $errList = $('<ul class="errorlist"></ul>');
                $errList.append(format('<li>{0}</li>', errSummary));
                $btnContainer.find('.errorlist').remove();
                $btnContainer.append($errList);
            } else {
                var $overlay = $('<div id="install-error" class="overlay"></div>');
                $overlay.append('<section><h3>' + gettext('Error') + '</h3><p>' +
                                errSummary + '</p></section>');
                $('#install-error').remove();
                $('body').append($overlay);
                $overlay.addClass('show');
            }
        } else {
            // Cancelled install. Roll back.
            revertButton($button);
        }
    }).bind('buttons.overlay_dismissed', function() {
        // Dismissed error. Roll back.
        revertButton($('.button.error'));
    }).bind('app_install_disabled', function(e, product) {
        // You're not using a compatible browser.
        var $button = $('.button.product'),
            $noApps = $('.no-apps'); // Reviewers page.

        setButton($button, $button.html(), 'disabled');

        if ($noApps.length) {
            $noApps.show();
        } else {
            $button.parent().append($('#noApps').html());
        }
    });
})();
