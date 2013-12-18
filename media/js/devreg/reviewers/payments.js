define('payments', ['capabilities', 'notification'], function(caps, notification) {

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

    if (simulateNavPay && !caps.navPay) {
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
            console.log('navigator.mozPay success');
            waitForPayment($def, product, webpayJWT, contribStatusURL);
        };
        request.onerror = function() {
            if (this.error.name !== 'cancelled') {
                console.log('navigator.mozPay error:', this.error.name);
                notification({
                    classes: 'error',
                    message: gettext('Payment failed. Try again later.'),
                    timeout: 5000
                }).then(window.location.reload);
            }
            $def.reject(null, product, 'MKT_CANCELLED');
        };
    }

    function beginPurchase(prod) {
        if (!prod) return;
        if ($def && $def.state() == 'pending') {
            $def.reject(null, product, 'collision');
            return;
        }
        $def = $.Deferred();
        product = prod;

        if (caps.navPay || simulateNavPay) {
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

    return {
        'purchase': beginPurchase
    };
});
