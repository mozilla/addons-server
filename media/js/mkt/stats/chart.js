(function () {
    // "use strict";
    var $win = $(window),
        $chart = $('#head-chart'),
        $btnZoom = $('#chart-zoomout'),
        baseConfig = {
            chart: {
                renderTo: 'head-chart',
                zoomType: 'x',
                events: {
                    selection: function() {
                        $btnZoom.removeClass('inactive')
                                .click(_pd(function(e) {
                                    $(this).trigger('zoomout');
                                }));
                    }
                }
            },
            credits: { enabled: false },
            title: {
                text: null
            },
            xAxis: {
                type: 'datetime',
                maxZoom: 7 * 24 * 3600000, // seven days
                title: {
                    text: null
                },
                tickmarkPlacement: 'on',
                startOfWeek: 0,
                dateTimeLabelFormats: {
                    hour: '%e %b<br>%H:%M'
                }
            },
            yAxis: {
                title: {
                    text: null
                },
                labels: {
                    formatter: function() {
                        return Highcharts.numberFormat(this.value, 0);
                    }
                },
                min: 0,
                minPadding: 0.05,
                showFirstLabel: false
            },
            legend: {
                enabled: true
            },
            tooltip: { },
            plotOptions: {
                line: {
                    lineWidth: 1.5,
                    shadow: false,
                    marker: {
                        enabled: true,
                        radius: 0,
                        states: {
                           hover: {
                              enabled: true,
                              radius: 5
                           }
                        }
                    },
                    states: {
                        hover: {
                            lineWidth: 2
                        }
                    },
                    connectNulls: true
                }
            }
        };
    Highcharts.setOptions({ lang: { resetZoom: '' } });
    var chart;

    // Determine unit used for a given metric.
    // Missing keys here is the source of `TypeError: b is not a function`.
    var metricTypes = {
        'revenue'               : 'currency',
        'sales'                 : 'sales',
        'refunds'               : 'refunds',
        'installs'              : 'installs',
        'usage'                 : 'users',
        'reviews_created'       : 'reviews',
        'mmo_total_visitors'    : 'users',
        'mmo_user_count_total'  : 'users',
        'mmo_user_count_new'    : 'users',
        'apps_review_count_new' : 'reviews',
        'apps_count_installed'  : 'installs',
        'apps_count_new'        : 'apps'
    };

    var acceptedGroups = {
        'day'   : true,
        'week'  : true,
        'month' : true
    };

    function showNoDataOverlay() {
        $chart.parent().addClass('nodata');
        $chart.parent().removeClass('loading');
        if (chart && chart.destroy) chart.destroy();
    }

    $win.bind("changeview", function() {
        $chart.parent().removeClass('nodata');
        $chart.addClass('loading');
        $btnZoom.addClass('inactive').click(_pd);
    });

    $win.bind("dataready", function(e, obj) {
        var view    = obj.view,
            metric  = view.metric,
            group   = view.group,
            data    = obj.data,
            range   = normalizeRange(view.range),
            start   = range.start,
            end     = range.end,
            date_range_days = parseInt((end - start) / 1000 / 3600 / 24, 10),
            fields  = obj.fields ? obj.fields.slice(0,5) : ['count'],
            series  = {},
            events  = obj.events,
            chartRange = {},
            t, row, i, field, val,
            is_overview = metric == 'overview' || metric == 'app_overview';

        // Allows reuse of non-in-app code.
        metric = metric.replace('_inapp', '');

        // Let different function handle if metrics aren't a Highcharts
        // datetime line graph.
        if (metric in z.StatsManager.nonDateMetrics) {
            return;
        }

        if (!(group in acceptedGroups)) {
            group = 'day';
        }

        // Disable links if they don't fit into the date range.
        $('.group a, .range a').removeClass('inactive').unbind('click', false);
        if (group == 'week') {
            $('a.days-7').addClass('inactive').bind('click', false);
        } else if (group == 'month') {
            $('a.days-7, a.days-30').addClass('inactive').bind('click', false);
        }
        if (group == 'day') {
            $('a.group-day').parent().addClass('selected');
        }
        if (date_range_days <= 8) {
            $('a.group-week, a.group-month').addClass('inactive').bind('click', false);
        }
        if (date_range_days <= 31) {
            $('a.group-month').addClass('inactive').bind('click', false);
        }

        if (obj.data.empty || !data.firstIndex) {
            showNoDataOverlay();
            $chart.removeClass('loading');
            return;
        }

        // Initialize the empty series object.
        _.each(fields, function(f) { series[f] = []; });

        // Transmute the data into something Highcharts understands.
        start = Date.iso(data.firstIndex);
        z.data = data;
        var step = '1 ' + group,
            point,
            dataSum = 0;

        forEachISODate({start: start, end: end}, '1 '+group, data, function(row, d) {
            for (i = 0; i < fields.length; i++) {
                field = fields[i];
                val = parseFloat(z.StatsManager.getField(row, field));
                if (val != val) val = null;
                series[field].push(val);
                if (val) dataSum += val;
            }
        }, this);

        // Display marker if only one data point.
        baseConfig.plotOptions.line.marker.radius = 3;
        var count = 0,
            dateRegex = /\d{4}-\d{2}-\d{2}/;
        for (var key in data) {
            if (dateRegex.exec(key) && data.hasOwnProperty(key)) {
                count++;
            }
            if (count > 1) {
                baseConfig.plotOptions.line.marker.radius = 0;
                break;
            }
        }

        // highCharts seems to dislike 0 and null data when determining a yAxis range.
        if (dataSum === 0) {
            baseConfig.yAxis.max = 10;
        } else {
            baseConfig.yAxis.max = null;
        }

        // Transform xAxis based on time grouping (day, week, month) and range.
        var dayMsecs = 1 * 24 * 3600 * 1000;
        var pointInterval = dayMsecs;
        var dateRangeDays = (end - start) / dayMsecs;
        baseConfig.xAxis.min = start - dayMsecs; // Fix chart truncation.
        baseConfig.xAxis.max = end;
        baseConfig.xAxis.tickInterval = null;
        if (group == 'week') {
            $('a.days-7').addClass('inactive').bind('click', false);
            pointInterval = 7 * dayMsecs;
            baseConfig.xAxis.maxZoom = 7 * dayMsecs;

            if (dateRangeDays <= 90) {
                baseConfig.xAxis.tickInterval = 7 * dayMsecs;
            }
        } else if (group == 'month') {
            $('a.days-7, a.days-30').addClass('inactive').bind('click', false);
            pointInterval = 30 * dayMsecs;
            baseConfig.xAxis.maxZoom = 31 * dayMsecs;

            if (dateRangeDays <= 365) {
                baseConfig.xAxis.tickInterval = 30 * dayMsecs;
            }
        }

        // Disable group links if they don't fit into the date range.
        if (group == 'day') {
            $('a.group-day').parent().addClass('selected');
        }
        if (date_range_days <= 8) {
            $('a.group-week, a.group-month').addClass('inactive').bind('click', false);
        }
        if (date_range_days <= 31) {
            $('a.group-month').addClass('inactive').bind('click', false);
        }

        // Set minimum max value for yAxis to prevent duplicate yAxis values.
        var max = 0;
        for (key in data) {
            if (data[key].count > max) {
                max = data[key].count;
            }
        }
        // Chart has minimum 5 ticks so set max to 5 to avoid pigeonholing.
        if (max < 5) {
            baseConfig.yAxis.max = 5;
        }

        // Round the start time to the nearest day (truncate the time) and
        // account for time zone to line up ticks and points on datetime axis.
        date = new Date(start);
        date.setHours(0, 0, 0);
        start = date.getTime() - (date.getTimezoneOffset() * 60000);

        // Populate the chart config object.
        var chartData = [], id;
        for (i = 0; i < fields.length; i++) {
            field = fields[i];
            id = field.split("|").slice(-1)[0];
            chartData.push({
                'type'  : 'line',
                'name'  : z.StatsManager.getPrettyName(view.metric, id),
                'id'    : id,
                'pointInterval' : pointInterval,
                // Add offset to line up points and ticks on day grouping.
                'pointStart' : start,
                'data'  : series[field],
                'visible' : !(metric == 'contributions' && id !='total')
            });
        }

        // Generate the tooltip function for this chart.
        // both x and y axis can be displayed differently.
        var tooltipFormatter = (function(){
            var xFormatter,
                yFormatter;
            function dayFormatter(d) { return Highcharts.dateFormat('%a, %b %e, %Y', new Date(d)); }
            function weekFormatter(d) { return format(gettext('Week of {0}'), Highcharts.dateFormat('%b %e, %Y', new Date(d))); }
            function monthFormatter(d) { return Highcharts.dateFormat('%B %Y', new Date(d)); }
            function currencyFormatter(n) { return '$' + Highcharts.numberFormat(n, 2); }
            function salesFormatter(n) { return format(gettext('{0} sales'), Highcharts.numberFormat(n, 0)); }
            function refundsFormatter(n) { return format(gettext('{0} refunds'), Highcharts.numberFormat(n, 0)); }
            function installsFormatter(n) { return format(gettext('{0} installs'), Highcharts.numberFormat(n, 0)); }
            function userFormatter(n) { return format(gettext('{0} users'), Highcharts.numberFormat(n, 0)); }
            function appsFormatter(n) { return format(gettext('{0} apps'), Highcharts.numberFormat(n, 0)); }
            function reviewsFormatter(n) { return format(gettext('{0} reviews'), Highcharts.numberFormat(n, 0)); }
            function addEventData(s, date) {
                var e = events[date];
                if (e) {
                    s += format('<br><br><b>{type_pretty}</b>', e);
                }
                return s;
            }

            // Determine x-axis formatter.
            if (group == "week") {
                baseConfig.xAxis.title.text = gettext('Week');
                xFormatter = weekFormatter;
            } else if (group == "month") {
                baseConfig.xAxis.title.text = gettext('Month');
                xFormatter = monthFormatter;
            } else {
                baseConfig.xAxis.title.text = gettext('Day');
                xFormatter = dayFormatter;
            }

            // Determine y-axis formatter.
            switch (metricTypes[metric]) {
                case 'currency': case 'revenue':
                    baseConfig.yAxis.title.text = gettext('Amount Earned');
                    yFormatter = currencyFormatter;
                    break;
                case 'sales':
                    baseConfig.yAxis.title.text = gettext('Units Sold');
                    yFormatter = salesFormatter;
                    break;
                case 'refunds':
                    baseConfig.yAxis.title.text = gettext('Units Refunded');
                    yFormatter = refundsFormatter;
                    break;
                case 'installs':
                    baseConfig.yAxis.title.text = gettext('Installs');
                    yFormatter = installsFormatter;
                    break;
                case 'users':
                    baseConfig.yAxis.title.text = gettext('Users');
                    yFormatter = userFormatter;
                    break;
                case 'apps':
                    baseConfig.yAxis.title.text = gettext('Apps');
                    yFormatter = appsFormatter;
                    break;
                case 'reviews':
                    yFormatter = reviewsFormatter;
                    break;
            }
            return function() {
                var ret = "<b>" + this.series.name + "</b><br>" +
                          xFormatter(this.x) + "<br>" +
                          yFormatter(this.y);
                return addEventData(ret, this.x);
            };
        })();

        // Set up the new chart's configuration.
        var newConfig = $.extend(baseConfig, { series: chartData });
        newConfig.tooltip.formatter = tooltipFormatter;

        function makeSiteEventHandler(e) {
            return function() {
                var s = format('<h3>{type_pretty}</h3><p>{description}</p>', e);
                if (e.url) {
                    s += format('<p><a href="{0}" target="_blank">{1}</a></p>', [e.url, gettext('More Info...')]);
                }
                $('#exception-note h2').html(format(
                    // L10n: {0} is an ISO-formatted date.
                    gettext('Details for {0}'),
                    e.start
                ));
                $('#exception-note div').html(s);
                $chart.trigger('explain-exception');
            };
        }

        var pb = [], pl = [];
        eventColors = ['#DDD','#DDD','#FDFFD0','#D0FFD8'];
        _.forEach(events, function(e) {
            pb.push({
                color: eventColors[e.type],
                from: Date.iso(e.start).backward('12h'),
                to: Date.iso(e.end || e.start).forward('12h'),
                events: {
                    click: makeSiteEventHandler(e)
                }
            });
        });
        newConfig.xAxis.plotBands = pb;
        newConfig.xAxis.plotLines = pl;


        if (fields.length == 1) {
            newConfig.legend.enabled = false;
        }

        // Generate a pretty title for the chart.
        var title;
        if (typeof obj.view.range == 'string') {
            var numDays = parseInt(obj.view.range, 10);
            title = format(csv_keys.chartTitle[metric][0], numDays);
        } else {
            // This is a custom range so display a range shorter by one day.
            end = new Date(end.getTime() - (24 * 60 * 60 * 1000));
            title = format(csv_keys.chartTitle[metric][1], [new Date(start).iso(), end.iso()]);
        }
        newConfig.title = {
            text: title
        };

        if (chart && chart.destroy) chart.destroy();
        chart = new Highcharts.Chart(newConfig);

        chartRange = chart.xAxis[0].getExtremes();

        $win.bind('zoomout', function() {
            chart.xAxis[0].setExtremes(chartRange.min, chartRange.max);
            $btnZoom.addClass('inactive').click(_pd);
        });

        $chart.removeClass('loading');
    });
})();
