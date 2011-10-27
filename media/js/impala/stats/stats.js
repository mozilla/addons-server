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
                group: 'day'
            };

        // Update the "Export as CSV" link when the view changes.
        (function() {
            var view = {},
                baseURL = $(".primary").attr("data-base_url");
            $(window).bind('changeview', function(e, newView) {
                _.extend(view, newView);
                var metric = view.metric,
                    range = normalizeRange(view.range),
                    url = baseURL + ([metric,'day',range.start.pretty(''),range.end.pretty('')]).join('-') + '.csv';
                $('#export_data').attr('href', url);
            });
        })();

        // set up notes modal.
        $('#stats-note').modal("#stats-note-link", { width: 520 });

        // Trigger the initial data load.
        $(window).trigger('changeview', initView);
    });

    $('.csv-table').csvTable();
})();
