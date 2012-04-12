// Hey there! I know how to install apps. Buttons are dumb now.

(function() {
    z.page.on('click', '.button.product', clickHandler);

    function clickHandler(e) {
        e.preventDefault();
        e.stopPropagation();
        var product = $(this).data('product');
        startInstall(product);
    }

    function startInstall(product) {
        if (z.anonymous) {
            localStorage.setItem('toInstall', product.manifestUrl);
            $(window).trigger('login');
            return;
        }
        if (product.isPurchased || !product.price) {
            install(product);
            return;
        }
        if (product.price) {
            purchase(product);
        }
    }

    function purchase(product) {
        $(window).trigger('app_purchase_start', product);
        $.when(z.payments.purchase(product))
         .done(purchaseSuccess)
         .fail(purchaseError);
    }

    function purchaseSuccess(product, receipt) {
        // Firefox doesn't successfully fetch the manifest unless I do this.
        setTimeout(function() {
            install(product);
        }, 0);
    }

    function purchaseError(product, msg) {
        $(window).trigger('app_purchase_error', product, msg);
    }

    function install(product, receipt) {
        var data = {};
        $(window).trigger('app_install_start', product);
        $.post(product.recordUrl).success(function(response) {
            if (response.receipt) {
                data.receipt = response.receipt;
            }
            $.when(apps.install(product, data))
             .done(installSuccess)
             .fail(installError);
        }).error(function(response) {
            // Could not record/generate receipt!
            installError(product);
        });
    }

    function installSuccess(product) {
        $(window).trigger('app_install_success', product);
    }

    function installError(product, msg) {
        $(window).trigger('app_install_error', product, msg);
    }

    $(function() {
        if (localStorage.getItem('toInstall')) {
            var lsVal = localStorage.getItem('toInstall');
            localStorage.removeItem('toInstall');
            var product = $(format('.button[data-manifestUrl="{0}"]',
                                   lsVal)).data('product');
            if (product) {
                startInstall(product);
            }
        }
    });
})();
