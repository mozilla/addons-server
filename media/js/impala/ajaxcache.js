function objEqual(a, b) {
    return JSON.stringify(a) == JSON.stringify(b);
}


z._AjaxCache = {};
z.AjaxCache = (function() {
    return function(namespace) {
        if (z._AjaxCache[namespace] === undefined) {
            z._AjaxCache[namespace] = {
                'previous': {'args': '', 'data': ''},
                'items': {}
            };
        }
        return z._AjaxCache[namespace];
    };
})();


(function($) {

$.ajaxCache = function(o) {
    o = $.extend({
        url: '',
        type: 'get',
        data: {},                 // Key/value pairs of form data.
        newItems: $.noop,         // Callback upon success of items fetched.
        cacheSuccess: $.noop,     // Callback upon success of items fetched
                                  // in cache.
        ajaxSuccess: $.noop,      // Callback upon success of Ajax request.
        ajaxFailure: $.noop,      // Callback upon failure of Ajax request.
    }, o);

    var cache = z.AjaxCache(o.url + ':' + o.type),
        args = JSON.stringify(o.data),
        $self = this,
        items,
        request;

    if (args != JSON.stringify(cache.previous.args)) {
        if (!!cache.items[args]) {
            items = cache.items[args];
            if (o.newItems) {
                o.newItems(null, items);
            }
            if (o.cacheSuccess) {
                o.cacheSuccess(null, items);
            }
        } else {
            // Make a request to fetch new items.
            request = $.ajax({url: o.url, type: o.method, data: o.data});

            request.done(function(data) {
                var items;
                if (!objEqual(data, cache.previous.data)) {
                    items = data;
                }
                if (o.newItems) {
                    o.newItems(data, items);
                }
                if (o.ajaxSuccess) {
                    o.ajaxSuccess(data, items);
                }
            });

            // Optional failure callback.
            if (o.failure) {
                request.fail(function(data) {
                    o.ajaxFailure(data);
                });
            }

            request.always(function(data) {
                // Store items returned from this request.
                cache.items[args] = data;

                // Store current list of items and form data (arguments).
                cache.previous.data = data;
                cache.previous.args = args;
            });

        }
    }
    return request;
};

})(jQuery);
