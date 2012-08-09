(function() {

    var sliderTemplate = template($('#preview-tray').html());
    var previewTemplate = template($('#single-preview').html());

    z.page.on('dragstart', function(e) {
        e.preventDefault();
    });

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

        var width = $tray.find('li').length * 195 - 15;

        $tray.find('.content').css({
            'width': width + 'px',
            'margin': '0 ' + ($tray.width() - 180) / 2 + 'px'
        });
    }

    z.page.on('fragmentloaded', function() {
        var trays = $('.listing.expanded .mkt-tile + .tray');
        trays.each(populateTray);
        if (trays.length) {
            Flipsnap('#page .slider .content', {distance: 195});
        }
    });

})();