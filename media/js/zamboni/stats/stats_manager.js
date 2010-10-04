// (function () {

    // Versioning for offline storage
    var version = "11";

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
                fields = [],
                out    = {};
            AMO.StatsManager.getDataRange(metric, seriesStart, seriesEnd, function() {
                for (var j=0; j<key.fields.length; j++) {
                    k = key.fields[j];
                    if (metric in breakdown_metrics)
                        k = breakdown_metrics[metric] + "|" + k;
                    out[k] = [];
                    fields.push(k);
                }
                chunkfor({
                    start: seriesStart,
                    end: seriesEnd,
                    step: millis("1 day"),
                    chunk_size: 10,
                    inner: function (i) {
                        if (ds[i]) {
                            var row = (metric == 'apps') ? AMO.StatsManager.collapseVersions(ds[i], 1) : ds[i];
                            for (var j=0; j<fields.length; j++) {
                                var val = AMO.StatsManager.getField(row, fields[j]);
                                var point = {
                                    x : i,
                                    y : val ? parseFloat(val) : 0
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
                                id: fields[j].split("|").slice(-1)[0],
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
        function miss(key, set) {
            var size = key.size || 14,
                ds = datastore[key.metric],
                time = {};
            time.end = ds.maxdate - size * (key.num - 1) * millis("1 day");
            time.start = time.end - size * millis("1 day");

            AMO.StatsManager.getDataRange(key.metric, time.start, time.end, function() {

                var ret = [];
                
                for (var i=time.end; i>time.start; i-= millis("1 day")) {
                    if (ds[i] !== undefined) {
                        var row = (key.metric == 'apps') ? AMO.StatsManager.collapseVersions(ds[i], 1) : ds[i];
                        ret.push(row);
                    }
                }

                if (ret.length) {
                    ret.page = key.num;
                    set(ret);
                } else {
                    set({nodata:true});
                }

            });
        },
        function hash(key) {
            return [key.metric,"page",key.num,"by",key.size].join('_');
        }
    );

    RankedList = new AsyncCache(
        function miss(key, set) {
            var metric = key.metric,
                time = key.time;
            AMO.StatsManager.getDataRange(metric, time.start, time.end, function () {
                var range = AMO.StatsManager.getDataSlice(metric, time, key.field);
                var job = {
                    task: "computeRankings",
                    data: range
                };
                StatsWorkerPool.queueJob(stats_worker_url, job, function(msg, worker) {
                    if ('success' in msg && msg.success) {
                        var result = msg.result;
                        set(result);
                    }
                    return true;
                }, this);
            });
        },
        function hash(key) {
            return [key.metric, key.field, key.time.start, key.time.end].join("_");
        }
    );

    AMO.StatsManager = {

        init: function () {
            if (capabilities.localStorage) {
                dbg("looking for local data");
                if (AMO.StatsManager.verify_local()) {
                    var cacheObject = localStorage.getItem("statscache-" + AMO.getAddonId());
                    if (cacheObject) {
                        dbg("found local data, loading...");
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
                localStorage.setItem("statscache-" + AMO.getAddonId(), JSON.stringify(datastore));
                localStorage.setItem("stats_version", version);
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
                if (local_store.getItem("stats_version") == version) {
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
                    if (!quiet) LoadBar.on(gettext("Loading&hellip;"));
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
        
        getDataSlice: function(metric, time, base) {
            base = base || "";
            if (typeof time === "string") {
                var seriesStart = ago(time);
                var seriesEnd = today();
            } else if (typeof time === "object") {
                var seriesStart = time.start;
                var seriesEnd = time.end;
            } else {
                return false;
            }
            
            var ds = datastore[metric];
            
            var ret = [];

            for (var i=seriesStart; i<seriesEnd; i+= millis("1 day")) {
                if (ds[i] !== undefined) {
                    var row = (metric == 'apps') ? AMO.StatsManager.collapseVersions(ds[i], 2) : ds[i];
                    if (base) {
                        ret.push(AMO.StatsManager.getField(row, base));
                    } else {
                        ret.push(row);
                    }
                }
            }
            return ret;
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
                }, set, ver, key;
            var ra = {};
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
                        if (!(key in ra)) {
                            ra[key] = 0;
                        };
                        var v = parseFloat(set[j]);
                        ra[key] += v;
                    }
                }
            }
            out.applications = ra;
            return out;
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