// Do this last- initialize the marketplace!

define('developers', ['login', 'notification', 'tracking'], function() {
    // TODO: Nuke Webtrends once we're exclusively on GA.
    webtrendsAsyncInit();
});
require('developers');
