(function () {
    var base_url = 'http://' + document.getElementById('remote_debug_server')
                                       .getAttribute('value') + '?';
    var oldConsole = window.console.log;
    window.console.log = function() {
        (new Image()).src = base_url + JSON.stringify({
            msg: Array.prototype.join.call(arguments, ' , '),
            file: '', line: '', type: 'log'
        });
        oldConsole.apply(window, arguments);
    };
    window.onerror = function(m,f,l) {
        (new Image()).src = base_url + JSON.stringify({
            msg: m, file: f, line: l, type: 'error'
        });
    };
})();

