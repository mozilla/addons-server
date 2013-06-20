// Do this last- initialize the marketplace!

(function() {

    var modules = [
        'buckets',
        'install'
    ];

    define('reviewers', modules, function(buckets) {
        // Append the profile string to the URL if reviewer is on mobile.
        if (z.capabilities.firefoxOS || z.capabilities.firefoxAndroid) {
            location.href = location.href + '?pro=' + buckets.get_profile();
        }
    });

    require('reviewers');

})();
