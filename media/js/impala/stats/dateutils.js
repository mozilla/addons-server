// date management helpers

z.date = (function() {
    var _millis = {
            "day" : 1000 * 60 * 60 * 24,
            "week" : 1000 * 60 * 60 * 24 * 7
        };

    // Returns the number of milliseconds for a given duration.
    // millis("1 day")
    // > 86400000
    // millis("2 days")
    // > 172800000
    function millis(str) {
        var tokens = str.split(/\s+/),
            n = parseInt(tokens[0], 10);
        if (!tokens[1]) throw "Invalid duration string";
        var unit = tokens[1].replace(/s$/,'').toLowerCase();
        if (!_millis[ unit ]) throw "Invalid time unit";
        return n * _millis[ unit ];
    }

    // pads a number with a preceding zero.
    // pad2(2)
    // > "02"
    // pad2(20)
    // > "20"
    function pad2(n) {
        var str = n.toString();
        return ('0' + str).substr(-2);
    }

    // Takes a date object and converts it to a time-less
    // representation of today's date.
    function date(d) {
        return Date.parse(date_string(d, '-'));
    }
    function date_string(d, del) {
        return [d.getFullYear(), pad2(d.getMonth()+1), pad2(d.getDate())].join(del);
    }
    function datepicker_format(d) {
        return [pad2(d.getMonth()+1), pad2(d.getDate()), d.getFullYear()].join('/');
    }

    // Truncates the current time off today's date.
    function today() {
        var d = new Date();
        return date(d);
    }

    // returns a millisecond timestamp for a specified duration in the past.
    function ago(str, times) {
        times = (times !== undefined) ? times : 1;
        return today() - millis(str) * times;
    }

    // takes a range object and normalizes it to have a `start` and `end` property.
    function normalizeRange(range) {
        var ret = {};
        if (typeof range == "string") {
            ret.start = ago(range);
            ret.end = today();
        } else if (typeof range == "object") {
            ret.start = range.start;
            ret.end = range.end;
        } else {
            throw "Invalid range values found.";
        }
        return ret;
    }

    return {
        'ago': ago, 'date': date, 'date_string': date_string,
        'datepicker_format': datepicker_format, 'millis': millis, 'pad2': pad2,
        'today': today, 'normalizeRange': normalizeRange
    };
})();
