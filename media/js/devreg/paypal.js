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
            if ($(this).val() === 'no') {
                $('#id_email').closest('div').hide();
            } else {
                $('#id_email').closest('div').show();
            }
        });
    }
    $('#paypal-change-address').click(function(e) {
        $('#paypal-change-address-form').show();
    });
    // If you've submitted the form and there was an error, show the form.
    if ($('ul.errorlist').length) {
        $('#paypal-change-address-form').show();
    }
};

// This is the setup payments form.
exports.payment_setup = function() {
    var update_forms = function(value) {
        var fields = [
            // Free
            [[], ['payments-support-type', 'payments-price-level',
                  'payments-upsell']],
            // Premium
            [['payments-support-type', 'payments-price-level',
              'payments-upsell'], []],
            // Premium with in-app
            [['payments-support-type', 'payments-price-level',
              'payments-upsell'], []],
            // Free with in-app
            [['payments-support-type'],
             ['payments-price-level', 'payments-upsell']]
        ];
        $.each(fields[value][0], function() { $('#' + this).show(); });
        $.each(fields[value][1], function() { $('#' + this).hide(); });
    };

    if ($('section.payments input[name=premium_type]').length) {
        update_forms($('section.payments input[name=premium_type]:checked').val());
        $('section.payments input[name=premium_type]').click(function(e) {
            update_forms($(this).val());
        });
    };
};


exports.check_with_paypal = function() {
    var $paypal_verify = $('#paypal-id-verify'),
        target = '.paypal-fail';
    if ($paypal_verify.length) {
        $.get($paypal_verify.attr('data-url'), function(d) {
                $paypal_verify.find('p').eq(0).hide();
                target = d.valid ? '.paypal-pass' : '.paypal-fail';
                $paypal_verify.find(target).show();
                $.each(d.message, function() {
                    $paypal_verify.find('ul').append('<li class="status-fail"><strong>' + d.message + '</strong></li>');
                })
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

