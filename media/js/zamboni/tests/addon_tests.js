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

/* Fails in Jenkins 3.6.17, uncomment when we can figure out why.
   Does not locally.
test('Test change elements on backup', function() {
    $('.backup-button', this.sandbox).showBackupButton();
    equals($('.addon-compatible td', this.sandbox).text(), 'Fx 1.0');
    equals($('.addon-updated time', this.sandbox).text(), 'today');
});
*/
