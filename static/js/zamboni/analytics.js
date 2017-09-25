// GA Analytics code. The '_setAccount' below is specific to AMO tracking.

function isDoNotTrackEnabled() {
    // We ignore things like `msDoNotTrack` because they are for older,
    // unsupported browsers and don't really respect the DNT spec. This
    // covers new versions of IE/Edge, Firefox from 32+, Chrome, Safari, and
    // any browsers built on these stacks (Chromium, Tor Browser, etc.).
    var dnt = navigator.doNotTrack || window.doNotTrack;
    if (dnt === '1') {
        window.console && console.info('[TRACKING]: Do Not Track Enabled; Google Analytics will not be loaded.');
        return true;
    }

    // Known DNT values not set, so we will assume it's off.
    return false;
}

var _gaq = _gaq || [];
_gaq.push(['_setAccount', 'UA-36116321-7']);
_gaq.push(['_trackPageview']);

(function() {
    if (isDoNotTrackEnabled() === false) {
      var ga = document.createElement('script');
      ga.type = 'text/javascript';
      ga.async = true;
      ga.src = ('https:' == document.location.protocol ? 'https://ssl' : 'http://www') + '.google-analytics.com/ga.js';
      var s = document.getElementsByTagName('script')[0];
      s.parentNode.insertBefore(ga, s);
    }
})();
