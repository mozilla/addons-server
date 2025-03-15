// GA Analytics code. The 'create' below is specific to AMO tracking.

function isDoNotTrackEnabled() {
  // We ignore things like `msDoNotTrack` because they are for older,
  // unsupported browsers and don't really respect the DNT spec. This
  // covers new versions of IE/Edge, Firefox from 32+, Chrome, Safari, and
  // any browsers built on these stacks (Chromium, Tor Browser, etc.).
  let dnt = navigator.doNotTrack || window.doNotTrack;
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

export function insertAnalyticsScript(dnt = isDoNotTrackEnabled()) {
  if (dnt) return;

  (function (i, s, o, g, r, a, m) {
    i['GoogleAnalyticsObject'] = r;
    i[r] =
      i[r] ||
      function () {
        (i[r].q = i[r].q || []).push(arguments);
      };
    i[r].l = 1 * new Date();
    a = s.createElement(o);
    m = s.getElementsByTagName(o)[0] || null;

    a.async = 1;
    a.src = g;

    if (m && m.parentNode) {
      // Insert before the first script tag
      m.parentNode.insertBefore(a, m);
    } else {
      // Fallback if there is no existing <script> tag
      // (e.g., testing environment with an empty DOM)
      s.head.appendChild(a);
    }
  })(
    window,
    document,
    'script',
    'https://www.google-analytics.com/analytics.js',
    'ga',
  );

  window.ga('create', 'UA-36116321-7', 'auto');
  window.ga('set', 'transport', 'beacon');
  window.ga('send', 'pageview');

  // Insert the script tag for GA4.
  const ga4Id = 'G-B9CY1C9VBC';
  const newTag = document.createElement('script');
  const firstTag = document.getElementsByTagName('script')[0];
  newTag.async = 1;
  newTag.src = `https://www.googletagmanager.com/gtag/js?id=${ga4Id}`;
  firstTag.parentNode.insertBefore(newTag, firstTag);

  // Set up GA4.
  window.dataLayer = window.dataLayer || [];
  function gtag() {
    window.dataLayer.push(arguments);
  }
  gtag('js', new Date());
  gtag('config', ga4Id);
}
