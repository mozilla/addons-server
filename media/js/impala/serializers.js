z.getVars = function(qs, excl_undefined) {
    if (typeof qs === 'undefined') {
        qs = location.search;
    }
    if (qs && qs[0] == '?') {
        qs = qs.substr(1);  // Filter off the leading ? if it's there.
    }
    if (!qs) return {};

    return _.chain(qs.split('&'))  // ['a=b', 'c=d']
            .map(function(c) {return _.map(c.split('='), escape_);}) //  [['a', 'b'], ['c', 'd']]
            .filter(function(p) {  // [['a', 'b'], ['c', undefined]] -> [['a', 'b']]
                return !!p[0] && (!excl_undefined || !_.isUndefined(p[1]));
            }).object()  // {'a': 'b', 'c': 'd'}
            .value();
};


JSON.parseNonNull = function(text) {
    return JSON.parse(text, function(key, value) {
        if (typeof value === 'object' && value === null) {
            return '';
        }
        return value;
    });
};
