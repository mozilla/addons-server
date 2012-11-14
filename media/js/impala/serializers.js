z.getVars = function(qs, excl_undefined) {
    if (typeof qs === 'undefined') {
        qs = location.search;
    }
    if (qs[0] == '?') {
        qs = qs.substr(1);  // Filter off the leading ? if it's there.
    }

    var pairs = _.chain(qs.split('&'))  // ['a=b', 'c=d']
                 .map(function(c) {return _.map(c.split('='), escape_);}); //  [['a', 'b'], ['c', 'd']]
    if (excl_undefined) {
        // [['a', 'b'], ['c', undefined]] -> [['a', 'b']]
        pairs = pairs.filter(function(p) {return !_.isUndefined(p[1]);})
    }
    return pairs.object().value();  // {'a': 'b', 'c': 'd'}
};


JSON.parseNonNull = function(text) {
    return JSON.parse(text, function(key, value) {
        if (typeof value === 'object' && value === null) {
            return '';
        }
        return value;
    });
};
