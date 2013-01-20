(function(exports) {
    "use strict";

// This is the setup payments form.
exports.payment_setup = function() {

    $('#regions').trigger('editLoaded');

    var getOverlay = function(name) {
        $('.overlay').remove();
        z.body.addClass('overlayed');
        var overlay = makeOrGetOverlay(name);
        overlay.html($('#' + name + '-template').html())
            .addClass('show')
            .on('click', '.close', _pd(function() {
               // TODO: Generalize this with the event listeners in overlay.js.
               z.body.removeClass('overlayed');
               overlay.remove();
            }));
        return overlay;
    };

    // We listen for events on z.body because overlays are outside of the page.
    z.body.on('keyup', '.groupie', function() {
        var $parent;
        if (this.groupie_parent) {
            $parent = this.groupie_parent;
        } else {
            // Traverse up the DOM until you find a node that contains a hidden input.
            $parent = _.find(
                _.map($(this).parents(), $),
                function(p) {return p.has('input[type=hidden]').length;}
            );
            this.groupie_parent = $parent;
        }

        var new_val = _.pluck($parent.find('.groupie'), 'value').join('');
        $parent.children('input[type=hidden]').val(new_val);
        console.log('Concatted groupie value', new_val);
    });

    z.body.on('click', '.un-groupie-bank-accounts', _pd(function() {
        $('.bank-accounts-strip').hide();
        // jQuery won't let you attr('type', ...).
        document.getElementById('id_bankAccountNumber').type = 'text';
    }));

    z.body.on('keyup', '#id_bankAccountCode', _.debounce(_pd(function() {
        var get_code_type = function(code) {
            var filtered = code.replace(/\W/g, '');
            var test = function(re) {return re.test(filtered);};
            switch(true) {
                case test(/^\d{20}$/):
                    return gettext('Spanish Banking Code');
                case test(/^\d{14}$/):
                    return gettext('Irish Sort Code');
                case test(/^\d{12}$/):
                    return gettext('Belgian Sort Code');
                case test(/^\d{10}$/):
                    return gettext('Spanish/French/Italian/Dutch Banking Code');
                case test(/^\d{9}$/):
                    return gettext('Dutch/US Sort Code');
                case test(/^\d{8}$/):
                    return gettext('Canadian Transit Number/German Routing Code');
                case test(/^[02]\d{6}$/):
                    return gettext('Korean Bank and Branch/Indonesian Bank Code');
                case test(/^\d{7}$/):
                    return gettext('Greek HEBIC/Indonesian Bank Code');
                case test(/^\d{6}$/):
                    return gettext('UK/Irish Sort Code or NZ Account Prefix or Australian BSB Code');
                case test(/^\d{5}$/):
                    return gettext('Austrian/Swiss Bank Code');
                case test(/^\d{4}$/):
                    return gettext('Danish/Swiss Bank Code');
                case test(/^\d{3}$/):
                    return gettext('Swiss/Iraqi Bank Code');
                case test(/^\d{1,2}$/):
                    return gettext('Iraqi Bank Code');
                default:
                    return false;
            }
        };
        var result = get_code_type($(this).val());
        var $small = $(this).siblings('small');
        if (result) {
            $small.text(format(gettext('Detected: {0}'), result));
        } else {
            $small.text('');
        }
    }), 200));

    // Handle bouncing between bank account fields gracefully.
    z.body.on('keyup', '.bank-accounts-strip input', _.debounce(function(e) {
        if (e.which < 48 || // Action keys
            (e.which > 90 && e.which < 96) || // Left/right/select
            e.which > 105) {
            // The user pressed a key that we don't care about.
            return;
        }

        var $this = $(this);
        var value = $this.val();
        if (!value) {
            // We don't care about the first keypress.
            return;
        }

        // The user tabbed out already. Fast-typers rejoice!
        if (!$this.is(':focus')) {
            console.log('Input already lost focus');
            return;
        }
        var previous_value = this.previous_value || '';
        this.previous_value = value;

        var maxlength = $this.data('maxlength');
        var difflength = value.length - maxlength;
        if (difflength >= 0 && value.length != previous_value.length) {
            console.log('At max length of segment');

            var next = $this.parent().next().children('input');
            if (!next.length) {
                // We're at the end anyway.
                // TODO: Show an error?
                return;
            }
            next.focus();

            if (difflength) {
                // The user has typed past the end of the input.
                console.log('Typed past length of segment');
                $this.val(value.substring(0, maxlength));
                next.val(value.substr(maxlength));
                next.trigger('keyup');
            }
        }

    }, 200));

    // This generates the pre-filled bank account name.
    z.body.on(
        'keyup',
        '.bank-accounts-strip input, #id_bankName, #id_bankAccountPayeeName',
        _.debounce(function(e) {
            var $account_name = $('#id_account_name');
            var accnum = $('#id_bankAccountNumber').val();
            var bankname = $('#id_bankName').val();
            var name = $('#id_bankAccountPayeeName').val();

            var acc_name = name;
            if (accnum.length > 10) {
                if (acc_name) {
                    acc_name += ' ';
                }

                acc_name += (
                    '(' +
                    accnum.substr(0, 2) +
                    '-' +
                    accnum.substr(2, 2) +
                    'XX-XXXXX' +
                    accnum.substr(accnum.length - 4, 2) +
                    '-' +
                    accnum.substr(accnum.length - 2) +
                    ')'
                );
            }
            if (bankname) {
                if (acc_name) {
                    acc_name += ' ';
                }
                acc_name += bankname;
            }

            // Enforce 64 char length
            if (acc_name.length > 64) {
                acc_name = acc_name.substr(0, 64);
            }

            var account_name_value = $account_name.val();
            var last_acc_name = $account_name.data('last');
            // If the account name is empty or the value is the last one we generated.
            if (!account_name_value || account_name_value == last_acc_name) {
                // Overwrite the value because it's not user-supplied.
                $account_name.val(acc_name);
            }
            $account_name.data('last', acc_name);
        }, 1000) // We don't need this to run very often.
    );

    function refreshAccountForm(data) {
        var $account_list_form = $('#bango-account-list');
        $account_list_form.load($account_list_form.data('url'));
    }

    function setupPaymentAccountOverlay($overlay, onsubmit) {
        function setupBangoForm($overlay) {
            $overlay.on('submit', 'form', _pd(function(e) {
                var $form = $(this);
                var $waiting_overlay;
                var $old_overlay = $overlay.children('section');
                $old_overlay.detach();
                $form.find('.error').remove();

                $.post(
                    $form.attr('action'), $form.serialize(),
                    function(data) {
                        $waiting_overlay.trigger('dismiss');
                        onsubmit.apply($form, [data]);
                    }
                ).error(function(error_data) {
                    // If there's an error, revert to the form and reset the buttons.

                    // We're recycling the variable $waiting_overlay to store
                    // the old overlay. That gets cleaned up, though, when we
                    // re-call setupBangoForm().
                    $waiting_overlay.empty().append($old_overlay);

                    try {
                        var parsed_errors = JSON.parse(error_data.responseText);
                        for(var field_error in parsed_errors) {
                            var field = $('#id_' + field_error);
                            $('<div>').addClass('error')
                                      .insertAfter(field)
                                      .text(parsed_errors[field_error].join('\n'));
                        }
                    } catch(err) {
                        // There was a JSON parse error, just stick the error
                        // message on the form.
                        $old_overlay.find('#bango-account-errors')
                                    .html(error_data.responseText);
                    }
                    setupBangoForm($waiting_overlay);
                });
                $waiting_overlay = getOverlay('bango-waiting');
            }));
        }
        setupBangoForm($overlay);
    }

    var newBangoPaymentAccount = function(e) {
        var $overlay = getOverlay('add-bango-account');
        setupPaymentAccountOverlay(
            $overlay,
            function(data) {
                refreshAccountForm();
                $('#no-payment-providers').addClass('js-hidden');
            }
        );
    };

    var editBangoPaymentAccount = function(account_url) {
        var paymentAccountSetup = function() {
            var $overlay = getOverlay('edit-bango-account');
            $overlay.find('form').attr('action', account_url);
            setupPaymentAccountOverlay($overlay, refreshAccountForm);
        };

        // Start the loading screen while we get the account data.
        return function(e) {
            var $waiting_overlay = getOverlay('bango-waiting');
            $.getJSON(
                account_url,
                function(data) {
                    $waiting_overlay.remove();
                    paymentAccountSetup();
                    for(var field in data) {
                        $('#id_' + field).val(data[field]);
                    }
                }
            );
        };
    };

    var paymentAccountTemplate = template($('#account-row-template').html());
    var paymentAccountList = function(e) {
        var $overlay = getOverlay('account-list');
        var $overlay_section = $overlay.children('.account-list').first();

        $.getJSON(
            $overlay_section.data('accounts-url'),
            function(data) {
                $overlay_section.removeClass('loading');
                var $table = $overlay_section.children('table');
                for(var acc = 0; acc < data.length; acc++) {
                    var account = data[acc];
                    $(paymentAccountTemplate(account)).appendTo($table);
                }

                $overlay_section.on('click', 'a.delete-account', _pd(function() {
                    var $tr = $(this).parents('tr').addClass('deleted');
                    // Delay the TR's removal 1s for the transition to complete.
                    setTimeout(function() {
                        $tr.remove();
                    }, 1000);

                    // Post to the delete URL, then refresh the account form.
                    $.post($tr.data('delete-url')).then(refreshAccountForm);

                })).on('click', 'a.modify-account', _pd(function() {
                    // Get the account URL from the table row and pass it to
                    // the function to handle the Edit overlay.
                    editBangoPaymentAccount($(this).parents('tr').data('account-url'))();
                }));
            }
        );
    };

    z.body.on('click', '.add-payment-account', _pd(newBangoPaymentAccount));
    z.body.on('click', '.payment-account-actions', _pd(paymentAccountList));
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
