function isLocalStorageAvailable() {
  try {
    return 'localStorage' in window && window['localStorage'] !== null;
  } catch (_e) {
    return false;
  }
}

function isSessionStorageAvailable() {
  try {
    return 'sessionStorage' in window && window['sessionStorage'] !== null;
  } catch (_e) {
    return false;
  }
}

function getCapabilities() {
  return {
    JSON: window.JSON && typeof JSON.parse == 'function',
    debug: ('' + document.location).indexOf('dbg') >= 0,
    debug_in_page: ('' + document.location).indexOf('dbginpage') >= 0,
    console: window.console && typeof window.console.log == 'function',
    replaceState: typeof history.replaceState === 'function',
    chromeless: window.locationbar && !window.locationbar.visible,
    localStorage: isLocalStorageAvailable(),
    sessionStorage: isSessionStorageAvailable(),
    fileAPI: !!window.FileReader,
    performance: !!(
      window.performance ||
      window.msPerformance ||
      window.webkitPerformance ||
      window.mozPerformance
    ),
    webactivities: !!(window.setMessageHandler || window.mozSetMessageHandler),
  };
}

export const capabilities = getCapabilities();
