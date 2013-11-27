define('payments-manage', ['payments'], function(payments) {
    'use strict';

    function refreshAccountForm(data) {
        var $accountListForm = $('#my-accounts-list');
        var $accountListContainer = $('#bango-account-list');
        $accountListForm.load($accountListContainer.data('url'));
    }

    function newBangoPaymentAccount(e) {
        var $overlay = payments.getOverlay({
            'id': 'payment-account-add',
            'class': 'undismissable'
        });
        payments.setupPaymentAccountOverlay($overlay, showAgreement);
    }

    function confirmPaymentAccountDeletion(data) {
        var spliter = ', ';
        var isPlural = data['app-names'].indexOf(spliter) < 0;
        var $confirm_delete_overlay = payments.getOverlay('payment-account-delete-confirm');
        $confirm_delete_overlay.find('p').text(
            // L10n: This sentence introduces a list of applications.
            format(ngettext('Warning: deleting payment account "{0}" ' +
                            'will move that associated app to an incomplete status ' +
                            'and it will no longer be available for sale:',
                            'Warning: deleting payment account "{0}" ' +
                            'will move those associated apps to an incomplete status ' +
                            'and they will no longer be available for sale:',
                            isPlural), [data['name']]));
        $confirm_delete_overlay.find('ul')
                               .html('<li>' + escape_(data['app-names']).split(spliter).join('</li><li>') + '</li>');
        $confirm_delete_overlay.on('click', 'a.payment-account-delete-confirm', _pd(function() {
            $.post(data['delete-url']).then(refreshAccountForm);
            $confirm_delete_overlay.remove();
            $('#paid-island-incomplete').toggleClass('hidden');
        }));
    }

    function setupAgreementOverlay(data, onsubmit) {
        var $waiting_overlay = payments.getOverlay('payment-account-waiting');
        var $portal_link = data['portal-link'];

        $.getJSON(data['agreement-url'], function(response) {
            var $overlay = payments.getOverlay('show-agreement');
            $overlay.on('submit', 'form', _pd(function(e) {
                var $form = $(this);

                // Assume the POST below was a success, and close the modal.
                $overlay.trigger('overlay_dismissed').detach();
                onsubmit.apply($form, data);
                if ($portal_link) {
                    $portal_link.show();
                }

                // If the POST failed, we show an error message.
                $.post(data['agreement-url'], $form.serialize(), refreshAccountForm).fail(function() {
                    $waiting_overlay.find('h2').text(gettext('Error'));
                    $waiting_overlay.find('p').text(gettext('There was a problem contacting the payment server.'));
                    if ($portal_link) {
                        $portal_link.hide();
                    }
                });
            }));

            // Plop in text of agreement.
            $('.agreement-text').html(response.text);
        });
    }

    function showAgreement(data) {
        setupAgreementOverlay(data, function() {
            refreshAccountForm();
            $('#no-payment-providers').addClass('js-hidden');
        });
    }

    function portalRedirect(data) {
        // Redirecting to Bango dev portal if the local redirection is successful.
        data.el.addClass('loading-submit').text('');
        $.ajax(data['portal-url'])
            .done(function(data, textStatus, jqXHR) {
                window.location.replace(jqXHR.getResponseHeader("Location"));
            }).fail(function() {
                data.el.removeClass('loading-submit').closest('td').text(gettext('Authentication error'));
            });
    }

    function editBangoPaymentAccount(account_url) {
        function paymentAccountSetup() {
            var $overlay = payments.getOverlay('payment-account-edit');
            $overlay.find('form').attr('action', account_url);
            payments.setupPaymentAccountOverlay($overlay, refreshAccountForm);
        }

        // Start the loading screen while we get the account data.
        return function(e) {
            var $waiting_overlay = payments.getOverlay('payment-account-waiting');
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
                    if (account.shared) {
                        $table.find('a.delete-account').last().remove();
                    }
                }
            } else {
                var $none = $('<div>');
                $none.text(gettext('You do not currently have any payment accounts.'));
                $none.insertBefore($table);
                $table.remove();
            }

            $overlay_section.on('click', 'a.delete-account', _pd(function() {
                var parent = $(this).closest('tr');
                var app_names = parent.data('app-names');
                var delete_url = parent.data('delete-url');
                if (app_names === '') {
                    $.post(delete_url)
                     .fail(function() {
                         // TODO: figure out how to display a failure.
                     })
                     .success(function() {
                         parent.remove();
                         refreshAccountForm();
                     });
                } else {
                    confirmPaymentAccountDeletion({
                        'app-names': app_names,
                        'delete-url': delete_url,
                        'name': parent.data('account-name'),
                        'shared': parent.data('shared')
                    });
                }
            })).on('click', '.modify-account', _pd(function() {
                // Get the account URL from the table row and pass it to
                // the function to handle the Edit overlay.
                editBangoPaymentAccount($(this).closest('tr').data('account-url'))();
            })).on('click', '.accept-tos', _pd(function() {
                var $tr = $(this).closest('tr');
                showAgreement({
                    'agreement-url': $tr.data('agreement-url'),
                    'portal-link': $tr.closest('.portal-link')
                });
            })).on('click', '.portal-account', _pd(function() {
                var $this = $(this);
                // Prevent double-click leading to an authentication error.
                $this.click(function () { return false; });
                portalRedirect({
                    'portal-url': $this.closest('tr').data('portal-url'),
                    'el': $this
                });
            }));
        });
    }

    function init() {
        z.body.on('click', '.add-payment-account', _pd(newBangoPaymentAccount));
        z.body.on('click', '#payment-account-action', _pd(paymentAccountList));
    }

    return {init: init};
});
