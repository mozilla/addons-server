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





