z.page.on('fragmentloaded', function() {

    // Reinitialize theme install button.
    $('.button.theme-install').click(_pd(function(e) {
        var elm = $('theme-large theme-preview div')[0];
        if (elm) {
            dispatchPersonaEvent('SelectPersona', elm);
        }
    }));

    // Reinitialize theme previews.
    initPreviewTheme(true);
});
