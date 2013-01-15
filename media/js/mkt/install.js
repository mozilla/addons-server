// Hey there! I know how to install apps. Buttons are dumb now.

define('install', ['capabilities', 'payments'], function(caps, payments) {
    z.page.on('click', '.product.launch', launchHandler);
    z.page.on('click', '.button.product:not(.launch):not(.incompatible)', installHandler);

    function launchHandler(e) {
        e.preventDefault();
        e.stopPropagation();
        var product = $(this).closest('[data-product]').data('product');
        z.apps[product.manifest_url].launch();
    }

    function installHandler(e) {
        e.preventDefault();
        e.stopPropagation();
        var product = $(this).closest('[data-product]').data('product');
        startInstall(product);
    }

    function startInstall(product) {
        if (z.anonymous && (!z.allowAnonInstalls || product.price)) {
            localStorage.setItem('toInstall', product.manifest_url);
            $(window).trigger('login');
            return;
        }
        // Show "Install" button if I'm installing from the Reviewer Tools,
        // I already purchased this, or if it's free!
        if (location.pathname.indexOf('/reviewers/') > -1 ||
            product.isPurchased || !product.price) {
            install(product);
            return;
        }
        if (product.price) {
            purchase(product);
        }
    }

    function purchase(product) {
        $(window).trigger('app_purchase_start', product);
        $.when(payments.purchase(product))
         .done(purchaseSuccess)
         .fail(purchaseError);
    }

    function purchaseSuccess(product, receipt) {
        // Firefox doesn't successfully fetch the manifest unless I do this.
        $(window).trigger('app_purchase_success', [product]);
        setTimeout(function() {
            install(product);
        }, 0);
    }

    function purchaseError(product, msg) {
        $(window).trigger('app_purchase_error', [product, msg]);
    }

    function install(product, receipt) {
        var data = {};
        var post_data = {
            src: product.src,
            device_type: caps.getDeviceType()
        };
        if (caps.chromeless) {
            post_data.chromeless = 1;
        }

        $(window).trigger('app_install_start', product);
        $.post(product.recordUrl, post_data).success(function(response) {
            if (response.error) {
                $('#pay-error').show().find('div').text(response.error);
                installError(product);
                return;
            }
            if (response.receipt) {
                data.data = {'receipts': [response.receipt]};
            }
            $.when(apps.install(product, data))
             .done(installSuccess)
             .fail(installError);
        }).error(function(response) {
            // Could not record/generate receipt!
            installError(null, product);
        });
    }

    function installSuccess(installer, product) {
        $(window).trigger('app_install_success', [installer, product, true]);
    }

    function installError(installer, product, msg) {
        $(window).trigger('app_install_error', [installer, product, msg]);
    }

    $(function() {
        if (localStorage.getItem('toInstall')) {
            var lsVal = localStorage.getItem('toInstall');
            localStorage.removeItem('toInstall');
            var product = $(format('.button[data-manifest_url="{0}"]',
                                   lsVal)).data('product');
            if (product) {
                startInstall(product);
            }
        }
    });
});
