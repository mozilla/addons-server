window.onerror = function(e) {
    document.querySelector('h1').innerHTML = e;
}

function slider(el) {
    var $el = $(el),
        $ul = $('ul', $el).eq(0),
        startX,
        newX,
        prevX,
        currentX = 0;
        lastMove = 0;
        contentWidth = 0,
        sliderWidth = $el.outerWidth();
    $ul.find('li').each(function() {
        contentWidth += $(this).outerWidth();
    });
    var maxScroll = sliderWidth - contentWidth;
    $el.find('img').bind('mousedown mouseup mousemove', function(e) {
        e.preventDefault();
    })
    $el.bind('touchstart', function(e) {
        e.preventDefault();
        var oe = e.originalEvent;
        startX = oe.touches[0].pageX;
        $ul.addClass('panning');
        $ul.css('-webkit-transition-timing', null)
        lastMove = oe.timeStamp;
    });
    $el.bind('touchmove', function(e) {
        e.preventDefault();
        var oe = e.originalEvent;
        var eX = oe.targetTouches[0].pageX;
        prevX = newX;
        newX = currentX + (eX - startX);
        $ul.css('-moz-transform', 'translate3d(' + newX + 'px, 0, 0)');
        $ul.css('-webkit-transform', 'translate3d(' + newX + 'px, 0, 0)');
        lastMove = oe.timeStamp;
    });
    $el.bind('touchend', function(e) {
        dbg("maxScroll: " + maxScroll);
        e.preventDefault();
        var oe = e.originalEvent;
        var eX = oe.changedTouches[0].pageX;
        newX = currentX + (eX - startX);
        var dist = newX - prevX;
        var time = oe.timeStamp - lastMove;
        var finalX = newX + (dist * 350 / time);
        finalX = Math.min(Math.max(finalX, maxScroll), 0);
        // if (finalX > 0 || finalX < contentWidth) {
        //     var overShoot = Math.abs(finalX > 0 ? finalX : (contentWidth - finalX));
        // }
        currentX = finalX;
        $ul.removeClass('panning');
        $ul.css('-moz-transform', 'translate3d(' + currentX + 'px, 0, 0)');
        $ul.css('-webkit-transform', 'translate3d(' + currentX + 'px, 0, 0)');
    });
    $(window).bind('saferesize', function() {
        sliderWidth = $el.outerWidth();
        maxScroll = sliderWidth - contentWidth;
    });
}

slider($('.slider')[0]);