(function() {

    var sliderTemplate = template($('#preview-tray').html());
    var previewTemplate = template($('#single-preview').html());

    function populateTray() {
        // preview trays expect to immediately follow a .mkt-tile.
        var $tray = $(this);
        var $tile = $tray.prev();
        if (!$tile.hasClass('mkt-tile')) return;
        var product = $tile.data('product');
        var previewsHTML = '';
        _.each(product.previews, function(p) {
            p.typeclass = (p.type === 'video/webm') ? 'video' : 'img';
            previewsHTML += previewTemplate(p);
        });
        $tray.html(sliderTemplate({previews: previewsHTML}));
    }

    z.page.on('fragmentloaded', function() {
        $('.listing.expanded .mkt-tile + .tray').each(populateTray);
    });

})();