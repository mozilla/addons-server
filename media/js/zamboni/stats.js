$(document).ready(function () {
    var csvTable;
    jQuery.fn.getData = function(name) {
        return this.attr("data-" + name);
    };

    page_state.addon_id = $(".primary").getData("addon_id");
    page_state.report_name = $(".primary").getData("report");
    page_state.data_range = "30 days";
    page_state.chart_fields = $("#head-chart").getData("series").split(',') || ["count"];
    var stats_base_url = $(".primary").getData("base_url");
    AMO.aggregate_stats_field = $(".stats-aggregate").getData("field");
    AMO.getAddonId = function () { return page_state.addon_id };
    AMO.getReportName = function () { return page_state.report_name };
    AMO.getSeriesList = function () {        return {
            "metric": page_state.report_name,
            "fields": page_state.chart_fields
        }
    };
    AMO.getStatsBaseURL = function () { return stats_base_url };
    t.go();
    AMO.StatsManager.init();
    t.lap("StatsManager init");

    var report = AMO.getReportName();

    $.datepicker.setDefaults({showAnim: ''});

    $("#date-range-start").datepicker();
    $("#date-range-end").datepicker();

    t.lap("datepicker init");

    var rangeMenu = $(".criteria.range ul");

    rangeMenu.click(function(e) {
        var $target = $(e.target).parent();
        var newRange = $target.attr("data-range");
        var $customRangeForm = $("div.custom.criteria");

        if (newRange) {
            $(this).children("li.selected").removeClass("selected");
            $target.addClass("selected");

            if (newRange == "custom") {
                $customRangeForm.removeClass("hidden").slideDown('fast');
            } else {
                page_state.data_range = newRange;
                $customRangeForm.slideUp('fast');
                AMO.StatsManager.getSeries(AMO.getSeriesList(), page_state.data_range, updateSeries);
                if (AMO.aggregate_stats_field) {
                    show_aggregate_stats(AMO.aggregate_stats_field, page_state.data_range);
                }
            }
        }
        e.preventDefault();
    });

    $("#date-range-form").submit(function() {
        var start = new Date($("#date-range-start").val());
        var end = new Date($("#date-range-end").val());

        page_state.data_range = {
            custom: true,
            start: start,
            end: end
        };
        AMO.StatsManager.getSeries(AMO.getSeriesList(), page_state.data_range, updateSeries);
        return false;
    });

    t.lap("events init");

    if (report == "overview") {
        page_state.report_name = 'downloads';
        var series_menu = $("#series-select");

        series_menu.click(function(e) {
            var $target = $(e.target);
            var new_report = $target.getData("report");
            var new_series = $target.getData("series");
            if (new_series && new_report != AMO.getReportName()) {
                series_menu.children("li.selected").removeClass("selected");
                $target.parent().addClass("selected");
                page_state.report_name = new_report;
                page_state.data_fields = new_series;
                AMO.StatsManager.getSeries(AMO.getSeriesList(), page_state.data_range, initCharts);
            }
            e.preventDefault();
        });        // generate_top_charts();

        // initTopCharts();
    } else {
        var csv_table_el = $(".csv-table");
        if (csv_table_el.length) {
            csvTable = new PageTable(csv_table_el[0]);
        }

        t.lap("csvtable init");
    }

    LoadBar.on("Loading the latest data&hellip;");
    //Get initial dataset
    if (datastore[report] && datastore[report].maxdate) {
        var fetchStart = datastore[report].maxdate - millis("1 day");
    } else {
        var fetchStart = ago("30 days");
    }
    t.go("fetching data")

    AMO.StatsManager.getDataRange(AMO.getReportName(), fetchStart, today(), function () {
        t.lap("building aggregate stats")
        if (AMO.aggregate_stats_field) {
            show_aggregate_stats(AMO.aggregate_stats_field, page_state.data_range);
        }
        t.lap("building initial chart stuff")
        AMO.StatsManager.getSeries(AMO.getSeriesList(), "30 days", initCharts);
        LoadBar.off();
        if (csvTable) {
            csvTable.gotoPage(1);
        }
    }, {force: true});

});



    var mainChart;

    function dayFormatter(x) { return Highcharts.dateFormat('%a, %b %e, %Y', x); }
    function weekFormatter(x) { return Highcharts.dateFormat('%b %e - ', x) + Highcharts.dateFormat('%b %e, %Y', x+7*24*60*60*1000); }
    function monthFormatter(x) { return Highcharts.dateFormat('%B %Y', x); }

    function downloadFormatter(y) { return Highcharts.numberFormat(y, 0) + ' downloads'; }
    function userFormatter(y) { return Highcharts.numberFormat(y, 0) + ' users'; }
    function currencyFormatter(y) { return '$' + Highcharts.numberFormat(y, 2); }

    function numberLabelFormatter(i) { return Highcharts.numberFormat(i, 0); }
    function currencyLabelFormatter(i) { return '$' + Highcharts.numberFormat(this.value, 2); }

    function repeat(str, n) {
      return new Array( n + 1 ).join( str );
    }

    function Timer() {
    }
    Timer.prototype.go = function(msg) {
        this.stime = (new Date()).getTime();
        if (msg) dbg(msg);
    };
    Timer.prototype.lap = function(msg) {
        var oltime = this.ltime || this.stime;
        this.ltime = (new Date()).getTime();
        dbg(this.ltime - oltime, msg);
    };

    var t = new Timer();

    function dbg() {
        if(window.console && window.console.log) {
            window.console.log(Array.prototype.slice.apply(arguments));
        }
    }

    function updateSeries(cfg) {
        for (var i=0; i<cfg.length; i++) {
            var series = mainChart.get(cfg[i].id);
            if (series) {
                series.setData(cfg[i].data);
            }
        }
    }
    function draw_diff(el, current, previous) {
        if (current.nodata || previous.nodata) return;
        var diffel = $(el);
        var diff = Math.round((current - previous) * 100 / previous);
        if (diff > 0) {
            diffel.addClass("plus");
        }
        if (diff < 0) {
            diffel.addClass("minus");
        }
        diffel.text((diff >= 0 ? '+' : '') + diff + "%");
    }


    function initCharts(cfg) {
        if (mainChart) {
            mainChart.destroy();
        }
        mainChart = new Highcharts.Chart({
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
                startOnTick: false,
                showFirstLabel: false
            },
            tooltip: {
                formatter: function() {
                    return dayFormatter(new Date(this.x)) + '<br/>'+
                        "<b>" + downloadFormatter(this.y) + "</b>";
                }
            },
            legend: {
                enabled: false
            },
            plotOptions: {
                line: {
                    lineWidth: 1,
                    animation: false,
                    marker: {
                        enabled: false,
                        states: {
                           hover: {
                              enabled: true,
                              radius: 3
                           }
                        }
                     },
                 states: {
                    hover: {
                       lineWidth: 1
                    }
                 }
              }
           },
           series: cfg
        });

    }



