(function() {
    document.body.innerHTML += '<style>#tinytools{-moz-box-sizing:border-box;background:#eee;position:fixed;bottom:0;left:0;width:100%;padding:4px}#tinytools *{margin:0;padding:0}#tinytools pre{overflow:auto;max-height:200px}#tinytools input{font-family:monospace;font-size:13px;-moz-box-sizing:border-box;width:100%;margin-top:4px}#tinytools .out{padding-left:2ch;color:blue}#tinytools .error{color:red}</style><div id="tinytools"><pre id="log"></pre><input type="text"></div>';

    var tt = document.querySelector('#tinytools');
    var repl = tt.querySelector('input');
    var logEl = tt.querySelector('#log');
    var old = {
        log: window.console.log,
        error: window.console.error,
        clear: window.console.clear
    };
    if (sessionStorage.getItem('tt-visible') === 'true') {
        tt.style.display = 'block';
    }
    window.console.log = function() {
        append(arguments, 'log');
        try {
            old.log.apply(window.console, arguments);
        } catch(e) {}
    };
    window.console.error = function() {
        append(arguments, 'error');
        try {
            old.error.apply(window.console, arguments);
        } catch(e) {}
    };
    window.console.clear = function() {
        logEl.innerHTML = '';
    };
    window.console.list = function(o) {
        var s = [], v;
        for (var p in o) {
            v = o[p];
            if (v === null || v === undefined) {
                v = typeof v;
            }
            v = v.toString().split('\n')[0];
            s.push(p + ': ' + v);
        }
        append([s.sort().join('\n')], 'out');
    };
    document.addEventListener('keydown', function(e) {
        if (e.which == 82 && e.metaKey) window.location.reload();
        if (e.which == 75 && e.metaKey && e.altKey) {
            if (tt.style.display != 'block') {
                tt.style.display = 'block';
                sessionStorage.setItem('tt-visible', true);
            } else {
                tt.style.display = 'none';
                sessionStorage.setItem('tt-visible', false);
            }
        }
    });
    window.onerror = function(m, f, l) {
        console.error(m, 'in file', f, 'on line', l);
    };

    function append(args, type) {
        var vals = Array.prototype.slice.apply(args);
        var out = vals.map(function(v) {
            return v && v.toString();
        }).join(' ');
        if (!out.length) return;
        logEl.innerHTML += '<div class="'+type+'">' + out + '</div>';
        logEl.scrollTop = logEl.scrollHeight;
    }

    var lastCommand = '';
    repl.addEventListener('keydown', function(e) {
        if (e.which == 38) {
            repl.value = lastCommand;
        }
        if (e.which == 13) {
            var code = repl.value;
            console.log('>', code);
            lastCommand = code;
            var out;
            try {
                out = window.eval(code);
            }
            catch (e) {
                console.error(e);
            }
            finally {
                append([out], 'out');
                repl.value = '';
            }
        }
    });
})();