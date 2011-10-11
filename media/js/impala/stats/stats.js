$(function() {
    "use strict";

    $(window).bind("changeview", function(e, view) {
        var queryParams = {},
            range = view.range;
        if (range) {
            if (typeof range == "string") {
                queryParams['last'] = range.split(/\s+/)[0];
            } else if (typeof range == "object") {

            }
        }
        queryParams = $.param(queryParams);
        if (queryParams) {
            history.replaceState(view, document.title, '?' + queryParams);
        }
    });

    var initView = {
            metric: $('.primary').attr('data-report'),
            range: $('.primary').attr('data-range'),
            group: 'day'
        };

    $(window).trigger('changeview', initView);
});
