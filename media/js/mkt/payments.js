(function() {

    var overlay = $('#pay'),
        paymentsTemplate = template(overlay.html()),
        product,
        purchaseInProgress = true,
        $def;

    // Check for/clear any paypal results
    (function() {
        var winTop = window.top,
            top_opener = winTop.opener || winTop;
            top_dgFlow = top_opener.dgFlow;
        if (top_dgFlow) {
            top_opener.jQuery(top_opener).trigger('purchasecomplete');
            top_dgFlow.closeFlow();
        }
    })();

    function beginPurchase(prod) {
        if ($def && $def.state() == 'pending') {
            $def.reject(product, 'collision');
            return;
        }
        $def = $.Deferred();
        product = prod;
        // console.log('beginning payment for ' + product.name, product);

        overlay.html(paymentsTemplate(product));
        overlay.addClass('show');
        $(window).bind('keypress.payments', function(e) {
            if (e.keyCode == z.keys.ESCAPE) {
                cancelPurchase();
            }
        });
        // TODO: allow multiple payment systems
        overlay.on('click.payments', '#payment-confirm', startPayment);
        overlay.on('click.payments', '#payment-cancel', cancelPurchase);

        return $def.promise();
    }

    function cancelPurchase(e) {
        if (e && e.preventDefault) e.preventDefault();
        $def.reject(product, 'cancelled');
        $(window).unbind('.payments');
        overlay.unbind('.payments');
        overlay.removeClass('show');
    }

    function completePurchase() {
        $(window).unbind('.payments');
        overlay.unbind('.payments');
        overlay.removeClass('show');
        $def.resolve(product);
    }

    function startPayment(e) {
        if (e && e.preventDefault) e.preventDefault();
        $.when(doPaypal(product))
         .then(completePurchase);
    }

    function doPaypal() {
        var $def = $.Deferred();
        $.post(product.purchase, function(response) {
            dgFlow = new PAYPAL.apps.DGFlow({trigger: '#page'});
            dgFlow.startFlow(response.url);
        });
        $(window).bind('purchasecomplete.payments',function() {
            $def.resolve();
        });
        return $def.promise();
    }

    z.payments = {
        'purchase': beginPurchase
    };
})();