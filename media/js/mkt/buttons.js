(function() {
    function getButton(product) {
        // Look up button by its manifest URL.
        return $(format('.button[data-manifest_url="{0}"]', product.manifest_url));
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

    if (!(navigator.mozApps && navigator.mozApps.installPackage)) {
        // disable packaged apps if we can't install them
        $('.button.product:not([disabled])').each(function() {
            var $this = $(this);
            if ($this.data('is_packaged')) {
                $this.attr('disabled', true).addClass('incompatible disabled');
            }
        });
    }

    z.doc.bind('app_purchase_start', function(e, product) {
        setButton(getButton(product), gettext('Purchasing'), 'purchasing');
    }).bind('app_purchase_success', function(e, product) {
        var $button = getButton(product);

        product['isPurchased'] = true;

        setButton($button, gettext('Purchased'), 'purchased');
    }).bind('app_install_start', function(e, product) {
        var $button = getButton(product);
        setButton($button, '<span class="spin"></span>',
                  'installing');

        // Reset button if it's been 30 seconds without user action.
        setTimeout(function() {
            if ($button.hasClass('installing')) {
                revertButton($button);
            }
        }, 30000);
    }).bind('app_install_success', function(e, installer, product, installedNow) {
        var $button = getButton(product);
        if (installedNow) {
            var $installed = $('#installed');
            if ($installed.length) {
                $how = $installed.find('.' + z.nav.platform);
                // Supported: Mac, Windows, or Linux.
                if ($how.length) {
                    $installed.show();
                    $how.show();
                }
            }
        }
        z.apps[product.manifest_url] = z.state.mozApps[product.manifest_url] = installer;
        setButton($button, gettext('Launch'), 'launch install');
    }).bind('app_purchase_error app_install_error', function(e, installer, product, msg) {
        var $button = getButton(product),
            errSummary;

        // TODO: We should remove this eventually.
        console.log('Error code:', msg);
        errSummary = apps.lookupError(msg);

        if (msg == 'MKT_CANCELLED' || msg == 'DENIED') {
            msg = 'cancelled';
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
                $button.trigger('notify', {
                    title: gettext('Error'),
                    msg: errSummary
                });
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
