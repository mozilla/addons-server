(function () {
    var base_url = 'http://' + document.getElementById('remote_debug_server')
                                       .getAttribute('value') + '?';
    var oldConsole = window.console.log;
    function transmit() {
        for (var i=0; i<arguments.length; i++) {
            arguments[i] = (typeof arguments[i] === 'string') ?
                           arguments[i] : JSON.stringify(arguments[i]);
        }
        (new Image()).src = base_url + JSON.stringify({
            msg: Array.prototype.join.call(arguments, ' , '),
            file: '', line: '', type: 'log'
        });
    }
    window.console.log = function() {
        oldConsole.apply(window, arguments);
        transmit(arguments);
    };
    window.onerror = function(m,f,l) {
        (new Image()).src = base_url + JSON.stringify({
            msg: m, file: f, line: l, type: 'error'
        });
    };
    window.addEventListener('load', function() {
        transmit('woo online');
        $.ajaxPrefilter(function(opts) {
            transmit('starting ajax request', opts);
        });
    });
})();

