// (function () {
    
    // Versioning for offline storage
    var version = "1";

    // where all the time-series data for the page is kept
    var datastore = {};

    // where all the the computed ranges are kept
    var seriesCache = {};
    var range_limits = {
        mindate: 0,
        maxdate: today()
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

    function ago (str) {
        return today() - millis(str);
    }
    
    function chunkfor(start, end, step, chunk_size, inner, callback, ctx) {
        var position = start;
        
        function nextchunk() {
            if (position < end) {
                
                for (var iterator = position;
                     iterator < position+(chunk_size*step) && iterator < end;
                     iterator += step) {
                         
                    inner.call(ctx, iterator);
                }
                
                position += chunk_size * step;
                
                setTimeout( function () {
                    nextchunk.call(this);
                }, 0);
                
            } else {
                callback.call(ctx);
            }
        }
        nextchunk();
    }
    
    document.onbeforeunload = function () {
        AMO.StatsManager.write_local();
    }
        
    AMO.StatsManager = {
        
        init: function () {
            if (window.globalStorage) {
                var host = location.hostname;
                var local_store = globalStorage[host];
                dbg("looking for local data");
                if (local_store.getItem("statscache") && AMO.StatsManager.verify_local()) {
                    var cacheObject = local_store.getItem("statscache");
                    dbg("found local data, loading...");
                    datastore = JSON.parse(cacheObject);
                    dbg(datastore);
                }
            } else {
                dbg("no local storage");
            }
        },
        
        write_local: function () {
            dbg("saving local data");
            if (window.globalStorage) {
                dbg("user has local storage");
                var host = location.hostname;
                var local_store = globalStorage[host];
                local_store.setItem("statscache", JSON.stringify(datastore));
                dbg("saved local data");
            } else {
                dbg("no local storage");
            }
        },

        clear_local: function () {
            if (globalStorage) {
                var host = location.hostname;
                var local_store = globalStorage[host];
                local_store.removeItem("statscache");
                dbg("cleared local data");
            }
        },
        
        verify_local: function () {
            if (window.globalStorage) {
                var host = location.hostname;
                var local_store = globalStorage[host];
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

            var seriesURLStart = Highcharts.dateFormat('%Y%m%d', seriesStart);
            var seriesURLEnd = Highcharts.dateFormat('%Y%m%d', seriesEnd);
            var seriesURL = AMO.getStatsBaseURL() + ([metric,"day",seriesURLStart,seriesURLEnd]).join("-") + ".json";
            
            $.get(seriesURL, function(data, status, xhr) {
                
                var maxdate = 0,
                    mindate = today();
                
                if (xhr.status == 200) {
                                
                    if (!datastore[metric]) {
                        datastore[metric] = {};
                        datastore[metric].mindate = today();
                        datastore[metric].maxdate = 0;
                    }

                    var ds = datastore[metric];

                    chunkfor(0, data.length, 1, 10,
                        function (i) {
                            var datekey = Date.parse(data[i].date);

                            maxdate = Math.max(datekey, ds.maxdate);
                            mindate = Math.min(datekey, ds.mindate);

                            ds[datekey] = data[i];
                        },
                        function () {
                            ds.maxdate = Math.max(maxdate, ds.maxdate);
                            ds.mindate = Math.min(mindate, ds.mindate);
                            callback.call(this, true);
                            clearTimeout(writeInterval);
                            writeInterval = setTimeout(AMO.StatsManager.write_local, 2000);
                        }, this
                    );


                } else if (xhr.status == 202) {
                    
                    var retry_delay = 30000;
                    
                    if (xhr.getResponseHeader("Retry-After")) {
                        retry_delay = parseInt(xhr.getResponseHeader("Retry-After")) * 1000;
                    }
                    
                    setTimeout(function () {
                        AMO.StatsManager._fetchData(metric, start, end, callback);
                    }, retry_delay);
                    
                }
            });
            

        },
        
        /*
         * getDataRange: ensures we have all the data from the server we need,
         * and queues up requests to the server if the requested data is outside
         * the range currently stored locally. Once all server requests return,
         * we move on.
         */
        
        getDataRange: function (metric, start, end, callback, quiet) {
            var needed = 0;
            
            end = Math.min(end, range_limits.maxdate);

            function finished() {
                needed--;
                if (datastore[metric].maxdate < end) {
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
            
            if (datastore[metric]) {
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

                    chunkfor(seriesStart, seriesEnd, millis("1 day"), 10,
                        function (i) {
                            for (var j=0; j<fields.length; j++) {
                                var point = {
                                    x : i,
                                    y : data[i] ? parseFloat(AMO.StatsManager.getField(data[i], fields[j])) : null
                                };
                                out[fields[j]].push(point);
                            }
                        },
                        function () {
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
                        }
                    );
                    
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
            }
            
            return val;

        }
        

    };
// })();