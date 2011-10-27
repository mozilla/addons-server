z.getVars = function(qs) {
    if (typeof qs === 'undefined') {
        qs = location.search;
    }
    var vars = {};
    if (qs.length > 1) {
        var items = qs.substr(1).split('&'),
            item;
        for (var i = 0; i < items.length; i++) {
            item = items[i].split('=');
            if (item[0] !== '' && typeof item[1] !== 'undefined') {
                vars[escape_(unescape(item[0]))] = escape_(unescape(item[1]));
            }
        }
    }
    return vars;
};


JSON.parseNonNull = function(text) {
    return JSON.parse(text, function(key, value) {
        if (typeof value === 'object' && value === null) {
            return '';
        }
        return value;
    });
};
