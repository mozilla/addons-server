define('buckets', [], function() {

    var aelem = document.createElement('audio');
    var velem = document.createElement('video');

    // Compatibilty with PhantomJS, which doesn't implement canPlayType
    if (!('canPlayType' in aelem)) {
        function noop() {return '';};
        velem = aelem = {canPlayType: noop};
    }

    var prefixes = ['moz', 'webkit', 'ms'];

    function prefixed(property, context) {
        if (!context) {
            context = window;
        }
        try {
            if (property in context) {
                return context[property];
            }
        } catch(e) {
            return false;
        }
        // Camel-case it.
        property = property[0].toUpperCase() + property.substr(1);

        for (var i = 0, e; e = prefixes[i++];) {
            try {
                if ((e + property) in context) {
                    return context[e + property];
                }
            } catch(e) {
                return false;
            }
        }
    }

    var has_gum = prefixed('getUserMedia', navigator);
    if (has_gum && navigator.mozGetUserMedia) {
        // Gecko 18's gum is a noop. FFFFFFFFFUUUUUUUUUUUUUU
        try {
            navigator.mozGetUserMedia(); // Should throw a TypeError.
            has_gum = false;
        } catch(e) {}
    }

    var has_audiocontext = !!(window.webkitAudioContext || window.AudioContext);

    var capabilities = [
        'mozApps' in navigator,
        'mozApps' in navigator && navigator.mozApps.installPackage,
        'mozPay' in navigator,
        // FF 18 and earlier throw an exception on this key
        (function() {try{return !!window.MozActivity} catch(e) {return false;}})(),
        'ondevicelight' in window,
        'ArchiveReader' in window,
        'battery' in navigator,
        'mozBluetooth' in navigator,
        'mozContacts' in navigator,
        'getDeviceStorage' in navigator,
        (function() { try{return window.mozIndexedDB || window.indexedDB} catch(e) {return false}})(),
        'geolocation' in navigator && 'getCurrentPosition' in navigator.geolocation,
        'addIdleObserver' in navigator && 'removeIdleObserver' in navigator,
        'mozConnection' in navigator && (navigator.mozConnection.metered === true || navigator.mozConnection.metered === false),
        'mozNetworkStats' in navigator,
        'ondeviceproximity' in window,
        'mozPush' in navigator || 'push' in navigator,
        'ondeviceorientation' in window,
        'mozTime' in navigator,
        'vibrate' in navigator,
        'mozFM' in navigator || 'mozFMRadio' in navigator,
        'mozSms' in navigator,
        !!(('ontouchstart' in window) || window.DocumentTouch && document instanceof DocumentTouch),
        window.screen.width <= 540 && window.screen.height <= 960,  // qHD support
        !!aelem.canPlayType('audio/mpeg').replace(/^no$/, ''),  // mp3 support
        !!(window.Audio),  // Audio Data API
        has_audiocontext,  // Web Audio API
        !!velem.canPlayType('video/mp4; codecs="avc1.42E01E"').replace(/^no$/,''),  // H.264
        !!velem.canPlayType('video/webm; codecs="vp8"').replace(/^no$/,''),  // WebM
        !!prefixed('cancelFullScreen', document),  // Full Screen API
        !!prefixed('getGamepads', navigator),  // Gamepad API
        !!(prefixed('persistentStorage') || window.StorageInfo),  // Quota Management API
        // WebRTC:
        has_gum && !prefixed('cameras', navigator),  // Can take photos
        has_gum && has_audiocontext &&
            !!((new (window.AudioContext || window.webkitAudioContext)()).createMediaStreamSource),  // Can record audio
        has_gum && false,  // XXX: Google WebRTC issue 2088
        'MediaStream' in window,
        'DataChannel' in window,
        prefixed('RTCPeerConnection'),
        prefixed('SpeechSynthesisEvent'),  // WebSpeech Synthesis
        prefixed('SpeechInputEvent'),  // WebSpeech Input
        prefixed('requestPointerLock', document.documentElement),  // Pointer lock
        prefixed('notification', navigator),  // TODO: window.webkitNotifications?
        prefixed('alarms', navigator),  // Alarms
        'mozSystem' in (new XMLHttpRequest()),  // mozSystemXHR
        prefixed('TCPSocket', navigator),  // mozTCPSocket/mozTCPSocketServer
        prefixed('mozInputMethod', navigator)
    ];

    var profile = parseInt(capabilities.map(function(x) {return !!x ? '1' : '0';}).join(''), 2).toString(16);
    // Add a count.
    profile += '.' + capabilities.length;
    // Add a version number.
    profile += '.3';

    return {
        get_profile: function() {return profile;},
        capabilities: capabilities
    };

});
