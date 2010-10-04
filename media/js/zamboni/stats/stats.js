function dbg() {
    if (capabilities.debug) {
        if(capabilities.console && !capabilities.debug_in_page) {
            window.console.log(Array.prototype.slice.apply(arguments));
        }
        if (capabilities.debug_in_page) {
            var args = Array.prototype.slice.apply(arguments);
            $("#dbgout").append(args.join("\t"));
            $("#dbgout").append("\n");
        }
    }
}

var mainChart;

function set_loading(el) {
    $(el).removeClass('loaded').addClass('loading');
}

function get_page_state(_opts) {
    var params = {},
        pairs, str, qstr;
        
    if (window.location.hash) {
        str = window.location.hash;
        if (str != page_state.last_hash) {
            qstr = str.substr(1);
            pairs = qstr.split('&');
            $(pairs).each(function (i,v) {
                pair = v.split('=');
                if (pair.length >= 2) {
                    params[pair[0]] = pair[1];
                } else {
                    params[pair[0]] = true;
                }
            });

            if ('start' in params && 'end' in params) {
                var sd = params.start;
                var ed = params.end;
                var start_date = sd.substr(0,4) + "/" + sd.substr(4,2) + "/" + sd.substr(6,2);
                var end_date = ed.substr(0,4) + "/" + ed.substr(4,2) + "/" + ed.substr(6,2);
                start_date = new Date(start_date);
                end_date = new Date(end_date);
                $("#date-range-start").val(datepicker_format(start_date));
                $("#date-range-end").val(datepicker_format(end_date));
                page_state.data_range = {
                    custom: true,
                    start: date(start_date),
                    end: date(end_date),
                    sd_str: sd,
                    ed_str: ed
                };
                
                $('.criteria li.selected').removeClass("selected");
                $('.criteria li[data-range~="custom"]').addClass("selected");
                
                if (!_opts.skip_update) {
                    update_page_state();
                }
                return true;
            } else if ('last' in params) {
                var data_range = params.last;
                if (("7 30 90").indexOf(data_range) > -1) {
                    page_state.data_range = data_range + " days";
                    
                    $('.criteria li.selected').removeClass("selected");
                    $('.criteria li[data-range~="'+data_range+'"]').addClass("selected");
                    
                    if (!_opts.skip_update) {
                        update_page_state();
                    }
                    return true;
                }
            }
        }
    }
    return false;
}

function update_page_state() {
    if ($(".primary").getData("report") == 'overview') {
        show_overview_stats(page_state.data_range);
        fetch_top_charts();
    }
    // set_loading($("#head-chart").parents('.featured'));
    headerChart.render({
        metric: AMO.getReportName(),
        time:   page_state.data_range
    });
    if (AMO.aggregate_stats_field && typeof page_state.data_range == 'string') {
        show_aggregate_stats(AMO.aggregate_stats_field, page_state.data_range);
    }
    var start, end,
        range = page_state.data_range,
        queryparams;
        
    if (typeof range === "string") {
        range = parseInt(range);
        queryparams = 'last=' + range;
        start = ago(range + ' days');
        end = today();
    } else if (typeof range === "object" && range.custom) {
        start = new Date(range.start);
        end = new Date(range.end);
        queryparams = 'start=' + range.sd_str + '&end=' + range.ed_str;
    } else {
        return false;
    }
    
    var seriesURL = AMO.getStatsBaseURL() + ([AMO.getReportName(),"day",Highcharts.dateFormat('%Y%m%d', start),Highcharts.dateFormat('%Y%m%d', end)]).join("-") + ".csv";
    $('#export_data').attr('href', seriesURL);
    
    if (capabilities.replaceState) {
        history.replaceState(page_state, document.title, '?' + queryparams);
    } else {
        page_state.last_hash = '#' + queryparams;
        window.location.hash = '#' + queryparams;
    }
    start_hash_check();
}

function dayFormatter(x) { return Highcharts.dateFormat('%a, %b %e, %Y', x); }
function weekFormatter(x) { return Highcharts.dateFormat('%b %e - ', x) + Highcharts.dateFormat('%b %e, %Y', x+7*24*60*60*1000); }
function monthFormatter(x) { return Highcharts.dateFormat('%B %Y', x); }

