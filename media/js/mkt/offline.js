z.page.on('fragmentloaded', function() {
    if (navigator.onLine === false) {
        checkOfflineState();
    }
});
z.page.on('click', '.offline button', function() {
    checkOfflineState();
});

function checkOfflineState() {
    if (navigator.onLine === false) {
        $('.online').hide();
        $('.offline').show();
    } else {
        $('.online').show();
        $('.offline').hide();
        z.page.trigger('refreshfragment');
    }
}
