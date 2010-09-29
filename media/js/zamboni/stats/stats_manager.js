// (function () {

    // Versioning for offline storage
    var version = "7";

    // where all the time-series data for the page is kept
    var datastore = {};

    // where all the the computed ranges are kept
    var seriesCache = {};
    var range_limits = {
        mindate: 0,
        maxdate: today()
    };
    var pending_fetches = 0;
    var page_state = {};
    var capabilities = {
        'localStorage' : ('localStorage' in window) && window['localStorage'] !== null,
        'JSON' : window.JSON && typeof JSON.parse == 'function',
        'debug' : !(('' + document.location).indexOf("dbg") < 0),
        'debug_in_page' : !(('' + document.location).indexOf("dbginpage") < 0),
        'console' : window.console && (typeof window.console.log == 'function'),
        'replaceState' : typeof history.replaceState === "function"
    };

    var writeInterval = false;
    
    var hashInterval = false;
    
    function stop_hash_check() {
        clearInterval(hashInterval);
    }
    function start_hash_check() {
        hashInterval = setInterval(get_page_state, 500);
    }

    LoadBar = {
        bar : $("#lm"),
        msg : $("#lm span"),
        isOn : false,
        say : function (str) {
            LoadBar.msg.html(str);
        },
        on : function (str) {
            if (str) LoadBar.say(str);
            LoadBar.bar.addClass("on");
            LoadBar.isOn = true;
        },
        off : function () {
            LoadBar.bar.removeClass("on");
            LoadBar.isOn = false;
        }
    };

    // Worker pool for Web Worker management

    var stats_worker_url = z.media_url+"js/zamboni/stats/stats_worker.js";
    
    var StatsWorkerPool = new WorkerPool(4);

    var breakdown_metrics = {
        "apps"      : "applications",
        "locales"   : "locales",
        "sources"   : "sources",
        "os"        : "oses",
        "versions"  : "versions",
        "statuses"  : "statuses"
    };

    function generateSeriesMenu(data) {
        var job = {
            task: "getFieldList",
            data: data.blob
        };
        StatsWorkerPool.queueJob(stats_worker_url, job, function(msg) {
            if (msg.success && msg.result) {
                var m = msg.result;
                for (var i=0;i<m.length;i++) {
                    //console.log(AMO.StatsManager.getPrettyName(data.metric, m[i]));
                }
            }
        }, this);
    }

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
        return date(d);
    }

    function date(d) {
        return Date.parse(date_string(d, '-'));
    }
    
    function date_string(d, del) {
        return [d.getFullYear(), pad2(d.getMonth()+1), pad2(d.getDate())].join(del);
    }
    
    function datepicker_format(d) {
        return [pad2(d.getMonth()+1), pad2(d.getDate()), d.getFullYear()].join('/');
    }

    function ago(str, times) {
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
    
    Series = new AsyncCache(
        function miss(key, set) {
            if (typeof key.time === "string") {
                var seriesStart = ago(key.time);
                var seriesEnd = today();
            } else if (typeof key.time === "object") {
                var seriesStart = key.time.start;
                var seriesEnd = key.time.end;
            } else {
                return false;
            }
            var metric = key.metric,
                fields = key.fields,
                out    = {};
            AMO.StatsManager.getDataRange(metric, seriesStart, seriesEnd, function() {
                for (var j=0; j<fields.length; j++) {
                    if (metric in breakdown_metrics)
                        fields[j] = breakdown_metrics[metric] + "|" + fields[j];
                    out[fields[j]] = [];
                }
                chunkfor({
                    start: seriesStart,
                    end: seriesEnd,
                    step: millis("1 day"),
                    chunk_size: 10,
                    inner: function (i) {
                        if (ds[i]) {
                            var row = (metric == 'apps') ? AMO.StatsManager.collapseVersions(ds[i], 2) : ds[i];
                            for (var j=0; j<fields.length; j++) {
                                var val = AMO.StatsManager.getField(row, fields[j]);
                                var point = {
                                    x : i,
                                    y : val ? parseFloat(val) : null
                                };
                                out[fields[j]].push(point);
                            }
                        }
                    },
                    callback: function () {
                        var ret = [];
                        for (var j=0; j<fields.length; j++) {
                            ret.push({
                                type: 'line',
                                name: AMO.StatsManager.getPrettyName(metric, fields[j].split("|").slice(-1)[0]),
                                id: fields[j],
                                data: out[fields[j]]
                            });
                        }
                        set(ret);
                    },
                    ctx: this
                });
            });
        },
        function hash(key) {
            var time;
            if (typeof key.time === "string") {
                time = key.time.replace(/\s/g, '_');
            } else if (typeof time === "object") {
                time = key.time.start + "_" + key.time.end;
            }
            return [key.metric,key.fields.join("_"),time].join('_');
        }
    );

    Page = new AsyncCache(
    );

    AMO.StatsManager = {

        init: function () {
            if (capabilities.localStorage) {
                var local_store = localStorage;
                dbg("looking for local data");
                if (local_store.getItem("statscache") && AMO.StatsManager.verify_local()) {
                    var cacheObject = local_store.getItem("statscache-" + AMO.getAddonId());
                    dbg("found local data, loading...");
                    if (cacheObject) {
                        cacheObject = JSON.parse(cacheObject);
                        if (cacheObject) {
                            datastore = cacheObject;
                        }
                    }
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

            pending_fetches++;

            var seriesURLStart = Highcharts.dateFormat('%Y%m%d', seriesStart),
                seriesURLEnd = Highcharts.dateFormat('%Y%m%d', seriesEnd),
                seriesURL = AMO.getStatsBaseURL() + ([metric,"day",seriesURLStart,seriesURLEnd]).join("-") + ".json";

            dbg("GET", seriesURLStart, seriesURLEnd);

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
                        chunk_size: 50,
                        inner: function(i) {
                            var datekey = parseInt(Date.parse(data[i].date));
                            maxdate = Math.max(datekey, maxdate);
                            mindate = Math.min(datekey, mindate);
                            ds[datekey] = data[i];
                        },
                        callback: function () {
                            ds.maxdate = Math.max(parseInt(maxdate), parseInt(ds.maxdate));
                            ds.mindate = Math.min(parseInt(mindate), parseInt(ds.mindate));
                            pending_fetches--;
                            callback.call(this, true);
                            clearTimeout(writeInterval);
                            writeInterval = setTimeout(AMO.StatsManager.write_local, 1000);
                        },
                        ctx: this
                    });


                } else if (xhr.status == 202) { //Handle a successful fetch but with no reponse

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
                dbg(pending_fetches, "fetches left");
                if (pending_fetches < 1) {
                    LoadBar.off();
                }
                if (datastore[metric] && datastore[metric].maxdate < end) {
                    dbg("truncating fetchable range");
                    range_limits.maxdate = datastore[metric].maxdate;
                }
                if (needed < 0) {
                    callback.call(this);
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
                        callback.call(this, {nodata:true})
                    }

                });

            }

        },

        getNumPages: function(metric, size) {
            size = size || 14;

            var ds = datastore[metric];

            return Math.ceil((ds.maxdate - ds.mindate) / millis("1 day") / size);
        },
        
        collapseVersions: function(row, precision) {
            var out = {
                    count : row.count,
                    date : row.date,
                    end : row.end,
                    row_count : row.row_count,
                    applications : {}
                }, set, ver, key;
            var ra = out.applications;
            var apps = row.applications;
            for (var i in apps) {
                if (apps.hasOwnProperty(i)) {
                    var set = apps[i];
                    for (var j in set) {
                        if (precision) {
                            ver = j.split('.').slice(0,precision).join('.') + '.x';
                        } else {
                            ver = j;
                        }
                        key = i + '_' + ver;
                        if (!ra[key]) {
                            ra[key] = 0;
                        };
                        var v = parseFloat(set[j]);
                        ra[key] += v;
                    }
                }
            }
            return out;
        },

        getRankedList: function(field, start, end, callback) {
            var metric = field.metric;
            var cacheKey = name || (metric + field.name + "_toplist_" + start + "_" + end);

            var sums = {};
            
            var ver, version_precision = 2;

            var total = 0;

            if (seriesCache[cacheKey]) {
                callback.call(this, seriesCache[cacheKey]);
            } else {
                AMO.StatsManager.getDataRange(metric, start, end, function () {
                    var ds = datastore[metric],
                        set = [],
                        val, v, key, row,
                        time_size = (end-start) / millis('1 day');
                        
                    
                    for (var i=start; i<end; i+= millis("1 day")) {
                        if (ds[i]) {
                            row = (metric == 'apps') ? AMO.StatsManager.collapseVersions(ds[i], version_precision) : ds[i];
                            var datum = AMO.StatsManager.getField(row, field.name);
                            for (var j in datum) {
                                if (datum.hasOwnProperty(j)) {
                                    val = datum[j];
                                    if (!sums[j]) {
                                        sums[j] = 0;
                                    };
                                    var v = parseFloat(datum[j]);
                                    sums[j] += v;
                                    total += v;
                                }
                            }
                        }
                    }

                    sorted_sums = [];
                    total = Math.floor(total/time_size);
                    for (var i in sums) {
                        var v = Math.floor(sums[i]/time_size);
                        sorted_sums.push({
                            'field': i,
                            'sum': v,
                            'pct': Math.floor(v*100/total)
                        });
                    }

                    sorted_sums.sort(function (a,b) {
                        return b.sum-a.sum;
                    })

                    var ret = {'sums': sorted_sums, 'total': total};

                    seriesCache[cacheKey] = ret;

                    callback.call(this, ret);

                });
            }
        },

        getAvailableFields: function(metric, start, end, callback) {
            
        },

        processRange: function(field, start, end, callback) {
            var metric = field.metric;

            var sumKey = [metric, field.name, 'sum', start, end].join('_');
            var meanKey = [metric, field.name, 'mean', start, end].join('_');
            var maxKey = [metric, field.name, 'max', start, end].join('_');
            var minKey = [metric, field.name, 'min', start, end].join('_');

            AMO.StatsManager.getDataRange(metric, start, end, function () {
                var ds = datastore[metric];

                var chunk = [];
                for (var i=start; i<end; i+= millis("1 day")) {
                    if (ds[i] !== undefined) {
                        chunk.push(ds[i]);
                    }
                }
                
                var job = {
                    task: "computeAggregates",
                    data: {
                        fieldName: field.name,
                        data: chunk
                    }
                };
                StatsWorkerPool.queueJob(stats_worker_url, job, function(msg, worker) {
                    if ('success' in msg && msg.success) {
                        var result = msg.result;
                        if (result.nodata) {
                            var ret = {nodata: true};
                        } else {
                            seriesCache[sumKey]  = result.sum;
                            seriesCache[meanKey] = result.mean;
                            seriesCache[maxKey]  = result.max;
                            seriesCache[minKey]  = result.min;
                        }
                        callback.call(this);
                    }
                    return true;
                }, this);
            });
        },

        getSum: function(field, start, end, callback) {
            AMO.StatsManager.getStat(field, 'sum', start, end, callback);
        },

        getMean: function(field, start, end, callback) {
            AMO.StatsManager.getStat(field, 'mean', start, end, callback);
        },

        getMin: function(field, start, end, callback) {
            AMO.StatsManager.getStat(field, 'min', start, end, callback);
        },

        getMax: function(field, start, end, callback) {
            AMO.StatsManager.getStat(field, 'max', start, end, callback);
        },

        getStat: function(field, stat, start, end, callback) {
            var cacheKey = name || [field.metric, field.name, stat, start, end].join('_');

            if (seriesCache[cacheKey]) {
                callback.call(this, seriesCache[cacheKey]);
            } else {
                AMO.StatsManager.processRange(field, start, end, function() {
                    callback.call(this, seriesCache[cacheKey] || {nodata:true});
                });
            }
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

        },
        
        getPrettyName: function(metric, field) {
            var parts = field.split('_');
            var key = parts[0];
            parts = parts.slice(1);
            
            if (metric in csv_keys) {
                if (key in csv_keys[metric]) {
                    return csv_keys[metric][key] + ' ' + parts.join(' ');
                }
            }
            return field;
        }


    };
// })();