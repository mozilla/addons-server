//bind pager controls to our addon grids
$('.island .addon-grid').bind('grid.init', function(e, data) {
    var $grid = data.self,
        numPages = data.maxPage;

    if (numPages > 1) {
        var $nav = $('<nav class="pager">');
        $nav.append('<a href="#" class="prev">&laquo;</a>');
        for (var i=0; i<=numPages; i++) {
            $nav.append('<a href="#" class="' + (i==0 ? 'selected ': '') + 'dot"></a>');
        }
        $nav.append('<a href="#" class="next">&raquo;</a>');
        $grid.parents('.island').prepend($nav);
        $nav.delegate('a', 'click', function(e) {
            e.preventDefault();
            var $tgt = $(this);
            if ($tgt.hasClass('dot')) {
                $grid.goto($tgt.index() - 1);
            } else if ($tgt.hasClass('prev')){
                $grid.prev();
            } else if ($tgt.hasClass('next')){
                $grid.next();
            }
        });
        $grid.bind('grid.update', function(e, data) {
            $nav.find('.dot').removeClass('selected')
                .eq(data.current).addClass('selected');
        });
    }
});


$(function() {
    "use strict";

    $('.addon-grid').each(function() {
        var $grid = $(this),
            $pages = $grid.find('section'),
            current = 0,
            maxPage = $pages.length-1;

        $grid.trigger("grid.init", {self: $grid, current: current, maxPage: maxPage});

        $grid.goto = function(n) {
            if (n != current) {
                n = n < 0 ? 0 : (n > maxPage ? maxPage : n);
                current = n;
                $pages.hide().eq(n).show();
                $grid.trigger("grid.update", {self: $grid, current: current, maxPage: maxPage})
            }
        };
        $grid.prev = function() {
            $grid.goto(current-1);
        };
        $grid.next = function() {
            $grid.goto(current+1);
        };
    });

    $("img[data-defer-src]").each(function() {
        var $img = $(this);
        $img.attr('src', $img.attr('data-defer-src'));
    });
});