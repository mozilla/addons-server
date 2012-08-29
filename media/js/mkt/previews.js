(function() {

    var sliderTemplate = getTemplate($('#preview-tray'));
    var previewTemplate = getTemplate($('#single-preview'));

    if (!sliderTemplate || !previewTemplate) {
        return;
    }

    z.page.on('dragstart', function(e) {
        e.preventDefault();
    });

    function populateTray() {
        // preview trays expect to immediately follow a .mkt-tile.
        var $tray = $(this);
        var $tile = $tray.prev();
        if (!$tile.hasClass('mkt-tile') || $tray.find('.slider').length) {
            return;
        }
        var product = $tile.data('product');
        var previewsHTML = '';
         if (!product.previews) return;
        _.each(product.previews, function(p) {
            p.typeclass = (p.type === 'video/webm') ? 'video' : 'img';
            previewsHTML += previewTemplate(p);
        });

        var dotHTML = Array(product.previews.length + 1).join('<b class="dot"></b>');
        $tray.html(sliderTemplate({previews: previewsHTML, dots: dotHTML}));

        var width = $tray.find('li').length * 195 - 15;

        $tray.find('.content').css({
            'width': width + 'px',
            'margin': '0 ' + ($tray.width() - 180) / 2 + 'px'
        });

        var slider = Flipsnap($tray.find('.content')[0], {distance: 195});
        var $pointer = $tray.find('.dots .dot');
        setActiveDot();
        slider.element.addEventListener('fsmoveend', setActiveDot, false);
        function setActiveDot() {
            $pointer.filter('.current').removeClass('current');
            $pointer.eq(slider.currentPoint).addClass('current');
        }
        $tray.on('click', '.dot', function() {
            slider.moveToPoint($(this).index());
        });
    }

    z.page.on('fragmentloaded populatetray', function() {
        var trays = $('.listing.expanded .mkt-tile + .tray');
        trays.each(populateTray);
    });

})();
