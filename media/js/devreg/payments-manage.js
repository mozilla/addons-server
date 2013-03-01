define('payments-manage', ['payments'], function(payments) {
    'use strict';

    function refreshAccountForm(data) {
        var $accountListForm = $('#bango-account-list');
        $accountListForm.load($accountListForm.data('url'));
    }

    function newBangoPaymentAccount(e) {
        var $overlay = payments.getOverlay({
            'id': 'add-bango-account',
            'class': 'undismissable'
        });
        payments.setupPaymentAccountOverlay($overlay, showAgreement);
    }

    function setupAgreementOverlay(data, onsubmit) {
        var $waiting_overlay = payments.getOverlay('bango-waiting');

        $.getJSON(data['agreement-url'], function(response) {
            var $overlay = payments.getOverlay('show-agreement');
            $overlay.on('submit', 'form', _pd(function(e) {
                var $form = $(this);

                // Assume the POST below was a success, and close the modal.
                $overlay.trigger('overlay_dismissed').detach();
                onsubmit.apply($form, data);

                // If the POST failed, we show an error message.
                $.post(data['agreement-url'], $form.serialize(), refreshAccountForm).fail(function() {
                    $waiting_overlay.find('h2').text(gettext('Error'));
                    $waiting_overlay.find('p').text(gettext('There was a problem contacting the payment server.'));
                });
            }));

            // Plop in date of agreement.
            var msg = $('.agreement-valid');
            msg.html(format(msg.html(), {date: response.valid}));

            // Plop in text of agreement.
            $('.agreement-text').text(response.text);
        });
    }

    function showAgreement(data) {
        setupAgreementOverlay(data, function() {
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
            if (data.length) {
                for (var acc = 0; acc < data.length; acc++) {
                    var account = data[acc];
                    $table.append(paymentAccountTemplate(account));
                }
            } else {
                var $none = $('<div>');
                $none.text(gettext('You do not currently have any payment accounts.'));
                $none.insertBefore($table);
                $table.remove();
            }

            $overlay_section.on('click', 'a.delete-account', _pd(function() {
                var $tr = $(this).parents('tr').remove();

                // Post to the delete URL, then refresh the account form.
                $.post($tr.data('delete-url')).then(refreshAccountForm);
            })).on('click', '.modify-account', _pd(function() {
                // Get the account URL from the table row and pass it to
                // the function to handle the Edit overlay.
                editBangoPaymentAccount($(this).parents('tr').data('account-url'))();
            })).on('click', '.accept-tos', _pd(function() {
                showAgreement({'agreement-url': $(this).parents('tr').data('agreement-url')});
            }));
        });
    }

    function init() {
        z.body.on('click', '.add-payment-account', _pd(newBangoPaymentAccount));
        z.body.on('click', '.payment-account-actions', _pd(paymentAccountList));
    }

    return {init: init};
});
