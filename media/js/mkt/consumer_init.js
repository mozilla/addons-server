// Do this last- initialize the marketplace!

define('marketplace', ['login', 'notification', 'prefetch'], function() {});
require('marketplace');

$('#splash-overlay').addClass('hide');
