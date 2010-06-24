// (function () {

    // Versioning for offline storage
    var version = "4";

    // where all the time-series data for the page is kept
    var datastore = {};

    // where all the the computed ranges are kept
    var seriesCache = {};
    var range_limits = {
        mindate: 0,
        maxdate: today()
    };
    var page_state = {
    }
    var capabilities = {
        localStorage : ('localStorage' in window) && window['localStorage'] !== null,
        JSON : window.JSON && typeof JSON.parse == 'function'
    };

    var writeInterval = false;

    LoadBar = {
        bar : $("#lm"),
        msg : $("#lm span"),
        say : function (str) {
            LoadBar.msg.html(str);
        },
        on : function (str) {
            if (str) LoadBar.say(str);
            LoadBar.bar.addClass("on");
        },
        off : function () {
            LoadBar.bar.removeClass("on");
        }
    };

    // date management helpers

    var _millis = {
        "day" : 1000 * 60 * 60 * 24,
        "week" : 1000 * 60 * 60 * 24 * 7
    };

    function millis(str) {
        var tokens = str.split(/\s+/);
        n = parseInt(tokens[0]);
        unit = tokens[1].replace(/s$/,'').toLowerCase();
        return n * _millis[ unit ];
    }

    function pad2(n) {
        var str = n.toString();
        return ('0' + str).substr(-2);
    }

    function today() {
        var d = new Date();
        return Date.parse([d.getFullYear(), pad2(d.getMonth()+1), pad2(d.getDate()+1)].join('-'));
    }

    function ago (str, times) {
        times = (times !== undefined) ? times : 1;
        return today() - millis(str) * times;
    }


    /* cfg takes:
     * start: the initial value
     * end: the (non-inclusive) max value
     * step: value to iterate by
     * chunk-size: how many iterations before setTimeout
     * inner: function to perform each iteration
     * callback: function to perform when finished
     * ctx: context from which to run all functions
     */
    function chunkfor(cfg) {
        var position = cfg.start;

        function nextchunk() {
            if (position < cfg.end) {

                for (var iterator = position;
                     iterator < position+(cfg.chunk_size*cfg.step) && iterator < cfg.end;
                     iterator += cfg.step) {

                    cfg.inner.call(cfg.ctx, iterator);
                }

                position += cfg.chunk_size * cfg.step;

                setTimeout( function () {
                    nextchunk.call(this);
                }, 0);

            } else {
                cfg.callback.call(cfg.ctx);
            }
        }
        nextchunk();
    }

    document.onbeforeunload = function () {
        AMO.StatsManager.write_local();
    }

    AMO.StatsManager = {

        init: function () {
            if (capabilities.localStorage) {
                var local_store = localStorage;
                dbg("looking for local data");
                if (local_store.getItem("statscache") && AMO.StatsManager.verify_local()) {
                    var cacheObject = local_store.getItem("statscache-" + AMO.getAddonId());
                    dbg("found local data, loading...");
                    datastore = JSON.parse(cacheObject);
                }
            } else {
                dbg("no local storage");
            }
        },

        write_local: function () {
            dbg("saving local data");
            if (capabilities.localStorage) {
                dbg("user has local storage");
                var local_store = localStorage;
                local_store.setItem("statscache-" + AMO.getAddonId(), JSON.stringify(datastore));
                local_store.setItem("stats_version", version);
                dbg("saved local data");
            } else {
                dbg("no local storage");
            }
        },

        clear_local: function () {
            if (capabilities.localStorage) {
                var local_store = localStorage;
                local_store.removeItem("statscache-" + AMO.getAddonId());
                dbg("cleared local data");
            }
        },

        verify_local: function () {
            if (capabilities.localStorage) {
                var local_store = localStorage;
                if (local_store.getItem("stats_version") === version) {
                    return true;
                } else {
                    dbg("wrong offline data verion");
                    return false;
                }
            }
            return false;
        },

        _fetchData: function (metric, start, end, callback) {

            var seriesStart = start;
            var seriesEnd = end;

            var seriesURLStart = Highcharts.dateFormat('%Y%m%d', seriesStart),
                seriesURLEnd = Highcharts.dateFormat('%Y%m%d', seriesEnd),
                seriesURL = AMO.getStatsBaseURL() + ([metric,"day",seriesURLStart,seriesURLEnd]).join("-") + ".json";
            $.ajax({ url:       seriesURL,
                     dataType:  'text',
                     success:   function(raw_data, status, xhr) {

                var maxdate = 0,
                    mindate = today();

                if (xhr.status == 200) {

                    if (!datastore[metric]) {
                        datastore[metric] = {};
                        datastore[metric].mindate = today();
                        datastore[metric].maxdate = 0;
                    }

                    var ds = datastore[metric];
                    // process the Data. We want to directly use the native JSON
                    // without jQuery's costly regexes if we can.
                    if (capabilities.JSON) {
                        dbg("native JSON");
                        var data = JSON.parse(raw_data);
                    } else {
                        dbg("jQuery JSON");
                        var data = $.parseJSON(raw_data);
                    }

                    chunkfor({
                        start: 0,
                        end: data.length,
                        step: 1,
                        chunk_size: 10,
                        inner: function (i) {
                            var datekey = parseInt(Date.parse(data[i].date));
                            maxdate = Math.max(datekey, maxdate);
                            mindate = Math.min(datekey, mindate);
                            ds[datekey] = data[i];
                        },
                        callback: function () {
                            ds.maxdate = Math.max(parseInt(maxdate), parseInt(ds.maxdate));
                            ds.mindate = Math.min(parseInt(mindate), parseInt(ds.mindate));
                            callback.call(this, true);
                            clearTimeout(writeInterval);
                            writeInterval = setTimeout(AMO.StatsManager.write_local, 2000);
                        },
                        ctx: this
                    });


                } else if (xhr.status == 202) {

                    var retry_delay = 30000;

                    if (xhr.getResponseHeader("Retry-After")) {
                        retry_delay = parseInt(xhr.getResponseHeader("Retry-After")) * 1000;
                    }

                    setTimeout(function () {
                        AMO.StatsManager._fetchData(metric, start, end, callback);
                    }, retry_delay);

                }
            }});


        },

        /*
         * getDataRange: ensures we have all the data from the server we need,
         * and queues up requests to the server if the requested data is outside
         * the range currently stored locally. Once all server requests return,
         * we move on.
         */

        getDataRange: function (metric, start, end, callback, opts) {
            var needed = 0,
                opts = opts || {};
                quiet = opts.quiet || false,
                force = opts.force || false;

            end = Math.min(end, range_limits.maxdate);

            function finished() {
                needed--;
                if (datastore[metric] && datastore[metric].maxdate < end) {
                    dbg("truncating fetchable range");
                    range_limits.maxdate = datastore[metric].maxdate;
                }
                if (needed < 0) {
                    callback.call(this);
                    LoadBar.off();
                } else {
                    if (!quiet) LoadBar.on("Loading&hellip;");
                }
            }

            if (datastore[metric] && !force) {
                ds = datastore[metric];
                if (ds.maxdate < end) {
                    needed++;
                    AMO.StatsManager._fetchData(metric, ds.maxdate, end, finished);
                }
                if (ds.mindate > start) {
                    needed++;
                    AMO.StatsManager._fetchData(metric, start, ds.mindate, finished);
                }
            } else {
                needed++;
                AMO.StatsManager._fetchData(metric, start, end, finished);
            }

            finished();
        },

        getSeries: function (seriesList, time, callback) {
            metric = seriesList.metric;
            if (typeof time == "string") {
                var cacheKey = metric + "_" + time.replace(/\s/g, '_');

                var seriesStart = ago(time);
                var seriesEnd = today();
            } else if (typeof time == "object" && time.custom) {
                var cacheKey = metric + "_" + time.start + "_" + time.end;

                var seriesStart = time.start.getTime();
                var seriesEnd = time.end;
            } else {
                return false;
            }

            if (seriesCache[cacheKey]) {

                callback.call(this, seriesCache[cacheKey]);

            } else {

                AMO.StatsManager.getDataRange(metric, seriesStart, seriesEnd, function() {
                    var out = {};
                    var fields = seriesList.fields;
                    var data = datastore[metric];

                    for (var j=0; j<fields.length; j++) {
                        out[fields[j]] = [];
                    }

                    chunkfor({
                        start: seriesStart,
                        end: seriesEnd,
                        step: millis("1 day"),
                        chunk_size: 10,
                        inner: function (i) {
                            for (var j=0; j<fields.length; j++) {
                                var val = data[i] ? AMO.StatsManager.getField(data[i], fields[j]) : null;
                                var point = {
                                    x : i,
                                    y : val ? parseFloat(val) : null
                                };
                                out[fields[j]].push(point);
                            }
                        },
                        callback: function () {
                            var ret = [];
                            for (var j=0; j<fields.length; j++) {
                                ret.push({
                                    type: 'line',
                                    id: fields[j],
                                    data: out[fields[j]]
                                });
                            }
                            seriesCache[cacheKey] = ret;
                            callback.call(this, ret);
                        },
                        ctx: this
                    });

                });
            }
        },

        getPage: function(metric, num, callback, size) {
            size = size || 14;
            var cacheKey = metric + "_page_" + num + "_by_" + size;

            if (seriesCache[cacheKey]) {
                if (!seriesCache[cacheKey].nodata) {
                    callback.call(this, seriesCache[cacheKey]);
                }
            } else {
                var ds = datastore[metric];

                var seriesEnd = ds.maxdate - size * (num - 1) * millis("1 day");


                // Why times 2? I'm pre-fetching the next page.
                var seriesStart = seriesEnd - size * millis("1 day");
                var dataStart = seriesStart - size * millis("1 day");

                AMO.StatsManager.getDataRange(metric, dataStart, seriesEnd, function() {

                    var ret = [];

                    ret.page = num;

                    for (var i=seriesEnd; i>seriesStart; i-= millis("1 day")) {
                        if (ds[i] !== undefined) ret.push(ds[i]);
                    }

                    if (ret.length) {
                        seriesCache[cacheKey] = ret;

                        callback.call(this, ret);
                    } else {
                        seriesCache[cacheKey] = {nodata:true};
                    }

                });

            }

        },

        getNumPages: function(metric, size) {
            size = size || 14;

            var ds = datastore[metric];

            return Math.ceil((ds.maxdate - ds.mindate) / millis("1 day") / size);
        },

        getSum: function(field, start, end, callback, name) {
            var metric = field.metric;
            var cacheKey = name || (metric + field.name + "_sum_" + start + "_" + end);

            if (seriesCache[cacheKey]) {
                callback.call(this, seriesCache[cacheKey]);
            } else {
                AMO.StatsManager.getDataRange(metric, start, end, function () {
                    var ds = datastore[metric];

                    var sum = 0;

                    var nodata = true;

                    for (var i=start; i<end; i+= millis("1 day")) {
                        if (ds[i] !== undefined) {
                            var datum = AMO.StatsManager.getField(ds[i], field.name);
                            if (datum !== undefined) {
                                nodata = false;
                                sum += parseFloat(datum);
                            }
                        }
                    }

                    if (nodata) {
                        var ret = {nodata: true};
                    } else {
                        var ret = sum;
                    }

                    seriesCache[cacheKey] = ret;

                    callback.call(this, ret);

                });
            }
        },

        getMean: function(field, start, end, callback) {
            var metric = field.metric;

            AMO.StatsManager.getSum(field, start, end, function (sum) {
                if (sum.nodata) {
                    callback.call(this, sum);
                } else {
                    var mean = sum / ((end - start) / millis("1 day"));
                    callback.call(this, mean);
                }
            });

        },

        getStat: function(name) {
            return seriesCache[name] || {nodata: true};
        },

        getField: function(record, field) {

            var parts = field.split('|');
            var val = record;

            for (var i=0; i<parts.length; i++) {
                val = val[parts[i]];
                if (!val) {
                    return null;
                }
            }

            return val;

        }


    };
// })();