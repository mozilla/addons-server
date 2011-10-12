$(function() {
    $('#search-facets').delegate('li.facet', 'click', function(e) {
        var $this = $(this);
        if ($this.hasClass('active')) {
            var $tgt = $(e.target);
            if ($tgt.is('a')) {
                $tgt.closest('.facet').find('.selected').removeClass('selected');
                $tgt.closest('li').addClass('selected');
                return;
            }
            $this.removeClass('active');
        } else {
            $this.closest('ul').find('.active').removeClass('active');
            $this.addClass('active');
        }
    });

    if ($('body').hasClass('pjax') && $.support.pjax) {
        initSearchPjax('#pjax-results');
    }
});


function initSearchPjax(container) {
    var $container = $(container);

    function pjaxOpen(url) {
        var urlBase = location.pathname + location.search;
        if (!!url && url != '#' && url != urlBase) {
            $.pjax({'url': url, 'container': container});
        }
    }

    function hijackLink() {
        pjaxOpen($(this).attr('href'));
    }

    function loading() {
        var $this = $(this),
            $wrapper = $this.closest('.results'),
            msg = gettext('Updating results&hellip;'),
            cls = 'updating';
        $wrapper.addClass('loading');

        // The loading indicator is absolutely positioned atop the
        // search results, so we do this to ensure a max-margin of sorts.
        if ($this.outerHeight() > 300) {
            cls += ' tall';
        }

        // Insert the loading indicator.
        $('<div>', {'class': cls, 'html': msg}).insertBefore($this);
    }

    function finished() {
        var $this = $(this),
            $wrapper = $this.closest('.results');

        // Initialize install buttons and compatibility checking.
        $.when($this.find('.install:not(.triggered)').installButton()).done(function() {
            $this.find('.install').addClass('triggered');
            initListingCompat();
        });

        // Remove the loading indicator.
        $wrapper.removeClass('loading').find('.updating').remove();

        // Scroll up.
        $('html').animate({scrollTop: 0}, 200);
    }

    function turnPages(e) {
        if (fieldFocused(e)) {
            return;
        }
        if (e.which == $.ui.keyCode.LEFT || e.which == $.ui.keyCode.RIGHT) {
            e.preventDefault();
            var sel;
            if (e.which == $.ui.keyCode.LEFT) {
                sel = '.paginator .prev:not(.disabled)';
            } else {
                sel = '.paginator .next:not(.disabled)';
            }
            pjaxOpen($container.find(sel).attr('href'));
        }
    }

    $('.pjax-trigger a').live('click', _pd(hijackLink));
    $container.bind('start.pjax', loading).bind('end.pjax', finished);
    $(document).keyup(_.throttle(turnPages, 300));
}
