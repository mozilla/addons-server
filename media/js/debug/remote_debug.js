(function () {
    var base_url = 'http://' + document.getElementById('remote_debug_server')
                                       .getAttribute('value') + '?';
    window.onerror = function(m,f,l) {
        (new Image()).src = base_url + JSON.stringify({
            msg: m, file: f, line: l
        });
    };
})();

