define('prefetch', [], function() {
    var assets = [
        'img/mkt/loading-16.png'
    ];
    _.each(assets, function(asset) {
        (new Image).src = z.body.data('media-url') + asset;
    });
});
