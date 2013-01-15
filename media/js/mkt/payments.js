(function() {

    var product,
        $def,
        simulateNavPay = $('body').data('simulate-nav-pay');

    var _giveUp;
    var _abortCheck = false;

    function waitForPayment($def, product, webpayJWT, contribStatusURL) {
        if (_abortCheck) {
            return;
        }
        var selfArgs = arguments;
        var nextCheck = window.setTimeout(function() {
            waitForPayment.apply(this, selfArgs);
        }, 2000);
        if (!_giveUp) {
            _giveUp = window.setTimeout(function() {
                _abortCheck = true;
                $def.reject(null, product, 'MKT_INSTALL_ERROR');
            }, 60000);
        }
        $.get(contribStatusURL)
            .done(function(result) {
                if (result.status == 'complete') {
                    window.clearTimeout(nextCheck);
                    window.clearTimeout(_giveUp);
                    $def.resolve(product);
                }
            })
            .fail(function() {
                $def.reject(null, product, 'MKT_SERVER_ERROR');
            });
    }

    if (simulateNavPay && !z.capabilities.navPay) {
        navigator.mozPay = function(jwts) {
            var request = {
                onsuccess: function() {
                    console.warning('handler did not define request.onsuccess');
                },
                onerror: function() {
                    console.warning('handler did not define request.onerror');
                }
            };
            console.log('STUB navigator.mozPay received', jwts);
            console.log('calling onsuccess() in 3 seconds...');
            window.setTimeout(function() {
                console.log('calling onsuccess()');
                request.onsuccess();
            }, 3000);
            return request;
        }
        console.log('stubbed out navigator.mozPay()');
    }

    function callNavPay($def, product, webpayJWT, contribStatusURL) {
        var request = navigator.mozPay([webpayJWT]);
        request.onsuccess = function() {
            waitForPayment($def, product, webpayJWT, contribStatusURL);
        }
        request.onerror = function() {
            $def.reject(null, product, 'MKT_CANCELLED');
        }
    }

    function beginPurchase(prod) {
        if (!prod) return;
        if ($def && $def.state() == 'pending') {
            $def.reject(null, product, 'collision');
            return;
        }
        $def = $.Deferred();
        product = prod;

        if (z.capabilities.navPay || simulateNavPay) {
            $.post(product.prepareNavPay, {})
                .fail(function() {
                    $def.reject(null, product, 'MKT_SERVER_ERROR');
                })
                .done(function(result) {
                    callNavPay($def, product, result.webpayJWT, result.contribStatusURL);
                });

        } else {
            $def.reject(null, product, 'MKT_CANCELLED');
        }

        return $def.promise();
    }

    z.payments = {
        'purchase': beginPurchase
    };
})();
