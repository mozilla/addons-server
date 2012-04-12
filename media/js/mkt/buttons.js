(function() {
    function getButton(product) {
        // Look up button by its manifest URL.
        return $(format('.button[data-manifestUrl="{0}"]', product.manifestUrl));
    }

    function setButton($button, text, cls) {
        if (cls == 'purchasing' || cls == 'installing') {
            // Save the old text of the button if we know we may revert later.
            $button.data('old-text', $button.html())
                   .data('old-font-size', $button.css('font-size'));
        }
        $button.html(text);
        if (cls == 'purchasing' || cls == 'installing') {
            // The text has changed, so do another linefit.
            $button.css('font-size', 14).linefit();
        } else {
            $button.removeClass('purchasing installing');
        }
        $button.addClass(cls);
    }

    function revertButton($button) {
        // Cancelled install/purchase. Roll back button to its previous state.
        $button.html($button.data('old-text'))
               .removeClass('purchasing');
        // The text has changed, so do another linefit.
        $button.css('font-size', $button.data('old-font-size')).linefit();
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
        var $button = getButton(product);
        if (msg) {
            setButton($button, gettext('Error'), 'error');
            alert(msg);
        } else {
            // Cancelled install. Roll back.
            revertButton($button);
        }
    });

    z.page.bind('fragmentloaded', function(e) {
        // Shrink text in buttons so everything fits on one line.
        $('.button').linefit();
    });
})();
