$(function() {
    if ($('.primary').attr('data-report') != 'overview') return;

    // set up topcharts (defined in topchart.js)
    $('.toplist').topChart();

    $(window).bind("changeview", function(e, view) {
        $('.two-up').addClass('loading');
    });
    // Save some requests by waiting until the graph data is ready.
    $(window).bind("dataready", function(e, data) {
        // return;
        var view    = _.extend({}, data.view, {group: 'all'}),
            range   = normalizeRange(view.range);

        // get aggregates for Daily Users and Downloads for the given time range.
        $.when(z.StatsManager.getDataRange(view)).then(function(data) {
            if (data.empty) {
                $("#downloads-in-range, #users-in-range").text(gettext('No data available.'));
            } else {
                // make all that data pretty.
                var aggregateRow    = data[data.firstIndex].data,
                    totalDownloads  = Highcharts.numberFormat(aggregateRow.downloads, 0),
                    totalUsers      = Highcharts.numberFormat(aggregateRow.updates, 0),
                    startString     = range.start.iso(),
                    endString       = range.end.iso(),
                    downloadFormat  = csv_keys.aggregateLabel.downloads,
                    userFormat      = csv_keys.aggregateLabel.usage;

                $("#downloads-in-range").html(format(downloadFormat,
                                                     totalDownloads,
                                                     startString,
                                                     endString));
                $("#users-in-range").html(format(userFormat,
                                                 totalUsers,
                                                 startString,
                                                 endString));
            }
            $('.two-up').removeClass('loading');
        });
    });
});