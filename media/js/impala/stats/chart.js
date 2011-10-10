(function () {
    var $win = $(window),
        baseConfig = {
            chart: {
              renderTo: 'head-chart',
              zoomType: 'x',
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
        var chartData = [], id
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
            if (metricTypes[metric] == "users") {
                yFormatter = userFormatter;
            } else {
                yFormatter = downloadFormatter;
            }
            return function() {
                return "<b>" + this.series.name + "</b><br>" +
                       xFormatter(this.x) + "<br>" +
                       yFormatter(this.y);
            }
        })();

        // Set up the new chart's configuration.
        var newConfig = $.extend(baseConfig, { series: chartData });
        if (fields.length == 1) {
            newConfig.legend.enabled = false;
            newConfig.chart.margin = [50, 50, 50, 80]
        }
        newConfig.tooltip.formatter = tooltipFormatter;


        if (chart) chart.destroy();
        chart = new Highcharts.Chart(newConfig);
    });
})();