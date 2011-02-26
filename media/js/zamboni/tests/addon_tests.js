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
})
