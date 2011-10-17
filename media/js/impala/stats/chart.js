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
                        enabled: false,
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
        "usage"     : "users",
        "apps"      : "users",
        "locales"   : "users",
        "os"        : "users",
        "versions"  : "users",
        "statuses"  : "users",
        "downloads" : "downloads",
        "sources"   : "downloads"
    };
    
    $win.bind("changeview", function() {
        $chart.addClass('loading');
    });

    $win.bind("dataready", function(e, obj) {
        var view    = obj.view,
            metric  = view.metric,
            group   = view.group,
            range   = z.date.normalizeRange(view.range),
            start   = range.start,
            end     = range.end,
            fields  = obj.fields ? obj.fields.slice(0,5) : ['count'],
            data    = obj.data,
            series  = {},
            chartRange = {},
            t, row, i, field, val;

        // Initialize the empty series object.
        _.each(fields, function(f) { series[f] = []; });

        // Transmute the data into something Highcharts understands.
        if (group == 'month') {
            _.each(data, function(row, t) {
                for (i = 0; i < fields.length; i++) {
                    field = fields[i];
                    val = parseFloat(z.StatsManager.getField(row, field));
                    if (val != val) val = null;
                    series[field].push({
                        'x' : parseInt(t, 10),
                        'y' : val
                    });
                }
            });
        } else {
            var step = z.date.millis('1 day');
            if (group == 'week') {
                step = z.date.millis('7 days');
                while((new Date(start)).getDay() > 0) {
                    start += z.date.millis('1 day');
                }
            }
            for (t = start; t < end; t += step) {
                row = data[t];
                for (i = 0; i < fields.length; i++) {
                    field = fields[i];
                    val = parseFloat(z.StatsManager.getField(row, field));
                    if (val != val) val = null;
                    series[field].push({
                        'x' : t,
                        'y' : val
                    });
                }
            }
        }

        // Populate the chart config object.
        var chartData = [], id;
        for (i = 0; i < fields.length; i++) {
            field = fields[i];
            id = field.split("|").slice(-1)[0];
            chartData.push({
                'type'  : 'line',
                'name'  : z.StatsManager.getPrettyName(view.metric, id),
                'id'    : id,
                'data'  : series[field]
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
            if (group == "week") {
                xFormatter = weekFormatter;
            } else if (group == "month") {
                xFormatter = monthFormatter;
            } else {
                xFormatter = dayFormatter;
            }
            if (metric == 'overview') {
                return function() {
                    return "<b>" + xFormatter(this.x) + "</b><br>" +
                           downloadFormatter(this.points[0].y) + "<br>" +
                           userFormatter(this.points[1].y);
                };
            } else {
                if (metricTypes[metric] == "users") {
                    yFormatter = userFormatter;
                } else {
                    yFormatter = downloadFormatter;
                }
                return function() {
                    return "<b>" + this.series.name + "</b><br>" +
                           xFormatter(this.x) + "<br>" +
                           yFormatter(this.y);
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
                        // min: 0,
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
                        // min: 0,
                        opposite: true
                    }
                ],
                tooltip: {
                    shared : true,
                    crosshairs : true
                }
            });
            // set Daily Users series to use the right yAxis.
            newConfig.series[1].yAxis = 1;
        }
        newConfig.tooltip.formatter = tooltipFormatter;

        if (fields.length == 1) {
            newConfig.legend.enabled = false;
            // newConfig.chart.margin = [50, 50, 50, 80];
        }

        // Generate a pretty title for the chart.
        var title;
        if (typeof obj.view.range == 'string') {
            title = format(csv_keys.chartTitle[metric][0], obj.view.range);
        } else {
            title = format(csv_keys.chartTitle[metric][1], [z.date.date_string(new Date(start), '-'),
                                                            z.date.date_string(new Date(end), '-')]);
        }
        newConfig.title = {
            text: title
        };

        if (chart) chart.destroy();
        chart = new Highcharts.Chart(newConfig);
        chartRange = chart.xAxis[0].getExtremes();
        $("h1").click(function() {
            chart.xAxis[0].setExtremes(chartRange.min, chartRange.max);
        })
        $chart.removeClass('loading');
    });
})();