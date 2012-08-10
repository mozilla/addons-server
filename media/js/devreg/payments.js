(function(exports) {
    "use strict";

// These are the forms that require an email.
exports.email_setup = function() {
    if ($('div.paypal-inline').length) {
        // Don't hide this if there was an error.
        if (!$('ul.errorlist').length) {
            $('#id_email').closest('div').addClass('js-hidden');
        }

        $('div.paypal-inline input[type=radio]').click(function(e) {
            if ($(this).val() === 'yes') {
                $('#id_email').closest('div').show();
            } else {
                $('#id_email').closest('div').hide();
            }
        });
    }
    $('#paypal-change-address').click(function(e) {
        $('#paypal-change-address-form').show();
    });
    // If you've submitted the form and there was an error, show the form.
    if ($('#paypal-change-address-form ul.errorlist').length) {
        $('#paypal-change-address-form').show();
    }
};

// This is the setup payments form.
exports.payment_setup = function() {

    // Set up account modal.
    var newPaymentAccount = function(e) {
        var overlay = makeOrGetOverlay('choose-payment-account');
        overlay.html($('#choose-payment-account-template').html());
        handlePaymentOverlay(overlay);

        var emailRe = /^(([^<>()[\]\\.,;:\s@\"]+(\.[^<>()[\]\\.,;:\s@\"]+)*)|(\".+\"))@((\[[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\])|(([a-zA-Z\-0-9]+\.)+[a-zA-Z]{2,}))$/;

        // PayPal chosen.
        $('button.paypal').click(_pd(function(e) {
            $('.overlay').remove();
            var overlay = makeOrGetOverlay('add-paypal-email');
            overlay.html($('#add-paypal-email-template').html());
            handlePaymentOverlay(overlay);

            // Email entered and submitted.
            var continue_button = $('.continue');
            continue_button.click(function(e) {
                // Validate email.
                var postData = {'email': $('.email').val()};
                // Setup the PayPal in the backend.
                if (emailRe.test(postData.email)) {
                    $.post(continue_button.data('paypal-url'), postData, function(data) {
                        // Request permissions for refunds by redirecting to PayPal.
                        if (data.valid) {
                            window.location.replace(data.paypal_url);
                        }
                    });
                } else {
                    $('.email').addClass('error');
                    $('.email-error').show();
                }
            });
        }));

        // Bluevia chosen.
        $('button.bluevia').click(_pd(function(e) {
            // Open Bluevia iframe.
            $('.overlay').remove();
            var overlay = makeOrGetOverlay('bluevia-iframe');
            overlay.html($('#bluevia-iframe-template').html());
            handlePaymentOverlay(overlay);

            // Set iframe src with the JWT.
            var blueviaFrame = $('.add-bluevia-iframe iframe');
            var blueviaOrigin;
            $.get(blueviaFrame.data('bluevia-url'), function(data) {
                if (!data.error) {
                    blueviaOrigin = data.bluevia_origin;
                    blueviaFrame.attr('src', data.bluevia_url);
                } else {
                    successNotification(data.message);
                }
            });

            // Set up postMessage handler.
            z.receiveMessage(function(msg) {
                // Ensure that this came from only BlueVia.
                if (msg.origin !== blueviaOrigin) {
                    return;
                }
                var postData = JSON.parse(msg.data);
                switch (postData.status) {
                    case 'failed':
                        // TODO: Log this.
                        successNotification(gettext('There was an error setting up your BlueVia account.'));
                        break;
                    case 'canceled':
                        overlay.remove();
                        return;
                    case 'loggedin': case 'registered':
                        // User already existed or new registration.
                        $.post(blueviaFrame.data('bluevia-callback'), postData, function(data) {
                            $('#bluevia').remove();
                            $('#payments-payment-account').append(data.html);
                            successNotification(data.message[0]);
                            $('.bluevia-actions #remove-account').on('click', _pd(function(e) {
                                removeAccount('bluevia', 'BlueVia');
                            }));
                        });
                        $('#no-payment-providers').addClass('js-hidden');
                        break;
                }
                overlay.remove();
            });
        }));
    };

    function removeAccount(type, typePretty) {
        var $remove = $('.' + type + '-actions #remove-account');
        var resp = $.post($remove.data('remove-url'));
        if (resp.error) {
            // L10n: first parameter is the name of a payment provider.
            successNotification(format(gettext('There was an error removing the {0} account.'), typePretty));
        }
        var $account = $('#' + type);
        $account.addClass('deleting');
        setTimeout(function() {
            $account.addClass('deleted').remove();
            // L10n: first parameter is the name of a payment provider.
            successNotification(format(gettext('{0} account successfully removed from app.'), typePretty));
            if (!$('.payment-option').length) {
                $('#no-payment-providers').removeClass('js-hidden');
            }
        }, 500);
    }

    var update_forms = function(value) {
        var fields = [
            // Free
            [[], ['premium-detail']],
            // Premium
            [['premium-detail'], []],
            // Premium with in-app
            [['premium-detail'], []],
            // Free with in-app
            [['payments-support-type'], ['premium-detail']],
            // Premium but other.
            [[], ['premium-detail']]
        ];

        // To disable all elements within premium form.
        var elements = ['', 'a', 'textarea', 'select', 'input', 'label', 'span', 'p', 'li'];
        function getPremiumElements(id) {
            var selector = $(id);
            $.each(elements, function(index, element) {
                selector = selector.add('#' + id + ' ' + element);
            });
            return selector;
        }

        $.each(fields[value][1], function() {
            var $inactive = getPremiumElements(this);
            $inactive.addClass('inactive').unbind('click')
                     .attr('disabled', 'disabled')
                     .attr('href', 'javascript:void(0)');
        });
        $.each(fields[value][0], function() {
            var $active = getPremiumElements(this);
            $active.removeClass('inactive').removeAttr('disabled');

            // Re-enable links.
            $.each($('#' + this + ' a'), function(index, link) {
                var $link = $(link);
                $link.attr('href', $link.data('url'));
            });

            $('.payment-account-actions').on('click', _pd(newPaymentAccount));
            $('.paypal-actions #remove-account').on('click', _pd(function(e) {
                removeAccount('paypal', 'PayPal');
            }));
            $('.bluevia-actions #remove-account').on('click', _pd(function(e) {
                removeAccount('bluevia', 'BlueVia');
            }));
        });
    };

    // Hide or show upsell form.
    var $freeSelect = $('#id_free');
    var $freeText = $('#upsell-form');
    $freeSelect.change(function() {
        if ($freeSelect.val()) {
            $freeText.show();
        } else {
            $freeText.hide();
        }
    }).trigger('change');

    if ($('section.payments input[name=premium_type]').length) {
        update_forms($('section.payments input[name=premium_type]:checked').val());
        $('section.payments input[name=premium_type]').click(function(e) {
            update_forms($(this).val());
        });
    }

    function handlePaymentOverlay(overlay) {
        overlay.addClass('show').on('click', '.close', _pd(function() {
            overlay.remove();
        }));
    }
};


exports.check_with_paypal = function() {
    // Looks for errors with PayPal account.
    var $paypal_verify = $('#paypal-id-verify'),
        target = '.paypal-fail';
    if ($paypal_verify.length) {
        $.get($paypal_verify.attr('data-url'), function(d) {
                $paypal_verify.find('p').eq(0).hide();
                target = d.valid ? '.paypal-pass' : '.paypal-fail';
                $paypal_verify.find(target).show().css('display', 'inline');

                var $paypalErrors = $('#paypal-errors');
                if (d.message.length) {
                    $paypalErrors.show();
                    $('.item-actions .setup-bounce').css('display', 'inline');

                    // Load the paypal link into the anchor tag.
                    var setupBounceLink = $('#setup-bounce-link');
                    var paypalUrl = setupBounceLink.data('paypal-url');
                    $.post(paypalUrl, { email: $('#paypal-id').text() }, function(data) {
                        setupBounceLink.attr('href', data.paypal_url);
                    });
                }
                $.each(d.message, function(index, value) {
                    $paypalErrors.find('ul').append(format('<li class="status-fail"><strong>{0}</strong></li>', value));
                });

                // Make error messages inactive when initial premium type is
                // free.
                if ($.inArray($('section.payments input[name=premium_type]:checked').val(), [0, 3, 4]) > -1) {
                    $('.status-fail').addClass('inactive');
                }
            }
        );
    }
};


})(typeof exports === 'undefined' ? (this.dev_paypal = {}) : exports);

$(document).ready(function() {
    dev_paypal.email_setup();
    dev_paypal.payment_setup();
    dev_paypal.check_with_paypal();
});
