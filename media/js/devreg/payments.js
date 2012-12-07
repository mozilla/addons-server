(function(exports) {
    "use strict";

// This is the setup payments form.
exports.payment_setup = function() {

    var getOverlay = function(name) {
        $('.overlay').remove();
        var overlay = makeOrGetOverlay(name);
        overlay.html($('#' + name + '-template').html());
        handlePaymentOverlay(overlay);
        return overlay;
    };

    // Set up account modal.
    var newBangoPaymentAccount = function(e) {
        var $overlay = getOverlay('add-bango-account');

        function setupBangoForm($overlay) {
            $overlay.on('submit', 'form', _pd(function(e) {
                var $form = $(this);
                var $waiting_overlay;
                var $old_overlay = $overlay.find('section.add-bango-account');
                $old_overlay.detach();

                $.post(
                    $form.attr('action'), $form.serialize(),
                    function(data) {
                        $('.overlay').remove();
                        $('#bango-account-list').html(data);
                        $('#no-payment-providers').addClass('js-hidden');
                    }
                ).error(function(error_data) {
                    // If there's an error, revert to the form and reset the buttons.
                    $waiting_overlay.empty().append($old_overlay);
                    $old_overlay.find('#bango-account-errors').html(error_data.responseText);
                    setupBangoForm($waiting_overlay);
                });
                $waiting_overlay = getOverlay('bango-waiting');
            }));
        }
        setupBangoForm($overlay);
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

    $('.payment-account-actions').on('click', _pd(newBangoPaymentAccount));

    function handlePaymentOverlay(overlay) {
        overlay.addClass('show').on('click', '.close', _pd(function() {
            overlay.remove();
        }));
    }
};

$('.update-payment-type button').click(function(e) {
    $('input[name=toggle-paid]').val($(this).data('type'));
});

var $paid_island = $('#paid-island, #paid-upsell-island');
$('#submit-payment-type.hasappendix').on('tabs-changed', function(e, tab) {
    $paid_island.toggle(tab.id == 'paid-tab-header');
})


})(typeof exports === 'undefined' ? (this.dev_payments = {}) : exports);

$(document).ready(function() {
    dev_payments.payment_setup();
});
