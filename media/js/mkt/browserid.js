_.extend(z, (function() {
    var loginUrl = $('body').data('login-url'),
        exports = {},
        $def,
        to;

    exports.login = function(go_to) {
        $def = $.Deferred();
        to = go_to;

        return $def;
    };

    return exports;
})());
