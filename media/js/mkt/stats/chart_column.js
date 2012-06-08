(function () {
    // 'use strict';
    var $win = $(window),
        $chart = $('#head-chart'),
        baseConfig = {
            chart: {
                renderTo: 'head-chart',
                type: 'column'
            },
            credits: { enabled: false },
            title: {
                text: null
            },
            xAxis: {
                title: {
                    text: null
                },
                tickmarkPlacement: 'on'
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
                minPadding: 0.05
            },
            legend: {
                enabled: false
            },
            plotOptions: {
                column: {
                    colorByPoint: true,
                    shadow: false
                }
            },
            tooltip: { },
            series: [{
                data: []
            }]
        },
        chart;

    // Determines unit used for a given metric.
    var xMetricTypes = z.StatsManager.metricKeys;
    var yMetricTypes = {
        'currency_revenue' : 'currency',
        'currency_sales'   : 'sales',
        'currency_refunds' : 'refunds'
    };

    function showNoDataOverlay() {
        $chart.parent().addClass('nodata');
        $chart.parent().removeClass('loading');
        if (chart && chart.destroy) chart.destroy();
    }

    $win.bind('changeview', function() {
        $chart.parent().removeClass('nodata');
        $chart.addClass('loading');
    });

    $win.bind('dataready', function(e, obj) {
        var view    = obj.view,
            metric  = view.metric,
            data    = obj.data,
            t, row, i, field, val;
        z.data  = data;

        if (!(metric in z.StatsManager.nonDateMetrics)) {
            return;
        }
        if (obj.data.empty) {
            showNoDataOverlay();
            $chart.removeClass('loading');
            return;
        }

        // Disable irrelevant links and controls.
        var inactive = function() { return false; };
        $('.range li a').addClass('inactive').bind('click', inactive);
        $('.group li a').addClass('inactive').bind('click', inactive);

        // Populate chart with categories (xAxis values) and data points.
        var categories = [],
            dataPoints = [];
        _.each(data, function(datum) {
            // xMetricTypes doubles for metricKeys.
            categories.push(datum[xMetricTypes[metric]]);
            dataPoints.push(datum.count);
        });
        baseConfig.xAxis.categories = categories;
        baseConfig.series[0].data = dataPoints;

        // Set minimum max value for yAxis to prevent duplicate yAxis values.
        var max = 0;
        _.each(data, function(datum) {
            if (datum.count > max) {
                max = datum.count;
            }
        });
        // Chart has minimum 5 ticks so set max to 5 to avoid pigeonholing.
        if (max < 5) {
            baseConfig.yAxis.max = 5;
        }

        // Generate the tooltip function for this chart.
        // both x and y axis can be displayed differently.
        baseConfig.tooltip.formatter = (function(){
            var xFormatter,
                yFormatter;

            function currencyFormatter(currency) { return format(gettext('by currency {0}'), currency); }
            function moneyFormatter(n) { return '$' + Highcharts.numberFormat(n, 2); }
            function salesFormatter(n) { return format(gettext('{0} sales'), Highcharts.numberFormat(n, 0)); }
            function refundsFormatter(n) { return format(gettext('{0} refunds'), Highcharts.numberFormat(n, 0)); }

            // Determine y-axis formatter.
            switch(xMetricTypes[metric]) {
                case 'currency':
                    baseConfig.xAxis.title.text = 'Currency';
                    xFormatter = currencyFormatter;
                    break;
            }

            // Determine y-axis formatter.
            switch (yMetricTypes[metric]) {
                case 'currency':
                    baseConfig.yAxis.title.text = 'Revenue';
                    yFormatter = moneyFormatter;
                    break;
                case 'sales':
                    baseConfig.yAxis.title.text = 'Sales';
                    yFormatter = salesFormatter;
                    break;
                case 'refunds':
                    baseConfig.yAxis.title.text = 'Refunds';
                    yFormatter = refundsFormatter;
                    break;
            }

            return function() {
                var ret = '<b>' + z.StatsManager.getPrettyName(metric, 'count') + '</b><br>' +
                          xFormatter(this.x) + '<br>' +
                          yFormatter(this.y);
                return ret;
            };
        })();

        // Set up the new chart's configuration.
        var newConfig = $.extend(baseConfig, {});

        // Generate chart title.
        var title;
        title = format(csv_keys.chartTitle[metric][1], []);
        newConfig.title = {
            text: title
        };

        if (chart && chart.destroy) chart.destroy();
        chart = new Highcharts.Chart(newConfig);
        $chart.removeClass('loading');
    });
})();
