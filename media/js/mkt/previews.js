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

        Flipsnap($tray.find('.content')[0], {distance: 195});
    }

    z.page.on('fragmentloaded populatetray', function() {
        var trays = $('.listing.expanded .mkt-tile + .tray');
        trays.each(populateTray);
    });

})();
