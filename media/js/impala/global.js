//bind pager controls to our addon grids
$('.island .listing-grid').bind('grid.init', function(e, data) {
    var $grid = data.self,
        numPages = data.maxPage;

    if (numPages > 1) {
        var $nav = $('<nav class="pager">');
        $nav.append('<a href="#" class="prev">&laquo;</a>');
        for (var i=0; i<=numPages; i++) {
            $nav.append('<a href="#" class="' + (i==0 ? 'selected ': '') + 'dot"><b></b></a>');
        }
        $nav.append('<a href="#" class="next">&raquo;</a>');
        $grid.parent().prepend($nav);
        $nav.delegate('a', 'click', function(e) {
            e.preventDefault();
            var $tgt = $(this);
            if ($tgt.hasClass('dot')) {
                $grid.go($tgt.index() - 1);
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

    // Show the first visit banner.
    var firstvisitcookie = 'amo_impala_user_seen';
    if (!$.cookie(firstvisitcookie)) {
        $('body').addClass('firstvisit');
        $.cookie(firstvisitcookie, '1');
    }

    //Truncate text in Firefox.
    $('.htruncate').truncate({dir: 'h'});
    $('.vtruncate').truncate({dir: 'v'});

    // Bind to the mobile site if a mobile link is clicked.
    $(".mobile-link").attr("href", window.location).click(function() {
        $.cookie("mamo", "on", {expires:30});
    });

    // Paginate listing grids.
    $('.listing-grid').each(function() {
        var $grid = $(this),
            $pages = $grid.find('section'),
            current = 0,
            maxPage = $pages.length-1;

        $grid.trigger("grid.init", {self: $grid, current: current, maxPage: maxPage});

        $grid.go = function(n) {
            if (n != current) {
                n = n < 0 ? 0 : (n > maxPage ? maxPage : n);
                current = n;
                $pages.hide().eq(n).show();
                $grid.trigger("grid.update", {self: $grid, current: current, maxPage: maxPage});
            }
        };
        $grid.prev = function() {
            $grid.go(current-1);
        };
        $grid.next = function() {
            $grid.go(current+1);
        };
    });

    // load deferred images.
    $('img[data-defer-src]').each(function() {
        var $img = $(this);
        $img.attr('src', $img.attr('data-defer-src'));
    });

    //allow dismissal of site-balloons.
    $('.site-balloon .close').click(function(e) {
        e.preventDefault();
        $(this).closest('.site-balloon').fadeOut();
    });

    $('.expando .toggle').click(_pd(function() {
        $(this).closest('.expando').toggleClass('expanded');
    }));

    $('.scrollto').click(function(e) {
        e.preventDefault();
        var href = $(this).attr('href'),
            $target = $(href.match(/#.*$/)[0]);
        if ($target.hasClass('expando')) {
            $target.addClass('expanded');
        }
        var top = $target.offset().top - 15;
        $(document.documentElement).animate({ scrollTop: top }, 500);
    });

    contributions.init();

    // Replaces rating selectboxes with the rating widget
    $("select[name='rating']").each(function(n, el) {
        var $el = $(el),
            $widget = $("<span class='ratingwidget stars stars-0'></span>"),
            rs = [],
            showStars = function(n) {
                $widget.removeClass('stars-0 stars-1 stars-2 stars-3 stars-4 stars-5').addClass('stars-' + n);
            };
        for (var i=1; i<=5; i++) {
            rs.push("<label data-stars='", i, "'>",
                    format(ngettext('{0} star', '{0} stars', i), [i]),
                    "<input type='radio' name='rating' value='", i, "'></label>");
        }
        var rating = 0;
        $widget.click(function(evt) {
            var t = $(evt.target);
            if (t.val()) {
                showStars(t.val());
            }
            rating = t.val();
        });
        $widget.mouseover(function(evt) {
            var t = $(evt.target);
            if (t.attr('data-stars')) {
                showStars(t.attr('data-stars'));
            }
        });
        $widget.mouseout(function(evt) {
            showStars(rating);
        });
        $widget.html(rs.join(''));
        $el.before($widget);
        $el.detach();
    });
});
