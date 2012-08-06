(function() {
    z.page.on('fragmentloaded', function() {
        function initSliders() {
            // Is this a finger-friendly device?
            if (z.capabilities.touch) {
                // is overflow-scrolling: touch supported?
                if (!z.capabilities.nativeScroll) {
                    $('.slider').each(touchSlider);
                }
                return;
            }
            //$('.categories h3').linefit();
            $('.slider').each(mouseSlider);
        }

        initSliders();
        $(window).bind('saferesize', initSliders);
    });

    function touchSlider() {
        var $el = $(this),
            $ul = $('ul', $el).eq(0),
            ulRaw = $ul[0],
            startX,
            newX,
            prevX,
            currentX = 0,
            lastMove = 0,
            contentWidth = 0,
            prop = z.prefixUpper + 'Transform',
            sliderWidth = $el.outerWidth();
        $ul.find('li').each(function() {
            contentWidth += $(this).outerWidth();
        });
        var maxScroll = sliderWidth - contentWidth;
        $el.find('img').bind('mousedown mouseup mousemove', function(e) {
            e.preventDefault();
        });
        $el.bind('touchstart', function(e) {
            // e.preventDefault();
            var oe = e.originalEvent;
            startX = oe.touches[0].pageX;
            $ul.addClass('panning');
            $ul.css('-webkit-transition-timing', null);
            lastMove = oe.timeStamp;
        });
        $el.bind('touchmove', function(e) {
            // e.preventDefault();
            prevX = newX;
            newX = currentX + (e.originalEvent.targetTouches[0].pageX - startX);
            ulRaw.style[prop] = 'translate3d(' + newX + 'px, 0, 0)';
            lastMove = e.originalEvent.timeStamp;
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

    function mouseSlider() {
        var currentPage,
            $this = $(this),
            $nextLink = $('.next-page', $this),
            $prevLink = $('.prev-page', $this),
            $li = $('li', $this),
            perPage = itemsPerPage($li),
            maxPage = numPages($li, perPage);

        $prevLink.on('click', _pd(prevPage));
        $nextLink.on('click', _pd(nextPage));

        var showNext = false,
            $window = $(window),
            fold = $window.width() + $window.scrollLeft();
        $li.each(function() {
            var $this = $(this);
            // Check if this item is off screen!
            if ($this.offset().left + $this.outerWidth() > fold) {
                return showNext = true;
            }
        });
        // Show "next" arrow if there is at least one page.
        $nextLink.toggleClass('show', showNext && !!maxPage);

        gotoPage(0);

        function gotoPage(n) {
            if (n < 0 || n > maxPage) {
                return;
            }
            var val = n * perPage * $li.outerWidth(true);
            // Have no idea why the magic number is needed.
            val += n * (perPage + ($this.hasClass('categories') ? 14 : 7));
            currentPage = n;
            $this.find('ul').css(z.prefixed('transform'),
                                 'translateX(-'+val+'px)');
            if (n === 0) {
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
    }

    function itemsPerPage($li) {
        var contWidth = $li.closest('.promo-slider').width();
        if (!contWidth) {
            contWidth = $li.closest('.alt-slider').width();
        }
        return Math.floor(contWidth / $li.outerWidth(true)) || 1;
    }

    function numPages($li, perPage) {
        var rawVal = $li.length / perPage,
            floorVal = Math.floor($li.length / perPage);
        return rawVal == floorVal ? floorVal - 1 : floorVal;
    }
})();
