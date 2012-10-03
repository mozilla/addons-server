now.ready(function () {
    var oldConsole = window.console.log;
    window.console.log = function() {
        now.log.apply(now, arguments);
    };
    window.onerror = function(m,f,l) {
        now.logError(m, f, l);
    };
    now.doEval = function(code) {
        var out;
        try {
            out = window.eval(code);
        }
        catch (e) {
            now.logError(e.message, 0, 0);
            return;
        }
        now.evalResp(out);
    };
    now.registerRemoteServer(window.navigator.platform, window.screen.width, window.screen.height);
    $.ajaxPrefilter(function(opts) {
        now.msg('starting ajax request', opts);
    });
});

