// Do this last- initialize the marketplace!

(function() {

    var modules = [
        'install'
    ];

    define('reviewers', modules, function() {
        // TODO: Nuke Webtrends once we're exclusively on GA.
        webtrendsAsyncInit();
    });

    require('reviewers');

})();

