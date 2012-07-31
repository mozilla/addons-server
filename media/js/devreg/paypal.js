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

        // PayPal chosen.
        $('button.paypal').click(_pd(function(e) {
            $('.overlay').remove();
            var overlay = makeOrGetOverlay('add-paypal-email');
            overlay.html($('#add-paypal-email-template').html());
            handlePaymentOverlay(overlay);

            // Email entered and submitted.
            var emailRe = /^(([^<>()[\]\\.,;:\s@\"]+(\.[^<>()[\]\\.,;:\s@\"]+)*)|(\".+\"))@((\[[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\])|(([a-zA-Z\-0-9]+\.)+[a-zA-Z]{2,}))$/;
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

        $('button.bluevia').click(_pd(function(e) {
            alert('TODO: bluevia onboarding');
        }));
    };

    // Remove PayPal account from app.
    var paypalRemove = _pd(function(e) {
        var success = $('.success h2');

        var $remove = $('.paypal-actions #remove-account');
        var resp = $.get($remove.data('remove-url'));
        if (!resp.success) {
            if (success.length) {
                success.text(gettext('There was an error removing the Paypal account.'));
            } else {
                $('#page').prepend($('<section class="full notification-box">' +
                    '<div class="success"><h2>' +
                    gettext('There was an error removing the PayPal account.') +
                        '</h2></div></section>'));
            }
        }

        var $paypal = $('#paypal');
        $paypal.addClass('deleting');
        setTimeout(function() {
            $paypal.addClass('deleted');

            // If already existing Django message, replace message.
            if (success.length) {
                success.text(gettext('PayPal account successfully removed from app.'));
            } else {
                $('#page').prepend($('<section class="full notification-box">' +
                    '<div class="success"><h2>' +
                    gettext('PayPal account successfully removed from app.') +
                        '</h2></div></section>'));
            }
        }, 500);
    });

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
            $('#remove-account').on('click', _pd(paypalRemove));
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
        overlay.addClass('show');
        overlay.on('click', '.close', _pd(function() {
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
                if ($.inArray($('section.payments input[name=premium_type]:checked').val(), [0, 3, 4])) {
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
