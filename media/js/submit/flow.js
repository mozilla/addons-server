$(function() {

    function loading(e, xhr, options) {
        // TODO: Bail if errors are present.
        var $container = $(this);
        $container.addClass('loading').trigger('flow.loading');
    }

    function finished(e, xhr, options) {
        var $container = $(this),
            $wrapper = $container.closest('.results');
        $container.removeClass('loading').addClass('loaded');
        var $progress = $('#submission-progress'),
            $selected = $progress.find('.active');
        if ($selected.length) {
            // Forward.
            var stepCur = parseInt($progress.attr('data-current-step'), 10),
                stepMax = parseInt($progress.attr('data-max-step'), 10),
                stepNext = Math.min(stepCur + 1, stepMax);

            // Decrement to previous step when going back in history.
            $(window).bind('popstate', function(e) {
                stepNext--;
                stepCur--;
                $progress.attr('data-current-step', stepNext)
                         .attr('data-previous-step', stepCur);
                $progress.find('li').eq(stepCur).nextAll().removeClass('active');
                // TODO: Keep track of whether we're going forward or backward
                // in history.
                //history.state.step = stepCur;
            });

            // Increment to next step.
            $progress.attr('data-current-step', stepNext)
                     .attr('data-previous-step', stepCur);
            $progress.find('li').eq(stepNext).prevAll().addClass('active');
            //history.state.step = stepCur;
        }

        if (options.type.toLowerCase() == 'post') {
            window.history.pushState({
                //pjax: $container.selector,
                //fragment: options.fragment,
                //timeout: options.timeout,
                pjax: '.pjax-container',
                fragment: undefined,
                timeout: 5000,
                url: null,
            }, document.title, $container.attr('data-post-url'));
        }

        // Scroll to top of page.
        $('html, body').animate({scrollTop: 0}, 200);

        $container.trigger('flow.finished');
    }
    if ($.support.pjax) {
        // TODO: Write a wrapper for PJAX-ifying forms.
        $('form').submit(_pd);
        $('.pjax-container').initPjax({
            'loading': loading,
            'finished': finished,
            'triggers': '.pjax-trigger',
            'settings': {
                'url': $('form').attr('action'),
                'type': 'post',
                'data': $('form').serialize()
            }
        });
    }
});


$.fn.initPjax = function(o) {
    o = $.extend({
        'triggers': '.pjax-trigger a'
    }, o);
    var $container = $(this),
        container = $container.selector,
        triggers = o.triggers.jquery ? o.triggers.selector : o.triggers,
        settings = $.extend({'container': container, 'timeout': 5000},
                            o.settings);
    function pjaxOpen(url) {
        var urlBase = location.pathname + location.search;
        // Skip if this is a GET and the target is the same URL.
        if (!!url && url != '#' && (url != urlBase || o.settings.data)) {
            $.pjax(settings);
        }
    }
    function hijackLink() {
        pjaxOpen(o.settings.url);
    }
    $container.delegate(triggers, 'click', _pd(hijackLink))
              .bind('pjax:start', o.loading)
              .bind('pjax:end', o.finished);
};

// TODO: Consider ensuring that POSTs do not fallback to GETs for
// non-supported browsers (https://github.com/defunkt/jquery-pjax/issues/59).
