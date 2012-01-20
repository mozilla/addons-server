(function () {
    // "use strict";
    var $win = $(window),
        $chart = $('#head-chart');
        baseConfig = {
            chart: {
              renderTo: 'head-chart',
              zoomType: 'x'
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
                startOnTick: false,
                showFirstLabel: false
            },
            legend: {
                enabled: true
            },
            tooltip: { },
            plotOptions: {
                line: {
                    lineWidth: 1,
                    animation: false,
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
                 }
              }
           }
        };
    Highcharts.setOptions({ lang: { resetZoom: '' } });
    var chart;
    // which unit do we use for a given metric?
    var metricTypes = {
        "usage"         : "users",
        "apps"          : "users",
        "locales"       : "users",
        "os"            : "users",
        "versions"      : "users",
        "statuses"      : "users",
        "downloads"     : "downloads",
        "sources"       : "downloads",
        "contributions" : "currency"
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
    });

    $win.bind("dataready", function(e, obj) {
        var view    = obj.view,
            metric  = view.metric,
            group   = view.group,
            data    = obj.data,
            range   = normalizeRange(view.range),
            start   = range.start,
            end     = range.end,
            fields  = obj.fields ? obj.fields.slice(0,5) : ['count'],
            series  = {},
            events  = obj.events,
            chartRange = {},
            t, row, i, field, val;

        if (!(group in acceptedGroups)) {
            group = 'day';
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
            point;
        forEachISODate({start: start, end: end}, '1 '+group, data, function(row, d) {
            for (i = 0; i < fields.length; i++) {
                field = fields[i];
                val = parseFloat(z.StatsManager.getField(row, field));
                if (val != val) val = null;
                point = {
                    'x' : d.getTime(),
                    'y' : val
                };
                series[field].push(point);
            }
        }, this);


        // Populate the chart config object.
        var chartData = [], id;
        for (i = 0; i < fields.length; i++) {
            field = fields[i];
            id = field.split("|").slice(-1)[0];
            chartData.push({
                'type'  : 'line',
                'name'  : z.StatsManager.getPrettyName(view.metric, id),
                'id'    : id,
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
            function weekFormatter(d) { return "Week of " + Highcharts.dateFormat('%b %e, %Y', new Date(d)); }
            function monthFormatter(d) { return Highcharts.dateFormat('%B %Y', new Date(d)); }
            function downloadFormatter(n) { return Highcharts.numberFormat(n, 0) + ' downloads'; }
            function userFormatter(n) { return Highcharts.numberFormat(n, 0) + ' users'; }
            function currencyFormatter(n) { return '$' + Highcharts.numberFormat(n, 2); }
            function addEventData(s, date) {
                var e = events[date];
                if (e) {
                    s += format('<br><br><b>{type_pretty}</b>', e);
                }
                return s;
            }

            // Determine x-axis formatter.
            if (group == "week") {
                xFormatter = weekFormatter;
            } else if (group == "month") {
                xFormatter = monthFormatter;
            } else {
                xFormatter = dayFormatter;
            }

            if (metric == 'overview') {
                return function() {
                    var ret = "<b>" + xFormatter(this.x) + "</b>",
                        p;
                    for (var i=0; i < this.points.length; i++) {
                        p = this.points[i];
                        ret += '<br>' + p.series.name + ': ';
                        ret += Highcharts.numberFormat(p.y, 0);
                    }
                    return addEventData(ret, this.x);
                };
            } else if (metric == 'contributions') {
                return function() {
                    var ret = "<b>" + xFormatter(this.x) + "</b>",
                        p;
                    for (var i=0; i < this.points.length; i++) {
                        p = this.points[i];
                        ret += '<br>' + p.series.name + ': ';
                        if (p.series.options.yAxis > 0) {
                            ret += Highcharts.numberFormat(p.y, 0);
                        } else {
                            ret += currencyFormatter(p.y);
                        }
                    }
                    return addEventData(ret, this.x);
                };
            } else {
                // Determine y-axis formatter.
                switch (metricTypes[metric]) {
                    case "users":
                        yFormatter = userFormatter;
                        break;
                    case "downloads":
                        yFormatter = downloadFormatter;
                        break;
                    case "currency":
                        yFormatter = currencyFormatter;
                        break;
                }
                return function() {
                    var ret = "<b>" + this.series.name + "</b><br>" +
                              xFormatter(this.x) + "<br>" +
                              yFormatter(this.y);
                    return addEventData(ret, this.x);
                };
            }
        })();

        // Set up the new chart's configuration.
        var newConfig = $.extend(baseConfig, { series: chartData });
        // set up dual-axes for the overview chart.
        if (metric == "overview" && newConfig.series.length) {
            _.extend(newConfig, {
                yAxis : [
                    { // Downloads
                        title: {
                           text: gettext('Downloads')
                        },
                        min: 0,
                        labels: {
                            formatter: function() {
                                return Highcharts.numberFormat(this.value, 0);
                            }
                        }
                    }, { // Daily Users
                        title: {
                            text: gettext('Daily Users')
                        },
                        labels: {
                            formatter: function() {
                                return Highcharts.numberFormat(this.value, 0);
                            }
                        },
                        min: 0,
                        opposite: true
                    }
                ],
                tooltip: {
                    shared : true,
                    crosshairs : true
                }
            });
            // set Daily Users series to use the right yAxis.
            _.find(newConfig.series,
                   function(s) { return s.id == 'updates'; }).yAxis = 1;
        }
        if (metric == "contributions" && newConfig.series.length) {
            _.extend(newConfig, {
                yAxis : [
                    { // Amount
                        title: {
                            text: gettext('Amount, in USD')
                        },
                        labels: {
                            formatter: function() {
                                return Highcharts.numberFormat(this.value, 2);
                            }
                        },
                        min: 0
                    },
                    { // Number of Contributions
                        title: {
                           text: gettext('Number of Contributions')
                        },
                        min: 0,
                        labels: {
                            formatter: function() {
                                return Highcharts.numberFormat(this.value, 0);
                            }
                        },
                        opposite: true
                    }
                ],
                tooltip: {
                    shared : true,
                    crosshairs : true
                }
            });
            // set Daily Users series to use the right yAxis.
            newConfig.series[0].yAxis = 1;
        }
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
            title = format(csv_keys.chartTitle[metric][1], [start.iso(), end.iso()]);
        }
        newConfig.title = {
            text: title
        };

        if (chart && chart.destroy) chart.destroy();
        chart = new Highcharts.Chart(newConfig);

        chartRange = chart.xAxis[0].getExtremes();
        // $("h1").click(function() {
        //     chart.xAxis[0].setExtremes(chartRange.min, chartRange.max);
        // });
        $chart.removeClass('loading');
    });
})();