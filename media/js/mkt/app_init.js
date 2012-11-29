// Do this last- initialize the marketplace!

define('marketplace', ['notification'], function(notification) {
    z.notification = notification;
});

$('#splash-overlay').addClass('hide');
