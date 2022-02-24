// date management helpers

(function () {
  // utility
  function pad2(n) {
    var str = n.toString();
    return ('0' + str).substr(-2);
  }
  var intervalRegex = /(-?\d+)\s*(\w)/,
    // ISO date format is used for internal representations.
    dateRegex = /(\d{4})[^\d]?(\d{2})[^\d]?(\d{2})/;

  _.extend(Date.prototype, {
    forward: function (by, unit) {
      if (typeof by == 'string') {
        var match = intervalRegex.exec(by);
        by = +match[1];
        unit = match[2];
      }
      unit = unit || 'd';
      switch (unit[0]) {
        case 'h':
          this.setHours(this.getHours() + by);
          break;
        case 'd':
          this.setDate(this.getDate() + by);
          break;
        case 'w':
          this.setDate(this.getDate() + by * 7);
          break;
        case 'm':
          this.setMonth(this.getMonth() + by);
          break;
        case 'y':
          this.setFullYear(this.getFullYear() + by);
          break;
      }
      return this;
    },
    backward: function (by, unit) {
      if (typeof by == 'string') {
        var match = intervalRegex.exec(by);
        by = +match[1];
        unit = match[2];
      }
      return this.forward(-by, unit);
    },
    pretty: function (del) {
      del = del || '';
      return [
        this.getFullYear(),
        pad2(this.getMonth() + 1),
        pad2(this.getDate()),
      ].join(del);
    },
    iso: function () {
      return this.pretty('-');
    },
    isAfter: function (d) {
      return this.getTime() > d.getTime();
    },
    isBefore: function (d) {
      return this.getTime() < d.getTime();
    },
    latter: function (d) {
      return this.isAfter(d) ? this : d;
    },
    former: function (d) {
      return this.isBefore(d) ? this : d;
    },
    clone: function () {
      return new Date(this.getTime());
    },
  });
  _.extend(Date, {
    ago: function (s) {
      return new Date().backward(s);
    },
    iso: function (s) {
      if (s instanceof Date) return s;
      var d = dateRegex.exec(s);
      if (d) {
        return new Date(d[1], d[2] - 1, d[3]);
      }
    },
  });
  _.extend(String, {
    max: function (a, b) {
      return a > b ? a : b;
    },
    min: function (a, b) {
      return a < b ? a : b;
    },
  });
})();

function forEachISODate(range, step, data, iterator, context) {
  var d = range.start.clone();
  for (d; d.isBefore(range.end); d.forward(step)) {
    var ds = d.iso();
    iterator.call(context, data[ds], d, ds);
  }
}

function normalizeRange(range) {
  var ret = {};
  if (typeof range == 'string') {
    ret.start = Date.ago(range);
    ret.end = new Date();
  } else if (typeof range == 'object') {
    ret.start = new Date(range.start);
    ret.end = new Date(range.end);
  } else {
    throw 'Invalid range values found.';
  }
  return ret;
}
