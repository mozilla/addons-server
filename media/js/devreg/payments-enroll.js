define('payments-enroll', ['payments'], function(payments) {
    'use strict';

    function getCodeType(code) {
        var filtered = code.replace(/\W/g, '');
        var test = function(re) {return re.test(filtered);};
        switch (true) {
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
    }

    function handleBankAccount(e) {
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
    }

    function generateAccountName(e) {
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
    }

    function init() {
        if ($('#id_bankAccountCode').length > 0) {
            z.body.on('keyup', '#id_bankAccountCode', _.debounce(_pd(function() {
                var $this = $(this);
                var result = getCodeType($this.val());
                // L10n: {0} is the name of a bank detected from the bank account code.
                $this.siblings('small').text(result ? format(gettext('Detected: {0}'), result) : '');
            }), 200));

            // Handle bouncing between bank account fields gracefully.
            z.body.on('keyup', '.bank-accounts-strip input', _.debounce(handleBankAccount, 200));

            // This generates the pre-filled bank account name.
            z.body.on('keyup', '.bank-accounts-strip input, #id_bankName, #id_bankAccountPayeeName',
                _.debounce(generateAccountName, 1000)  // We don't need this to run very often.
            );
        }
    }

    return {init: init};
});
