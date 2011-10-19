$(function() {
    $('#search-facets').delegate('li.facet', 'click', function(e) {
        var $this = $(this);
        if ($this.hasClass('active')) {
            var $tgt = $(e.target);
            if ($tgt.is('a')) {
                $tgt.closest('ul').find('.selected').removeClass('selected');
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
            $.pjax({
                url: url,
                container: container,
                beforeSend: function(xhr) {
                    this.trigger('begin.pjax', [xhr, url, container]);
                    xhr.setRequestHeader('X-PJAX', 'true');
                    loading();
                },
                complete: function(xhr) {
                    this.trigger('end.pjax', [xhr, url, container]);
                    finished();
                }
            });
        }
    }

    function hijackLink() {
        var $this = $(this);
        // Supress clicks on the currently selected sort filter.
        if (!($this.parent('li.selected').length &&
              $this.closest('#sorter').length)) {
            pjaxOpen($(this).attr('href'));
        }
    }

    function loading() {
        var $wrapper = $container.closest('.results'),
            msg = gettext('Updating results&hellip;'),
            cls = 'updating';
        $wrapper.addClass('loading');

        // The loading throbber is absolutely positioned atop the
        // search results, so we do this to ensure a max-margin of sorts.
        if ($container.outerHeight() > 300) {
            cls += ' tall';
        }

        // Insert the loading throbber.
        $('<div>', {'class': cls, 'html': msg}).insertBefore($container);
    }

    function finished() {
        var $wrapper = $container.closest('.results');

        // Initialize install buttons and compatibility checking.
        $.when($container.find('.install:not(.triggered)')
                         .installButton()).done(function() {
            $container.find('.install').addClass('triggered');
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
    $(document).keyup(_.throttle(turnPages, 300));
}
