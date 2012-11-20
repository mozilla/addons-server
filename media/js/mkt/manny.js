if ('applicationCache' in window) {
    function Log(el) {
        function ts() {
            var d = (new Date());
            function p(v, n) {
                return ('00' + d['get'+v]()).substr(-n);
            }
            return [p('Hours',2), p('Minutes',2),
                    p('Seconds',2), p('Milliseconds',3)].join(':');
        }
        this.log = function(msg) {
            var line = [ts(), msg].join('\t');
            this.push(line);
            if (el) {
                el.innerHTML += line + '\n';
            }
        };
        this.pretty = function() {
            return this.join('\n');
        }
        return this;
    }
    Log.prototype = Array.prototype;

    var manny = (function() {
        var log = new Log(document.getElementById('manny-log')),
            cache = window.applicationCache,
            watchInterval = false;

        cache.addEventListener('checking', function() {
            log.log('checking for updates...');
        });
        cache.addEventListener('noupdate', function() {
            log.log('no updates found.');
            manny.online = true;
        });
        cache.addEventListener('updateready', function() {
            log.log('successfully updated. refresh to view new content.');
            if (manny.autoupdate) {
                log.log('reloading...');
                window.location.reload();
            }
        });
        cache.addEventListener('downloading', function() {
            log.log('updating...');
            manny.online = true;
        });
        cache.addEventListener('progress', function(e) {
            log.log('downloading resources (' + e.loaded + '/' + e.total + ')');
        });
        cache.addEventListener('error', function() {
            log.log('an error occurred.');
            manny.online = navigator.onLine || false;
            if (navigator.onLine === false) {
                log.log('browser is offline.');
            }
        });
        cache.addEventListener('cached', function() {
            log.log('successfully updated. refresh to view new content.');
        });

        var manny = {
            cache: cache,
            log: log,
            autoupdate: false,
            online: true,
            watch: function(interval) {
                interval = interval || 30*1000;
                log.log('polling for new manifest every ' + interval + 'ms');
                watchInterval = setInterval(function() {
                    cache.update();
                }, interval);
            },
            unwatch: function() {
                log.log('suspending polling');
                clearInterval(watchInterval);
            },
            size: function() {
                return cache.mozLength || cache.webkitLength || 0;
            }
        };

        return manny;
    })();
}