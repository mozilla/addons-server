(function() {

    $(function() {
        "use strict";

        $(window).bind("changeview", function(e, view) {
            var queryParams = {},
                range = view.range;
            if (range) {
                if (typeof range == "string") {
                    queryParams.last = range.split(/\s+/)[0];
                } else if (typeof range == "object") {
                    // queryParams.start = z.date.date_string(new Date(range.start), '');
                    // queryParams.end = z.date.date_string(new Date(range.end), '');
                }
            }
            queryParams = $.param(queryParams);
            if (queryParams) {
                history.replaceState(view, document.title, '?' + queryParams);
            }
        });

        // Set up initial default view.
        var initView = {
                metric: $('.primary').attr('data-report'),
                range: $('.primary').attr('data-range'),
                group: 'week'
            };

        $(window).trigger('changeview', initView);
    });

    $('.csv-table').csvTable();
})();
