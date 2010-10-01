// Hello there! I'm the stats computation worker for the AMO stats pages.
// Don't minify me! I need to be requestable on my own.

function error(msg) {
    postMessage({
        "success"   : false,
        "msg"       : msg
    });
    close();
}

function getField(record, field) {

    var parts = field.split('|'),
        val   = record;

    for (var i=0; i<parts.length; i++) {
        val = val[parts[i]];
        if (!val) {
            return null;
        }
    }

    return val;
}

self.tasks = {
    "computeRankings": function(data) {
        var v, datum, sorted_sums,
            total = 0;
            sums = {};
        
        for (var i=0; i<data.length; i++) {
            datum = data[i];
            for (var j in datum) {
                if (datum.hasOwnProperty(j)) {
                    if (!sums[j]) {
                        sums[j] = 0;
                    };
                    v = parseFloat(datum[j]);
                    sums[j] += v;
                    total += v;
                }
            }
        }

        sorted_sums = [];
        total = Math.floor(total/data.length);
        for (var i in sums) {
            v = Math.floor(sums[i]/data.length);
            sorted_sums.push({
                'field': i,
                'sum': v,
                'pct': Math.floor(v*100/total)
            });
        }

        sorted_sums.sort(function (a,b) {
            return b.sum-a.sum;
        })

        postMessage({
            success: true,
            result: {
                'sums': sorted_sums,
                'total': total
            }
        });
    },
    "getFieldList": function(data) {
        var fields = {},
            result = [];
        function fieldEnum(o, par) {
            par = par || '';
            for (var key in o) {
                if (o.hasOwnProperty(key)) {
                    if (typeof o[key] == "object") {
                        fieldEnum(o[key], par + key + "|");
                    } else {
                        fields[par + key] = true;
                    }
                }
            }
        }
        for (var i=0; i<data.length; i++) {
            fieldEnum(data[i]);
        }
        for (var key in fields) {
            if (fields.hasOwnProperty(key)) {
                result.push(key);
            }
        }
        postMessage({
            success: true,
            result: result
        });
    },
    "computeAggregates": function(info) {
        var sum = 0,
            max = {nodata: true},
            min = {nodata: true},
            nodata = true,
            data = info.data,
            fieldName = info.fieldName;
            
        if (!data.length) {
            error("no data passed!");
        }

        for (var i=0; i<data.length; i++) {
            var datum = getField(data[i], fieldName);
            if (datum !== undefined) {
                var val = parseFloat(datum);
                if (nodata) {
                    min = val;
                    max = val;
                }
                nodata = false;
                max = Math.max(max, val);
                min = Math.min(min, val);
                sum += val;
            }
        }

        if (nodata) {
            postMessage({nodata: true});
            close();
        } else {
            postMessage({
                success: true,
                result: {
                    "sum":  sum,
                    "min":  min,
                    "max":  max,
                    "mean": sum / data.length
                }
            });
        }
    } 
};

addEventListener('message', function(e) {
    var msg      = e.data,
        taskName = msg.task;

    if (taskName in self.tasks) {
        self.tasks[taskName](msg.data);
        self.close();
    } else {
        error("no known task named " + taskName);
    }
}, false);





