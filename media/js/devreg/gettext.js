// stub gettext for when servers are bad at things
if (typeof window.gettext !== 'function') {
    window.gettext = function gettext(s) {
        return s;
    };
}