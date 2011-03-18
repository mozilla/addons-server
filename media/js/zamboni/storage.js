var Storage = (function() {
    var cookieStorage = {
        expires: 30,    // Number of days
        getItem: function(key) {
            return $.cookie(key);
        },
        setItem: function(key, value) {
            return $.cookie(key, value, {path: "/", expires: this.expires});
        },
        removeItem: function(key) {
            return $.cookie(key, null);
        }
    };
    var engine = cookieStorage;
    try {
        if ("localStorage" in window && window["localStorage"] !== null) {
            engine = window.localStorage;
        }
    } catch (e) {
    }
    return {
        get: function(key) {
            return engine.getItem(key);
        },
        set: function(key, value) {
            return engine.setItem(key, value);
        },
        remove: function(key) {
            return engine.removeItem(key);
        }
    };
})();
