(function() {

    var overlay = $('#pay'),
        paymentsTemplate = getTemplate($('#pay-template'));

    if (!paymentsTemplate) {
        return;
    }

    var product,
        purchaseInProgress = true,
        $def,
        message = $('#purchased-message'),
        messageTemplate = template($('#purchased-template').html()),
        data = {
            'currency': $('body').data('user').currency,
            'src': z.getVars().src,
            'device_type': z.capabilities.getDeviceType()
        },
        oneTimePayClicked = false,
        simulateNavPay = $('body').data('simulate-nav-pay');

    if (z.capabilities.chromeless) {
        data.chromeless = 1;
    }

    var _giveUp;
    var _abortCheck = false;

    function waitForPayment($def, product, blueviaJWT, contribStatusURL) {
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
                $def.reject(product, 'MKT_INSTALL_ERROR');
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
                $def.reject(product, 'MKT_SERVER_ERROR');
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

    function callNavPay($def, product, blueviaJWT, contribStatusURL) {
        var request = navigator.mozPay([blueviaJWT]);
        request.onsuccess = function() {
            waitForPayment($def, product, blueviaJWT, contribStatusURL);
        }
        request.onerror = function() {
            $def.reject(product, 'MKT_CANCELLED');
        }
    }

    function beginPurchase(prod) {
        if (!prod) return;
        if ($def && $def.state() == 'pending') {
            $def.reject(product, 'collision');
            return;
        }
        $def = $.Deferred();
        product = prod;
        oneTimePayClicked = false;

        if (z.capabilities.navPay || simulateNavPay) {
            $.post(product.prepareNavPay, {})
                .fail(function() {
                    $def.reject(product, 'MKT_SERVER_ERROR');
                })
                .done(function(result) {
                    callNavPay($def, product, result.blueviaJWT, result.contribStatusURL);
                });
            return $def.promise();
        }

        // If the user is pre-authed or the app has zero price, just call
        // the purchase method right away.
        if (z.pre_auth || product.price === '0') {
            startPayment();
            return $def.promise();
        }

        if (product.currencies) {
            initCurrencies(JSON.parse(product.currencies));
        }

        overlay.html(paymentsTemplate(product));
        overlay.addClass('show');

        // Let's set user's default currency unless he/she changes it.
        if (data.currency) {
            $('#preapproval input[name=currency]').val(data.currency);
        }

        // Guess and set the payment overlay height.
        setTimeout(function() {
            overlay.find('section').css('height',
                $('#pay section > div').outerHeight() + 38 +'px');
        }, 0);

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
            $label = $(format('<div><em>{0}</em></div>', gettext('Currency'))),
            $item;

        for (var currency in clist) {
            $item = $(format('<li><a href="#">{0} ({1})</a></li>', currency,
                             clist[currency]));
            $list.append($item);
        }

        $label.prepend($list);

        // Yea...(race condition).
        setTimeout(function() {
            $('.product-details .price').addClass('has-currency')
                                        .append($label);
            initCurrencyEvents($list);
        }, 0);
    }

    function initCurrencyEvents($list) {
        var $price = $('#price-display'),
            $items = $list.find('li');

        $('#pay .has-currency').unbind('click').click(function(e) {
            if ($price.hasClass('expanded')) {
                $price.removeClass('expanded');
                $list.css('height', 0);
            } else {
                var myHeight = $items.length * $items.outerHeight();
                $price.addClass('expanded');
                $list.css('height', myHeight + 'px');
            }
        });

        $('#pay').unbind('click.currency')
                 .on('click.currency', _pd(function(e) {
            var $targ = $(e.target);

            if ($targ.parents('#currency-list').length ||
                $targ.parent('.price').length) {
                var sel = $targ.html().split(' ');

                if (sel.length == 2) {
                    sel[1] = sel[1].replace(/\(/, '').replace(/\)/, '');

                    // Feel free to remove.
                    console.log('Setting currency to: ', sel[0]);
                    data.currency = sel[0];
                    $('#preapproval input').val(sel[0]);
                    $price.removeClass('expanded').html(sel[1]);
                    $list.css('height', 0);
                }
            } else {
                $price.removeClass('expanded');
                $list.css('height', 0);
            }
        }));
    }

    function beginPreApproval(e) {
        localStorage.setItem('toInstall', product.manifestUrl);
        $('#preapproval').submit();
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
        message.replaceWith(messageTemplate(product));
        $('#purchased').removeClass('js-hidden');
        $def.resolve(product);
    }

    function startPayment(e) {
        if (e && e.preventDefault) e.preventDefault();
        if (oneTimePayClicked) {
            return;
        }
        oneTimePayClicked = true;
        $.when(doPaypal(product))
         .then(completePurchase);
    }

    function doPaypal() {
        var $def = $.Deferred();
        $(window).bind('purchasecomplete.payments', function() {
            $def.resolve();
        });

        $(window).bind('purchaseerror.payments', function(e, p, error) {
            // PayPal iframe was dismissed by user.
            if (error) {
                $('#pay-error').show().find('div').text(error);
            }
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
                dgFlow = new PAYPAL.apps.DGFlow({trigger: '#page'});
                dgFlow.startFlow(response.url);
                overlay.removeClass('show');
                // Scroll to top of PayPal modal.
                var $frame = $('[name=PPDGFrame]');
                if ($frame.length) {
                    var offset = $frame.offset().top;
                    if (offset > 9) {
                        $(document.documentElement).animate({scrollTop: offset}, 1000);
                    }
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
