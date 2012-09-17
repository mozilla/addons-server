z.page.on('fragmentloaded', function() {

    var installButton = $('.button.theme-install');
    installButton.click(_pd(function(e) {
        var elm = $('.theme-large .theme-preview div')[0];
        if (elm) {
            dispatchPersonaEvent('SelectPersona', elm);
        }
    }));

    // Reinitialize theme install button.
    if (z.capabilities.userAgent.indexOf('Firefox') < 0) {
        installButton.text(gettext('Not available for your platform')).unbind('click').addClass('disabled');
    }


    // Reinitialize theme previews.
    initPreviewTheme(true);
});
