// Hey there! I know how to install apps. Buttons are dumb now.

(function() {
    z.page.on('click', '.button', startInstall);

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
        install(product, receipt);
    }

    function purchaseError(product, msg) {
        console.log(product, msg);
    }

    function install(product, receipt) {
        // console.log('installing app '+product.name, product);
        $.when(apps.install(product.manifestUrl))
         .done(installSuccess)
         .fail(installError);
    }

    function installSuccess() {
        this.removeClass('install').addClass('installed');
        this.html('Installed');
    }

    function installError() {
        this.html(oldLabel);
    }
})();