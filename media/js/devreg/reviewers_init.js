// Do this last- initialize the marketplace!

(function() {

    var modules = [
        'buckets',
        'install'
    ];

    define('reviewers', modules, function(buckets) {
        // Append the profile string to the URL if reviewer is on mobile.
        var profileInActive = location.search.indexOf('?pro') == -1;
        if (profileInActive && (z.capabilities.firefoxOS || z.capabilities.firefoxAndroid)) {
            location.search = '?pro=' + buckets.get_profile();
        }
    });

    require('reviewers');

})();
