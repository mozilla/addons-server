function slider() {
    var $el = $(this),
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
        // e.preventDefault();
        var oe = e.originalEvent;
        startX = oe.touches[0].pageX;
        $ul.addClass('panning');
        $ul.css('-webkit-transition-timing', null)
        lastMove = oe.timeStamp;
    });
    $el.bind('touchmove', function(e) {
        // e.preventDefault();
        var oe = e.originalEvent;
        var eX = oe.targetTouches[0].pageX;
        prevX = newX;
        newX = currentX + (eX - startX);
        $ul.css('-moz-transform', 'translate3d(' + newX + 'px, 0, 0)');
        $ul.css('-webkit-transform', 'translate3d(' + newX + 'px, 0, 0)');
        lastMove = oe.timeStamp;
    });
    $el.bind('touchend', function(e) {
        var oe = e.originalEvent;
        var eX = oe.changedTouches[0].pageX;
        newX = currentX + (eX - startX);
        var dist = newX - prevX;
        if (Math.abs(startX - newX) < 10) {
            return true;
        }
        e.preventDefault();
        var time = oe.timeStamp - lastMove;
        var finalX = newX + (dist * 350 / time);
        // if (finalX > 0 || finalX < contentWidth) {
        //     var overShoot = Math.abs(finalX > 0 ? finalX : (contentWidth - finalX));
        //     var after_finalX = Math.min(Math.max(finalX, maxScroll), 0);
        //     $ul.one('webkitTransitionEnd', function() {
        //         $ul.css('-webkit-transform', 'translate3d(' + after_finalX + 'px, 0, 0)');
        //         currentX = after_finalX;
        //     });
        // } else {
            finalX = Math.min(Math.max(finalX, maxScroll), 0);
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

z.page.on('fragmentloaded', function() {
    function itemsPerPage($item) {
        var contWidth = $('#page > section > div').width(),
            margin = parseInt($item.css('margin-right'), 10);

        return Math.floor(contWidth / ($item.width() + margin));
    }

    function numPages($list) {
        var $item = $list.find('li'),
            rawVal = $item.length / itemsPerPage($item),
            floorVal = Math.floor($item.length / itemsPerPage($item));
        return rawVal == floorVal ? floorVal - 1 : floorVal;
    }

    function initSliders() {
        $('.slider').each(function() {
            var currentPage,
                $this = $(this),
                $nextLink = $('.next-page', $this),
                $prevLink = $('.prev-page', $this),
                maxPage = numPages($this.find('ul'));

            // Show "next" arrow if there is at least one page.
            if (maxPage) {
                $nextLink.addClass('show');
            }
            $prevLink.click(_pd(prevPage));
            $nextLink.click(_pd(nextPage));

            gotoPage(0);

            function gotoPage(n) {
                if (n < 0 || n > maxPage) {
                    return;
                }
                $item = $this.find('ul li');
                var $item = $this.find('ul li'),
                    perPage = itemsPerPage($item),
                    val = n * perPage * $item.outerWidth(true);
                // Have no idea why the magic number is needed.
                val += n * (perPage + 7);
                currentPage = n;
                $this.find('ul').css(z.prefixed('transform'),
                                     'translateX(-'+val+'px)');
                if (n == 0) {
                    $prevLink.removeClass('show');
                } else if (n == maxPage) {
                    $nextLink.removeClass('show');
                }
            }

            function nextPage() {
                if (currentPage < maxPage) {
                    $prevLink.addClass('show');
                    gotoPage(currentPage+1);
                }
            }

            function prevPage() {
                if (currentPage) {
                    $nextLink.addClass('show');
                    gotoPage(currentPage-1);
                }
            }
        });
    }

    initSliders();
    $(window).bind('saferesize', initSliders);
});
