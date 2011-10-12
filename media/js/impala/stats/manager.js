function dbg() {
    if(window.console && (typeof window.console.log == 'function')) {
        window.console.log(Array.prototype.slice.apply(arguments));
    }
}

z.hasPushState = (typeof history.replaceState === "function");

z.StatsManager = (function() {
    // "use strict";

    // The version of the stats localStorage we are using.
    // If you increment this number, you cache-bust everyone!
    var STATS_VERSION = 22;

    var storage         = z.Storage("stats"),
        storageCache    = z.Storage("statscache"),
        dataStore       = {},
        currentView     = {},
        addonId         = parseInt($(".primary").attr("data-addon_id"), 10),
        baseURL         = $(".primary").attr("data-base_url"),
        pendingFetches  = 0,
        writeInterval   = false;

    // It's a bummer, but we need to know which metrics have breakdown fields.
    // check by saying `if (metric in breakdownMetrics)`
    var breakdownMetrics = {
        "apps": true,
        "locales": true,
        "os": true,
        "sources": true,
        "versions": true,
        "statuses": true,
        "overview": true
    };

    // is a metric an average or a sum?
    var metricTypes = {
        "usage"     : "mean",
        "apps"      : "mean",
        "locales"   : "mean",
        "os"        : "mean",
        "versions"  : "mean",
        "statuses"  : "mean",
        "downloads" : "sum",
        "sources"   : "sum"
    };

    // Initialize from localStorage when dom is ready.
    function init() {
        dbg("looking for local data");
        if (verifyLocalStorage()) {
            var cacheObject = storageCache.get(addonId);
            if (cacheObject) {
                dbg("found local data, loading...");
                cacheObject = JSON.parse(cacheObject);
                if (cacheObject) {
                    dataStore = cacheObject;
                }
            }
        }
    }
    $(init);

    // These functions deal with our localStorage cache.

    function writeLocalStorage() {
        dbg("saving local data");
        storageCache.set(addonId, JSON.stringify(dataStore));
        storage.set("version", STATS_VERSION);
        dbg("saved local data");
    }

    function clearLocalStorage() {
        storageCache.remove(addonId);
        dbg("cleared local data");
    }

    function verifyLocalStorage() {
        if (storage.get("version") == STATS_VERSION) {
            return true;
        } else {
            dbg("wrong offline data verion");
            clearLocalStorage();
            return false;
        }
    }

    document.onbeforeunload = writeLocalStorage;


    // Runs when 'changeview' event is detected.
    function processView(e, newView) {
        // Update our internal view state.
        currentView = $.extend(currentView, newView);

        // Fetch the data from the server or storage, and notify other components.
        $.when( getDataRange(currentView) )
         .then( function(data) {
            $(window).trigger("dataready", {
                'view'  : currentView,
                'fields': getAvailableFields(currentView),
                'data'  : data
            });
        });
    }
    $(window).bind('changeview', processView);


    // Returns a list of field names for a given data set.
    function getAvailableFields(view) {
        var metric = view.metric,
            range = z.date.normalizeRange(view.range),
            start = range.start,
            end = range.end,
            ds,
            row,
            numRows = 0,
            step = z.date.millis("1 day"),
            fields = {};

        // Non-breakdwon metrics only have one field.
        if (!(metric in breakdownMetrics)) return false;

        ds = dataStore[metric];
        if (!ds) throw "Expected metric with valid data!";

        // Locate all unique fields.
        for (var i=start; i<end; i+= step) {
            if (ds[i]) {
                row = (metric == 'apps') ? collapseVersions(ds[i], 1) : ds[i];
                _.each(row.data, function(v, k) {
                    fields[k] = fields[k] ? fields[k] + v : v;
                });
                _.extend(fields, row.data);
            }
        }

        // sort the fields, make them proper field identifiers, and return.
        return _.map(
            _.sortBy(
                _.keys(fields),
                function (f) {
                    return -fields[f];
                }
            ),
            function(f) {
                return "data|" + f;
            }
        );
    }


    // getDataRange: ensures we have all the data from the server we need,
    // and queues up requests to the server if the requested data is outside
    // the range currently stored locally. Once all server requests return,
    // we move on.
    function getDataRange(view, callback) {
        dbg("enter getDataRange", view.metric);
        var range = z.date.normalizeRange(view.range),
            metric = view.metric,
            ds,
            needed = 0,
            $def = $.Deferred();

        function finished() {
            needed--;
            dbg(pendingFetches, " fetches pending");
            if (needed < 1) {
                var ret = {}, row,
                    step = z.date.millis("1 day");
                ds = dataStore[metric];
                for (var i=range.start; i<range.end; i+= step) {
                    if (ds[i]) {
                        ret[i] = (metric == 'apps') ? collapseVersions(ds[i], 1) : ds[i];
                    }
                }
                ret = groupData(ret, view);
                ret.metric = metric;
                $def.resolve(ret);
            }
        }

        if (dataStore[metric]) {
            ds = dataStore[metric];
            dbg("range", range.start, range.end);
            if (ds.maxdate < range.end) {
                needed++;
                fetchData(metric, ds.maxdate, range.end, finished);
            }
            if (ds.mindate > range.start) {
                needed++;
                fetchData(metric, range.start, ds.mindate, finished);
            }
            if (ds.mindate <= range.start && ds.maxdate >= range.end) {
                dbg("all data found locally");
                finished();
            }
        } else {
            dbg("metric not found");
            needed++;
            fetchData(metric, range.start, range.end, finished);
        }
        return $def;
    }


    // Aggregate data based on view's `group` setting.
    function groupData(data, view) {
        var metric = view.metric,
            range = z.date.normalizeRange(view.range),
            group = view.group || 'day',
            groupedData = {};
        // if grouping is by day, do nothing.
        if (group == 'day') return data;
        var groupKey = false,
            groupVal = false,
            groupCount = 0,
            d, row;
        // big loop!
        for (var i=range.start; i<range.end; i+= z.date.millis('1 day')) {
            d = new Date(i);
            row = data[i];
            // Here's where grouping points are caluculated.
            if ((group == 'week' && d.getDay() === 0) || (group == 'month' && d.getDate() == 1)) {
                // we drop the some days of data from the result set
                // if they are not a complete grouping.
                if (groupKey && groupVal) {
                    // average `count` for mean metrics
                    if (metricTypes[metric] == 'mean') {
                        groupVal.count /= groupCount;
                    }
                    // overview gets special treatment. Only average ADUs.
                    if (metric == "overview") {
                        groupVal.data.updates /= groupCount;
                    } else if (metric in breakdownMetrics) {
                        // average for mean metrics.
                        _.each(groupVal.data, function(val, field) {
                            if (metricTypes[metric] == 'mean') {
                                groupVal.data[field] /= groupCount;
                            }
                        });
                    }
                    groupedData[groupKey] = groupVal;
                }
                // set the new group date to the current iteration.
                groupKey = i;
                // reset our aggregates.
                groupCount = 0;
                groupVal = {
                    date: z.date.date_string(new Date(groupKey), '-'),
                    count: 0,
                    data: {}
                };
            }
            // add the current row to our aggregates.
            if (row && groupVal) {
                groupVal.count += row.count;
                if (metric in breakdownMetrics) {
                    _.each(row.data, function(val, field) {
                        if (!groupVal.data[field]) {
                            groupVal.data[field] = 0;
                        }
                        groupVal.data[field] += val;
                    });
                }
            }
            groupCount++;
        }
        return groupedData;
    }


    // The beef. Negotiates with the server for data.
    function fetchData(metric, start, end, callback) {
        var seriesStart = start,
            seriesEnd = end;

        pendingFetches++;

        var seriesURLStart = Highcharts.dateFormat('%Y%m%d', seriesStart),
            seriesURLEnd = Highcharts.dateFormat('%Y%m%d', seriesEnd),
            seriesURL = baseURL + ([metric,'day',seriesURLStart,seriesURLEnd]).join('-') + '.json';

        dbg("GET", seriesURLStart, seriesURLEnd);

        $.ajax({ url:       seriesURL,
                 dataType:  'text',
                 success:   fetchHandler});

        function fetchHandler(raw_data, status, xhr) {
            var maxdate = 0,
                mindate = z.date.today();

            if (xhr.status == 200) {

                if (!dataStore[metric]) {
                    dataStore[metric] = {};
                    dataStore[metric].mindate = z.date.today();
                    dataStore[metric].maxdate = 0;
                }

                var ds = dataStore[metric],
                    data = JSON.parse(raw_data);

                var i, datekey;
                for (i=0; i<data.length; i++) {
                    datekey = parseInt(Date.parse(data[i].date), 10);
                    maxdate = Math.max(datekey, maxdate);
                    mindate = Math.min(datekey, mindate);
                    ds[datekey] = data[i];
                }
                ds.maxdate = Math.max(parseInt(maxdate, 10), parseInt(ds.maxdate, 10));
                ds.mindate = Math.min(parseInt(mindate, 10), parseInt(ds.mindate, 10));
                pendingFetches--;
                callback.call(this, true);
                clearTimeout(writeInterval);
                writeInterval = setTimeout(writeLocalStorage, 1000);

            } else if (xhr.status == 202) { //Handle a successful fetch but with no reponse

                var retry_delay = 30000;

                if (xhr.getResponseHeader("Retry-After")) {
                    retry_delay = parseInt(xhr.getResponseHeader("Retry-After"), 10) * 1000;
                }

                setTimeout(function () {
                    fetchData(metric, start, end, callback);
                }, retry_delay);

            }
        }
    }


    // Rounds application version strings to a given precision.
    // Passing `0` will truncate versions entirely.
    function collapseVersions(row, precision) {
        var out = {
                count   : row.count,
                date    : row.date,
                end     : row.end
            },
            set,
            ver,
            key,
            apps    = row.data,
            ret     = {};

        for (var i in apps) {
            if (apps.hasOwnProperty(i)) {
                set = apps[i];
                for (ver in set) {
                    key = i + '_' + ver.split('.').slice(0,precision).join('.');
                    if (!(key in ret)) {
                        ret[key] = 0;
                    }
                    var v = parseFloat(set[ver]);
                    ret[key] += v;
                }
            }
        }
        out.data = ret;
        return out;
    }


    // Takes a data row and a field identifier and returns the value.
    function getField(row, field) {
        var parts   = field.split('|'),
            val     = row;

        // give up if the row is falsy.
        if (!val) return null;
        // drill into the row object for a nested key.
        // `data|api` means row['data']['api']
        for (var i = 0; i < parts.length; i++) {
            val = val[parts[i]];
            if (!val) {
                return null;
            }
        }

        return val;
    }


    function getPrettyName(metric, field) {
        var parts = field.split('_'),
            key = parts[0];
        parts = parts.slice(1);

        if (metric in csv_keys) {
            if (key in csv_keys[metric]) {
                return csv_keys[metric][key] + ' ' + parts.join(' ');
            }
        }
        return field;
    }


    // Expose some functionality to the z.StatsManager api.
    return {
        'fetchData'     : fetchData,
        'dataStore'     : dataStore,
        'getPrettyName' : getPrettyName,
        'getField'      : getField
    };
})();