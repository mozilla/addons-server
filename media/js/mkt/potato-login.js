(function() {
    window.addEventListener('message', function(e) {
        console.log('Got message from ' + e.origin);

        var key = e.data[0];
        var body = e.data[1];

        switch (key) {
            case 'navigator.id.request':
                body.oncancel = function() {
                    postBack('navigator.id.request:cancel', true);
                };
                navigator.id.request(body);
                break;
            case 'navigator.id.logout':
                if (navigator.id.logout) {
                    navigator.id.logout();
                }
                break;
            case 'navigator.id.watch':
                navigator.id.watch({
                    loggedInUser: body,
                    onlogin: function(assertion) {
                        postBack('navigator.id.watch:login', assertion);
                    },
                    onlogout: function() {
                        postBack('navigator.id.watch:logout', true);
                    },
                })
                break;
        }

    }, false);

    function postBack(key, value) {
        window.postMessage([key, value], '*');
    }

    // Load `include.js` from persona.org, and drop login hotness like it's hot.
    var s = document.createElement('script');
    s.onload = function() {
        postBack('setup', true);
    };

    var android = navigator.userAgent.indexOf('Firefox') !== -1 && navigator.userAgent.indexOf('Android') !== -1;
    var fxos = navigator.mozApps && !android;

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
