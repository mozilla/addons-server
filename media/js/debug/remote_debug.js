(function () {
    var base_url = 'http://' + document.getElementById('remote_debug_server')
                                       .getAttribute('value') + '?';
    var oldConsole = window.console.log;
    window.console.log = function() {
        oldConsole.apply(window, arguments);
        for (var i=0; i<arguments.length; i++) {
            arguments[i] = JSON.stringify(arguments[i]);
        }
        (new Image()).src = base_url + JSON.stringify({
            msg: Array.prototype.join.call(arguments, ' , '),
            file: '', line: '', type: 'log'
        });
    };
    window.onerror = function(m,f,l) {
        (new Image()).src = base_url + JSON.stringify({
            msg: m, file: f, line: l, type: 'error'
        });
    };
    window.addEventListener('load', function() {
        console.log('woo online');
        $.ajaxPrefilter(function(opts) {
            console.log('starting ajax request', opts);
        });
    });
})();

