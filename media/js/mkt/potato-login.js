(function() {
    window.addEventListener('message', function(e) {

        function postBack(key, value) {
            e.source.postMessage([key, value], '*');
        }

        var key = e.data[0];
        var body = e.data[1];
        console.log('[potato][iframe] Got message from ' + e.origin, key, body);

        switch (key) {
            case 'navigator.id.request':
                body.oncancel = function() {
                    console.log('[potato][iframe] n.id.request cancelled');
                    postBack('navigator.id.request:cancel', true);
                };
                navigator.id.request(body);
                break;
            case 'navigator.id.logout':
                if (navigator.id.logout) {
                    console.log('[potato][iframe] Logout requested');
                    navigator.id.logout();
                }
                break;
            case 'navigator.id.watch':
                postBack('_shimmed', navigator.id._shimmed);
                console.log('[potato][iframe] n.id.watch for ' + body);
                navigator.id.watch({
                    loggedInUser: body,
                    onlogin: function(assertion) {
                        console.log('[potato][iframe] n.id.watch logged in');
                        postBack('navigator.id.watch:login', assertion);
                    },
                    onlogout: function() {
                        console.log('[potato][iframe] n.id.watch logged out');
                        postBack('navigator.id.watch:logout', true);
                    },
                })
                break;
        }

    }, false);

    // Load `include.js` from persona.org, and drop login hotness like it's hot.
    var s = document.createElement('script');

    var desktop
    var android = navigator.userAgent.indexOf('Firefox') !== -1 && navigator.userAgent.indexOf('Android') !== -1;
    var fxos = navigator.mozApps && !android && navigator.userAgent.indexOf('Mobile') !== -1;

    if (fxos) {
        // Load the Firefox OS include that knows how to handle native Persona.
        // Once this functionality lands in the normal include we can stop
        // doing this special case. See bug 821351.
        s.src = document.body.attributes.getNamedItem('data-native-persona-url').value;
    } else {
        s.src = document.body.attributes.getNamedItem('data-persona-url').value;
    }
    document.body.appendChild(s);

})();
