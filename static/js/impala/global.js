//bind pager controls to our addon grids
$('.island .listing-grid').on('grid.init', function(e, data) {
    var $grid = data.self,
        numPages = data.maxPage;

    if (numPages > 0) {
        var $nav = $('<nav class="pager">');
        $nav.append('<a href="#" class="prev">&laquo;</a>');
        for (var i=0; i<=numPages; i++) {
            $nav.append('<a href="#" class="' + (i==0 ? 'selected ': '') + 'dot"><b></b></a>');
        }
        $nav.append('<a href="#" class="next">&raquo;</a>');
        $grid.parent().prepend($nav);
        $nav.on('click', 'a', function(e) {
            e.preventDefault();
            var $tgt = $(this);
            if ($tgt.hasClass('dot')) {
                $grid.go($tgt.index() - 1);
            } else if ($tgt.hasClass('prev')){
                $grid.prevPage();
            } else if ($tgt.hasClass('next')){
                $grid.nextPage();
            }
        });
        $grid.on('grid.update', function(e, data) {
            $nav.find('.dot').removeClass('selected')
                .eq(data.current).addClass('selected');
        });
    }
});

function hoverTruncate(grid) {
    var $grid = $(grid);
    if ($grid.hasClass('hovercard')) {
        $grid = $grid.parent();
    }
    $grid.find('.hovercard h3').truncate();
    $grid.on('mouseover', '.hovercard', function() {
        var $el = $(this);
        setTimeout(function() {
            $el.find('h3').untruncate();
        }, 100);
    }).on('mouseout', '.hovercard', function() {
        var $el = $(this);
        setTimeout(function() {
            $el.find('h3').truncate();
        }, 100);
    });
}

function listing_grid() {
    var $grid = $(this),
        $pages = $grid.find('section'),
        current = 0,
        maxPage = $pages.length-1;
    $grid.trigger("grid.init", {self: $grid, current: current, maxPage: maxPage});
    $grid.go = function(n) {
        if (n != current) {
            n = n < 0 ? 0 : (n > maxPage ? maxPage : n);
            current = n;
            $pages.hide().eq(n).show().find('.hovercard h3').truncate();
            $grid.trigger("grid.update", {self: $grid, current: current, maxPage: maxPage});
        }
    };
    $grid.prevPage = function() {
        $grid.go(current-1);
    };
    $grid.nextPage = function() {
        $grid.go(current+1);
    };
    hoverTruncate(this);
    $grid.css({
        'width': $grid.width() + 'px',
        'height': $grid.height() + 'px'
    });
    return $grid;
}


$(function() {
    "use strict";

    // Paginate listing grids.
    $('.listing-grid').each(listing_grid);

    // Truncate titles on single hovercards.
    $('.hovercard').each(function() {
        hoverTruncate(this);
    });

    // load deferred images.
    $('img[data-defer-src]').each(function() {
        var $img = $(this);
        $img.attr('src', $img.attr('data-defer-src'));
    });

    // Email obfuscation.
    $('span.emaillink').each(function() {
        var $this = $(this);
        $this.find('.i').remove();
        var em = $this.text().split('').reverse().join('');
        $this.prev('a').attr('href', 'mailto:' + em);
        // Allows the email to be selected and pasted in webmails, see #919160.
        $this.text(em).css('direction', 'ltr');
    });

    $('#page').on('click', '.expando .toggle', _pd(function() {
        $(this).closest('.expando').toggleClass('expanded');
    }));

    var fragment = window.location.hash;
    if (fragment && /^#[\w.-]+$/.test(fragment)) {
        // If the page URL is pointing directly to an expando section (e.g.
        // external link to that section), make sure the contents are visible.
        var $target = $(fragment);
        if ($target.hasClass('expando'))
            $target.addClass('expanded');
    }

    $('#page').on('click', '.scrollto', function(e) {
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

    $("select[name='rating']").ratingwidget();
});

// AJAX form submit

$(function() {
  $(document).on('submit', 'form.ajax-submit, .ajax-submit form', function() {
      var $form = $(this),
          $parent = $form.is('.ajax-submit') ? $form : $form.closest('.ajax-submit'),
          params = $form.serializeArray();

      $form.find('.submit, button[type=submit], submit').prop('disabled', true).addClass('loading-submit');
      $.post($form.attr('action'), params, function(d) {
          var $replacement = $(d);
          $parent.replaceWith($replacement);
          $replacement.trigger('ajax-submit-loaded');
          $replacement.find('.ajax-submit').trigger('ajax-submit-loaded');
      });
      return false;
  });
});
