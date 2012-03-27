// Hey there! I know how to install apps. Buttons are dumb now.

(function() {
    z.page.on('click', '.button.product', startInstall);

    function startInstall(e) {
        e.preventDefault();
        e.stopPropagation();
        var product = $(this).data('product');

        if (product.isPurchased || !product.price) {
            install(product);
            return;
        }
        if (product.price) {
            purchase(product);
        }
    }

    function purchase(product) {
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
    }

    function install(product, receipt) {
        var data = {};
        $.post(product.recordUrl).success(function(response) {
            if (response.receipt) {
                data.receipt = response.receipt;
            }
            $.when(apps.install(product.manifestUrl, data))
             .done(installSuccess)
             .fail(installError);
        }).error(function(response) {
            throw 'Could not record generate receipt!';
        });
    }

    function installSuccess(button, product) {
        // Don't do this if cancelled.
        //this.removeClass('install').addClass('installed');
        // Store in localStorage (based on user if authenticated)?
        //this.html('Installed');
    }

    function installError(button, product) {
        //button.html(oldLabel);
    }
})();
