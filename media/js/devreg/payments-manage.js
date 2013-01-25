define('payments-manage', ['payments'], function(payments) {
    'use strict';

    function refreshAccountForm(data) {
        var $account_list_form = $('#bango-account-list');
        $account_list_form.load($account_list_form.data('url'));
    }

    function newBangoPaymentAccount(e) {
        var $overlay = payments.getOverlay('add-bango-account');
        payments.setupPaymentAccountOverlay($overlay, showAgreement);
    }

    function agreementSuccess(pk) {
        $('.account-list [data-account=' + pk + '] .terms-accepted').removeClass('rejected').addClass('accepted');
    }

    function agreementError(pk) {
        $('.account-list [data-account=' + pk + '] .terms-accepted').removeClass('accepted').addClass('rejected');
    }

    var agreementUrl = $('#show-agreement-template').data('url');

    function setupAgreementOverlay(data, $overlay, onsubmit) {
        var url = format(agreementUrl, data.pk);

        // TODO: Do something with waiting overlays. This is slow.
        $.getJSON(url, function(data) {
            // Plop in date of agreement.
            var msg = $('.agreement-valid');
            msg.html(format(msg.html(), {date: data.valid}));

            // Plop in text of agreement.
            $('.agreement-text').text(data.text);
        });

        $overlay.on('submit', 'form', _pd(function(e) {
            var $form = $(this);

            // Assume the POST below was a success, and close the modal.
            $overlay.detach();
            z.body.removeClass('overlayed');
            onsubmit.apply($form, data);

            // If the POST failed, we show an error message.
            $.post(url, $form.serialize(), function(response) {
                if (response.accepted) {
                    agreementSuccess(data.pk);
                } else {
                    agreementError();
                }
            }, 'json').error(function() {
                agreementError(data.pk);
            });
        })).on('overlay_dismissed', function() {
            // If it wasn't already marked as successful, then the user cancelled.
            if (!$('.account-list [data-account=' + data.pk + '] .terms-accepted.success')) {
                agreementError(data.pk);
            }
        });
    }

    function showAgreement(data) {
        var $overlay = payments.getOverlay('show-agreement');
        setupAgreementOverlay(data, $overlay, function() {
            refreshAccountForm();
            $('#no-payment-providers').addClass('js-hidden');
        });
    }

    function editBangoPaymentAccount(account_url) {
        function paymentAccountSetup() {
            var $overlay = payments.getOverlay('edit-bango-account');
            $overlay.find('form').attr('action', account_url);
            payments.setupPaymentAccountOverlay($overlay, refreshAccountForm);
        }

        // Start the loading screen while we get the account data.
        return function(e) {
            var $waiting_overlay = payments.getOverlay('bango-waiting');
            $.getJSON(account_url, function(data) {
                $waiting_overlay.remove();
                z.body.removeClass('overlayed');
                paymentAccountSetup();
                for (var field in data) {
                    $('#id_' + field).val(data[field]);
                }
            }).fail(function() {
                $waiting_overlay.find('h2').text(gettext('Error'));
                $waiting_overlay.find('p').text(gettext('There was a problem contacting the payment server.'));
            });
        };
    }

    var paymentAccountTemplate = template($('#account-row-template').html());
    function paymentAccountList(e) {
        var $overlay = payments.getOverlay('account-list');
        var $overlay_section = $overlay.children('.account-list').first();

        $.getJSON($overlay_section.data('accounts-url'), function(data) {
            $overlay_section.removeClass('loading');
            var $table = $overlay_section.children('table');
            for (var acc = 0; acc < data.length; acc++) {
                var account = data[acc];
                $(paymentAccountTemplate(account)).appendTo($table);
            }

            $overlay_section.on('click', 'a.delete-account', _pd(function() {
                var $tr = $(this).parents('tr').remove();

                // Post to the delete URL, then refresh the account form.
                $.post($tr.data('delete-url')).then(refreshAccountForm);
            })).on('click', 'a.modify-account', _pd(function() {
                // Get the account URL from the table row and pass it to
                // the function to handle the Edit overlay.
                editBangoPaymentAccount($(this).parents('tr').data('account-url'))();
            }));
        });
    }

    function init() {
        z.body.on('click', '.add-payment-account', _pd(newBangoPaymentAccount));
        z.body.on('click', '.payment-account-actions', _pd(paymentAccountList));
    }

    return {init: init};
});
