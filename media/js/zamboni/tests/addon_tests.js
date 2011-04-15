test('Buttons: Test backup button', function() {
    $('.backup-button').showBackupButton();

    var attr = 'data-version-supported',
        current = $('#buttons .install').first();
        current_wrapper = $('#buttons .install-shell').first();
        backup = $('#buttons .backup-button .install').first();
        backup_wrapper = $('#buttons .backup-button').first();

    equals(backup_wrapper.hasClass('hidden'), false);
    equals(current_wrapper.hasClass('hidden'), true);

    current_wrapper.removeClass('hidden');
    backup_wrapper.addClass('hidden');
    backup.attr(attr, 'false');
    current.attr(attr, 'true');

    $('.backup-button').showBackupButton();
    equals(backup_wrapper.hasClass('hidden'), true);
    equals(current_wrapper.hasClass('hidden'), false);
});

var paypalFixtures = {
    setup: function() {
        this.sandbox = tests.createSandbox('#paypal');
        $.mockjaxSettings = {
            status: 200,
            responseTime: 0
        };
    },
    teardown: function() {
        $.mockjaxClear();
        this.sandbox.remove();
    }
};

module('Contributions', paypalFixtures);

asyncTest('Paypal failure', function() {
    var self = this;
    $.mockjax({
        url: '/paykey?src=direct&result_type=json',
        dataType: 'json',
        responseText: { paykey: '', url:'', error:'Error' }
    });
    self.sandbox.find('div.contribute a.suggested-amount').trigger('click');
    tests.waitFor(function() {
        // Note: popup.render moves the element outside the sandbox.
        return $('#paypal-error').length === 1;
    }).thenDo(function() {
        equals($('#paypal-error').text(), 'Error');
        start();
    });
});
