// We would use :hover, but we want to hide the menu on fragment load!
if (z.capabilities.desktop) {
    $('.act-tray').on('mouseover', function() {
        $('.act-tray').addClass('active');
    }).on('mouseout', function() {
        $('.act-tray').removeClass('active');
    }).on('click', '.account-links a', function() {
        $('.account-links, .settings').removeClass('active');
    });
    z.page.on('fragmentloaded', function() {
        $('.account-links, .settings').removeClass('active');
    });
}