// })();


function initTopCharts() {

    $(".toplists .toplist").each(function (i, el) {

        var table = $("table", el)[0],
            container = $(".piechart", el)[0],
            rows = $('tbody tr', table);

        function fancyParse(x) {
            return parseFloat(x.replace(",", ""));
        }

        if (table) {
            var topchart1 = new Highcharts.Chart({
               chart: {
                  renderTo: container,
                  margin: 0,
                  height:200,
                  width:210
               },
               title: {
                  text: null
               },
               plotArea: {
                  shadow: null,
                  borderWidth: null,
                  backgroundColor: null
               },
               tooltip: {
                  formatter: function() {
                     return '<b>'+ this.point.name +'</b>: '+ Highcharts.numberFormat(this.y, 0);
                  }
               },
               plotOptions: {
                  pie: {
                     allowPointSelect: true,
                     data: 'datatable',
                     dataParser: function(data) {
                        var result = [];
                        // loop through the rows and get the data depending on the series (this) name
                        for (var i = 0; i < rows.length; i++) {
                           var row = $(rows[i]).children();
                           result.push(
                              [$(row[0]).text(), fancyParse($(row[1]).text())]
                           );
                        }
                        return result;
                     },
                     dataLabels: {
                        enabled: false,
                        color: '#333'
                     },
                     size:190
                  }
               },
               credits: {enabled:false},
               legend: {
                  enabled:false
               },
                  series: [{
                  type: 'pie',
               }]
            });
            for (var i = 0; i < rows.length; i++) {
               var row = $(rows[i]).children();
               $(row[0]).append($("<b class='seriesdot' style='background:" + topchart1.series[0].data[i].color + "'>&nbsp;</b>"));
            }
        } // end if(table)
    });
}

function show_aggregate_stats (_field, range) {
    field = {
        metric: AMO.getReportName(),
        name: _field
    }
    $(".stats-aggregate .range").text("Last " + range);
    $(".stats-aggregate .prev_range").text("Prior " + range);

    AMO.StatsManager.getSum(field, ago(range, 3), ago(range, 2) + millis("1 day"), function(sum_3x_range) {
        AMO.StatsManager.getSum(field, ago(range, 2), ago(range) + millis("1 day"), function(sum_prev_range) {
            AMO.StatsManager.getSum(field, ago(range), today(), function(sum_range) {

                $("#sum_range").text(Highcharts.numberFormat(sum_range, 0));
                $("#sum_prev_range").text(Highcharts.numberFormat(sum_prev_range, 0));
                draw_diff($("#sum_diff"), sum_range, sum_prev_range);
                draw_diff($("#sum_prev_diff"), sum_prev_range, sum_3x_range);
                AMO.StatsManager.getMean(field, ago(range, 3), ago(range, 2) + millis("1 day"), function(mean_3x_range) {
                    AMO.StatsManager.getMean(field, ago(range, 2), ago(range) + millis("1 day"), function(mean_prev_range) {
                        AMO.StatsManager.getMean(field, ago(range), today(), function(mean_range) {
                            $("#mean_range").text(Highcharts.numberFormat(mean_range, 0));
                            $("#mean_prev_range").text(Highcharts.numberFormat(mean_prev_range, 0));
                            draw_diff($("#mean_diff"), mean_range, mean_prev_range);
                            draw_diff($("#mean_prev_diff"), mean_prev_range, mean_3x_range);
                        });
                    });
                });
            });
        });
    });
}