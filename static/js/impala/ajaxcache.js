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
        ajaxFailure: $.noop       // Callback upon failure of Ajax request.
    }, o);

    if (!z.capabilities.JSON || parseFloat(jQuery.fn.jquery) < 1.5) {
        // jqXHR objects allow Deferred methods as of jQuery 1.5. Some of our
        // old pages are stuck on jQuery 1.4, so hopefully this'll disappear
        // sooner than later.
        return $.ajax({
            url: o.url,
            type: o.method,
            data: o.data,
            success: function(data) {
                o.newItems(data, data);
                o.ajaxSuccess(data, items);
            },
            errors: function(data) {
                o.ajaxFailure(data);
            }
        });
    }

    var cache = z.AjaxCache(o.url + ':' + o.type),
        args = JSON.stringify(o.data),
        previous_args = JSON.stringify(cache.previous.args),
        items,
        request;

    if (args != previous_args) {
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
                o.newItems(data, items);
                o.ajaxSuccess(data, items);

                // Store items returned from this request.
                cache.items[args] = data;

                // Store current list of items and form data (arguments).
                cache.previous.data = data;
                cache.previous.args = args;
            });

            // Optional failure callback.
            if (o.failure) {
                request.fail(function(data) {
                    o.ajaxFailure(data);
                });
            }
        }
    }
    return request;
};

})(jQuery);
