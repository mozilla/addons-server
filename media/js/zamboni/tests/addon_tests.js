var buttonFixtures = {
    setup: function() {
        this.sandbox = tests.createSandbox('#buttons');
    },
    teardown: function() {
        this.sandbox.remove();
    }
};

module('Buttons', buttonFixtures);

test('Test backup button', function() {
    var attr = 'data-version-supported',
        current = this.sandbox.find('.install').first();
        current_wrapper = this.sandbox.find('.install-shell').first();
        backup = this.sandbox.find('.backup-button .install').first();
        backup_wrapper = this.sandbox.find('.backup-button').first();

    equals(backup_wrapper.hasClass('hidden'), false);
    equals(current_wrapper.hasClass('hidden'), true);

    current_wrapper.removeClass('hidden');
    backup_wrapper.addClass('hidden');
    backup.attr(attr, 'false');
    current.attr(attr, 'true');

    this.sandbox.find('.backup-button').showBackupButton();
    equals(backup_wrapper.hasClass('hidden'), true);
    equals(current_wrapper.hasClass('hidden'), false);
});

test('Test change elements on backup', function() {
    $('.backup-button', this.sandbox).showBackupButton();
    equals($('.addon-compatible td', this.sandbox).text(), 'Fx 1.0');
    //equals(this.sandbox.find('.addon-updated time').text(), 'today');
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
