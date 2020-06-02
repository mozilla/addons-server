// GA Analytics code. The 'create' below is specific to AMO tracking.

function isDoNotTrackEnabled() {
  // We ignore things like `msDoNotTrack` because they are for older,
  // unsupported browsers and don't really respect the DNT spec. This
  // covers new versions of IE/Edge, Firefox from 32+, Chrome, Safari, and
  // any browsers built on these stacks (Chromium, Tor Browser, etc.).
  var dnt = navigator.doNotTrack || window.doNotTrack;
  if (dnt === '1') {
    window.console &&
      console.info(
        '[TRACKING]: Do Not Track Enabled; Google Analytics will not be loaded.',
      );
    return true;
  }

  // Known DNT values not set, so we will assume it's off.
  return false;
}

if (isDoNotTrackEnabled() === false) {
  (function (i, s, o, g, r, a, m) {
    i['GoogleAnalyticsObject'] = r;
    (i[r] =
      i[r] ||
      function () {
        (i[r].q = i[r].q || []).push(arguments);
      }),
      (i[r].l = 1 * new Date());
    (a = s.createElement(o)), (m = s.getElementsByTagName(o)[0]);
    a.async = 1;
    a.src = g;
    m.parentNode.insertBefore(a, m);
  })(
    window,
    document,
    'script',
    'https://www.google-analytics.com/analytics.js',
    'ga',
  );

  ga('create', 'UA-36116321-7', 'auto');
  ga('set', 'transport', 'beacon');
  ga('send', 'pageview');
}
