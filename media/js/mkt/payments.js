(function() {

    var overlay = $('#pay'),
        paymentsTemplate = template($('#pay-template').html()),
        product,
        purchaseInProgress = true,
        $def,
        message = $('#purchased'),
        messageTemplate = template(message.html()),
        data = {};

    function beginPurchase(prod) {
        if (!prod) return;
        if ($def && $def.state() == 'pending') {
            $def.reject(product, 'collision');
            return;
        }
        $def = $.Deferred();
        product = prod;

        // If the user is pre-authed, just call PayPal right away.
        if (z.pre_auth) {
            startPayment();
            return $def.promise();
        }

        if (product.currencies) {
            initCurrencies(JSON.parse(product.currencies));
        }

        overlay.html(paymentsTemplate(product));
        overlay.addClass('show');
        $(window).bind('keypress.payments', function(e) {
            if (e.keyCode == z.keys.ESCAPE) {
                cancelPurchase();
            }
        }).bind('overlay_dismissed', function(e) {
            cancelPurchase();
        });

        overlay.on('click.payments', '#pre-approval', beginPreApproval);
        overlay.on('click.payments', '#payment-confirm', startPayment);
        overlay.on('click.payments', '#pay .close', cancelPurchase);

        return $def.promise();
    }

    function initCurrencies(clist) {
        var $list = $('<ul id="currency-list"></ul>'),
            $trigger = $(format('<a href="#">{0}</a>', gettext('Currency'))),
            $item;

        for (var currency in clist) {
            $item = $(format('<li><a href="#">{0} ({1})</a></li>', currency,
                             clist[currency]));
            $list.append($item);
        }

        // Yea...(race condition).
        setTimeout(function() {
            $('.product-details .price').append($trigger, $list);
            initCurrencyEvents($trigger, $list);
        }, 0);
    }

    function initCurrencyEvents($trigger, $list) {
        var $price = $('#price-display');

        $trigger.unbind('click').click(_pd(function(e) {
            $list.addClass('show');
        }));

        $('#pay').unbind('click.currency')
                 .on('click.currency', _pd(function(e) {
            var $targ = $(e.target);

            if ($targ.parents('#currency-list').length ||
                $targ.parent('.price').length) {
                var sel = $targ.html().split(' ');

                if ($targ.html() != $trigger.html()) {
                    sel[1] = sel[1].replace('\(', '').replace('\)', '');

                    // Feel free to remove.
                    console.log('Setting currency to: ', sel[0]);
                    data.currency = sel[0];
                    $('#price-display').html(sel[1]);
                    $list.removeClass('show');
                }
            } else {
                $list.removeClass('show');
            }
        }));
    }

    function beginPreApproval(e) {
        localStorage.setItem('toInstall', product.manifestUrl);
    }

    function cancelPurchase(e) {
        if (e && e.preventDefault) e.preventDefault();
        $def.reject(product, 'cancelled');
        $(window).unbind('.payments');
        overlay.unbind('.payments');
        overlay.removeClass('show');
        $('#currency-list').removeClass('show');
    }

    function completePurchase() {
        console.log('completing purchase of ', product);
        if (!product) {
            console.log('somehow we don\'t have a product!');
        }
        $(window).unbind('.payments');
        overlay.unbind('.payments');
        overlay.removeClass('show');
        $('#currency-list').removeClass('show');
        message.html(messageTemplate(product));
        message.toggle();
        $def.resolve(product);
    }

    function startPayment(e) {
        if (e && e.preventDefault) e.preventDefault();
        $.when(doPaypal(product))
         .then(completePurchase);
    }

    function doPaypal() {
        var $def = $.Deferred();
        $(window).bind('purchasecomplete.payments', function() {
            $def.resolve();
        });

        $(window).bind('purchaseerror.payments', function(e, p, error) {
            $('#pay-error').show().find('div').text(error);
            cancelPurchase();
        });

        $.post(product.purchase, data, function(response) {
            if (response.error) {
                $(window).trigger('purchaseerror', [product, response.error]);
            }
            else if (response.status == 'COMPLETED') {
                // If the response from pre-auth was good,
                // then just jump to the next step.
                $def.resolve();
            } else {
                // This will show if the user is not pre-authed
                // or for some reason the pre-auth failed.
                dgFlow = new PAYPAL.apps.DGFlow({expType: 'mini', trigger: '#page'});
                dgFlow.startFlow(response.url);
                overlay.removeClass('show');
                // Scroll to top of PayPal modal.
                var offset = $('iframe[name=PPDGFrame]').offset().top;
                if (offset > 9) {
                    $(document.documentElement).animate({scrollTop: offset}, 1000);
                }
                // When PayPal modal gets dismissed, reset install button.
                var intVal = setInterval(function() {
                    if (!dgFlow.isOpen()) {
                        clearInterval(intVal);
                        cancelPurchase();
                        return;
                    }
                }, 1000);
            }
        });
        return $def.promise();
    }

    z.payments = {
        'purchase': beginPurchase
    };
})();