function downloadFormatter(y) { return Highcharts.numberFormat(y, 0) + ' downloads'; }
function userFormatter(y) { return Highcharts.numberFormat(y, 0) + ' users'; }
function currencyFormatter(y) { return '$' + Highcharts.numberFormat(y, 2); }

function numberLabelFormatter(i) { return Highcharts.numberFormat(this.value, 0); }
function currencyLabelFormatter(i) { return '$' + Highcharts.numberFormat(this.value, 2); }

function repeat(str, n) {
  if (n) return new Array( n + 1 ).join( str );
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

function SeriesChart() {
    var chartObj;
    var currentView;
    var $fieldList = $("#fieldList");
    var $fieldMenu = $("#fieldMenu");
    var $legend;

    function drawLegend() {
        if (currentView.metric in breakdown_metrics) {
            var fields = chartObj.series;
            if (!$(".chart_legend").length) {
                $legend = $("<ul class='chart_legend'></ul>");
                $(".listing-header").append($legend);
            }
            var markup = ["<li><a id='changeFields' href='#'>change</a></li>"];
            for (var i = 0; i < fields.length; i++) {
               markup.push(
                   "<li class='series' data-field='",fields[i].id,"'>",
                   "<b class='seriesdot' style='background:",
                   fields[i].color,
                   "'>&nbsp;</b>",
                   fields[i].name,
                   "</li>");
            }
            $(".chart_legend").empty();
            $legend.html(markup.join(''));
        }
    }

    function drawFieldMenu() {
        var job = {
            task: "getFieldList",
            data: AMO.StatsManager.getDataSlice(
                currentView.metric,
                currentView.time,
                breakdown_metrics[currentView.metric]
            )
        };
        StatsWorkerPool.queueJob(stats_worker_url, job, function(msg, worker) {
            if ('success' in msg && msg.success) {
                var result = msg.result;
                menu = [];
                for (var i=0; i<result.length; i++) {
                    var v = result[i],
                        name = AMO.StatsManager.getPrettyName(
                            currentView.metric, v.split('|').join('_'));
                    menu.push([name,v]);
                }
                menu = menu.sort(function(a,b) { return a[0] > b[0] ? 1 : -1; });
                $fieldList.html($.map(menu, function(n) {
                    return "<li><label><input type='checkbox' name='field' value='" + n[1] + "'> " + n[0] + "</label></li>";
                }).join(''));
                $.each(currentView.fields, function(i,v) {
                    $("input[value='"+v+"']", $fieldList).attr('checked',true);
                });
            }
            return true;
        }, this);
    }
    
    this.init = function(cfg) {
        if (chartObj) chartObj.destroy();
        chartObj = new Highcharts.Chart(cfg);
        $("#fieldMenuPopup").popup("#changeFields", {
            delegate: $(".listing-header"),
            container: $(document.body),
            width: "auto",
            callback: function(obj) {
                var $popup = $(this),
                    cf = currentView.fields;
                return {"pointTo": obj.click_target};
            }
        });
        // $fieldMenu.submit(function(e) {
        $fieldMenu.delegate('input', 'change', function(e) {
            e.preventDefault();
            var newFields = [];
            $.map($(":checked", $fieldMenu), function(n) {
                newFields.push($(n).val());
            });
            self.render({'fields': newFields});
            csvTable.setColumns(newFields);
        });
    };
    this.render = function(view) {
        var newView = $.extend({}, currentView, view);
        dbg("rendering", newView);
        Series.get(newView, function(seriesSet) {
            var s = chartObj.series;
            while(chartObj.series.length) {
                chartObj.series[0].remove(false);
            }
            for (var i=0; i<seriesSet.length; i++) {
                chartObj.addSeries(seriesSet[i], false);
            }
            dbg(chartObj.series);
            chartObj.redraw();
            currentView = newView;
            if ('fields' in view) {
                drawLegend();
            }
            if ('time' in view) {
                drawFieldMenu();
            }
        });
    };
    this.chart = function() { return chartObj; };
    var self = this;
}

headerChart = new SeriesChart();
chartConfig = {
    chart: {
      renderTo: 'head-chart',
      zoomType: 'x',
      events: {
          redraw: done_loading,
          load: done_loading
      },          
      margin: [30,20,30,70]
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
            formatter: numberLabelFormatter
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
            lineWidth: 2,
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

function done_loading() {
    dbg("doneloading");
}

function initCharts(cfg) {
    if (mainChart.series.length > 1) {
        $(".listing-header").append($("<ul class='chart_legend'></ul>"));
        $legend = $('.chart_legend');
        for (var i = 0; i < mainChart.series.length; i++) {
           $legend.append($("<li style='display:block;float:right'><b class='seriesdot' style='background:" + mainChart.series[i].color + "'>&nbsp;</b>" + mainChart.series[i].name + "</li>"));
        }
    }
}



// })();


function initTopChart(el) {

    var table = $("table", el)[0],
        container = $(".piechart", el)[0],
        rows = $('tbody tr', table);

    function fancyParse(x) {
        return parseFloat(x.replace(",", ""));
    }

    if (table) {
        var data = [];
        for (var i = 0; i < rows.length; i++) {
           var row = $(rows[i]).children();
           data.push(
              [$(row[0]).text(), fancyParse($(row[1]).text())]
           );
        }
        
        var options = {
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
                data: data
           }]
        };
        var topchart1 = new Highcharts.Chart(options);
        for (var i = 0; i < rows.length; i++) {
           var row = $(rows[i]).children();
           $(row[0]).append($("<b class='seriesdot' style='background:" + topchart1.series[0].data.color + "'>&nbsp;</b>"));
        }
    } // end if(table)
}

function fetch_top_charts() {
    var start, end,
        range = page_state.data_range,
        toplists = $(".toplist");
    if (typeof range === "string") {
        start = ago(range);
        end = today();
    } else if (typeof range === "object" && range.custom) {
        start = range.start;
        end = range.end;
    } else {
        return false;
    }

    set_loading(toplists);
    toplists.each(function (i, toplist) {
        var tableEl = $("table", toplist);
        var report = tableEl.getData("report"),
            field = tableEl.getData("field"),
            tbody = ["<tbody>"];

        function renderTopChart(results) {
            var sums = results.sums;
            for (i=0; i<Math.min(sums.length, 5); i++) {
                var sum = sums[i];
                tbody.push("<tr>");
                tbody.push("<td>", AMO.StatsManager.getPrettyName(report, sum.field), "</td>");
                tbody.push("<td>", sum.sum, "</td>");
                tbody.push("<td>(", (sum.pct > 0 ? sum.pct : '<1'), "%)</td>");
                tbody.push("</tr>");
            }
            if (sums.length > 5) {
                var othersum = 0;
                for (i=5; i<sums.length; i++) {
                    othersum += sums[i].sum;
                }
                var pct = Math.floor(othersum * 100 / results.total);
                tbody.push("<tr>");
                tbody.push("<td>" + gettext('Other') + "</td>");
                tbody.push("<td>", othersum, "</td>");
                tbody.push("<td>(", (pct > 0 ? pct : '&lt;1'), "%)</td>");
                tbody.push("</tr>");

            }
            tbody.push("</tbody>");
            tableEl.html(tbody.join(''));
            initTopChart(toplist);
            $(toplist).addClass('loaded');
        }
            
        if (report && field) {
            RankedList.get({
                metric: report,
                field: field,
                time: {
                    start: start,
                    end: end
                }
            }, renderTopChart);
        }
    });
}

function show_overview_stats () {
    var start, end,
        range = page_state.data_range;
    if (typeof range === "string") {
        start = ago(range);
        end = today();
    } else if (typeof range === "object" && range.custom) {
        start = range.start;
        end = range.end;
    } else {
        return false;
    }
    AMO.StatsManager.getSum({metric: "downloads", name: "count"}, start, end, function(sum_range) {
        $("#sum_downloads_range").text(Highcharts.numberFormat(sum_range, 0));
    });
    AMO.StatsManager.getMean({metric: "usage", name: "count"}, start, end, function(mean_range) {
        $("#sum_usage_range").text(Highcharts.numberFormat(mean_range, 0));
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

var csvTable;

$(document).ready(function () {
    jQuery.fn.getData = function(name) {
        return this.attr("data-" + name);
    };
    headerChart.init(chartConfig);
    
    var $report_el = $(".primary");
    var data_range = $report_el.getData("range");
    page_state.addon_id = $report_el.getData("addon_id");
    page_state.report_name = $report_el.getData("report");

    if (!get_page_state({skip_update:true})) { //if no hash, get natural page state
        if (data_range == "custom") {
            var sd = $report_el.getData("start_date");
            var ed = $report_el.getData("end_date");
            start_date = sd.substr(0,4) + "/" + sd.substr(4,2) + "/" + sd.substr(6,2);
            end_date = ed.substr(0,4) + "/" + ed.substr(4,2) + "/" + ed.substr(6,2);
            $("#date-range-start").val(datepicker_format(new Date(start_date)));
            $("#date-range-end").val(datepicker_format(new Date(end_date)));
            start_date = new Date(start_date);
            end_date = new Date(end_date);
            page_state.data_range = {
                custom: true,
                start: date(start_date),
                end: date(end_date),
                sd_str: sd,
                ed_str: ed
            };
        } else {
            page_state.data_range = data_range;
        }
    }


    page_state.chart_fields = $("#head-chart").getData("series").split(',') || ["count"];
    var stats_base_url = $report_el.getData("base_url");
    AMO.aggregate_stats_field = $(".stats-aggregate").getData("field");
    AMO.getAddonId = function () { return page_state.addon_id };
    AMO.getReportName = function () { return page_state.report_name };
    AMO.getStatsBaseURL = function () { return stats_base_url };

    AMO.StatsManager.init();

    var report = AMO.getReportName();

    $.datepicker.setDefaults({showAnim: ''});

    $("#date-range-start").datepicker();
    $("#date-range-end").datepicker();

    var rangeMenu = $(".criteria.range ul");

    rangeMenu.click(function(e) {
        var $target = $(e.target).parent();
        var newRange = $target.attr("data-range");
        var $customRangeForm = $("div.custom.criteria");

        if (newRange) {
            stop_hash_check();
            $(this).children("li.selected").removeClass("selected");
            $target.addClass("selected");

            if (newRange == "custom") {
                $customRangeForm.removeClass("hidden").slideDown('fast');
                start_hash_check();
            } else {
                page_state.data_range = newRange;
                $customRangeForm.slideUp('fast');
                update_page_state();
            }
        }
        e.preventDefault();
    });

    $("#date-range-form").submit(function() {
        stop_hash_check();
        var start = new Date($("#date-range-start").val());
        var end = new Date($("#date-range-end").val());

        page_state.data_range = {
            custom: true,
            start: date(start),
            end: date(end),
            sd_str: date_string(start, ''),
            ed_str: date_string(end, '')
        };
        setTimeout(update_page_state,0);
        return false;
    });

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
                // set_loading($("#head-chart").parents('.featured'));
                headerChart.render({
                    metric: AMO.getReportName(),
                    fields: page_state.chart_fields,
                    time:   page_state.data_range
                });
            }
            e.preventDefault();
        });

    } else {
        var csv_table_el = $(".csv-table");
        if (csv_table_el.length) {
            csvTable = new PageTable(csv_table_el[0]);
        }
    }

    LoadBar.on(gettext("Loading the latest data&hellip;"));
    //Get initial dataset
    if (datastore[page_state.report_name] && datastore[page_state.report_name].maxdate) {
        var fetchStart = datastore[page_state.report_name].maxdate - millis("1 day");
    } else {
        var fetchStart = ago('30 days');
    }

    var seriesURL = AMO.getStatsBaseURL() + ([page_state.report_name,"day",Highcharts.dateFormat('%Y%m%d', ago('30 days')),Highcharts.dateFormat('%Y%m%d', today())]).join("-") + ".csv";
    $('#export_data').attr('href', seriesURL);

    AMO.StatsManager.getDataRange(AMO.getReportName(), fetchStart, today(), function () {

        if (AMO.aggregate_stats_field && typeof page_state.data_range == 'string') {
            show_aggregate_stats(AMO.aggregate_stats_field, page_state.data_range);
        }

        headerChart.render({
            metric: AMO.getReportName(),
            fields: page_state.chart_fields,
            time:   page_state.data_range
        });

        LoadBar.off();
        if (csvTable) {
            csvTable.gotoPage(1);
        }
        if (report == 'overview') {
            fetch_top_charts();
            show_overview_stats(page_state.data_range);
        }
        start_hash_check();
    }, {force: true});

});
