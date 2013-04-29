(function() {

var languages = ['en-US', 'es', 'pl', 'pt-BR', 'dbg'];

var lang_expander = {
    'en': 'en-US', 'ga': 'ga-IE',
    'pt': 'pt-BR', 'sv': 'sv-SE',
    'zh': 'zh-CN'
};

if (!window.define) {
    function get_locale(locale) {
        if (languages.indexOf(locale) !== -1) {
            return locale;
        }
        locale = locale.split('-')[0];
        if (languages.indexOf(locale) !== -1) {
            return locale;
        }
        if (locale in lang_expander) {
            locale = lang_expander[locale];
            if (languages.indexOf(locale) !== -1) {
                return locale;
            }
        }
        return 'en-US';
    }
    var qs_lang = /[\?&]lang=([\w\-]+)/i.exec(window.location.search);
    var locale = get_locale((qs_lang && qs_lang[1]) || navigator.language);
    if (locale === 'en-US') {
        return;
    }
    document.write('<script src="/locales/' + locale + '.js"></script>');

} else {
    define('l10n', ['format'], function(format) {
        var rtlList = ['ar', 'he', 'fa', 'ps', 'ur'];

        function get(str, args, context) {
            context = context || navigator;
            var out;
            if (context.l10n && str in context.l10n.strings) {
                out = context.l10n.strings[str].body;
            } else {
                out = str;
            }
            if (args) {
                out = format.format(out, args);
            }
            return out;
        }
        function nget(str, plural, args, context) {
            context = context || navigator;
            if (!args || !('n' in args)) {
                throw new Error('`n` not passed to ngettext');
            }
            var out;
            var n = args.n;
            if (context.l10n && str in context.l10n.strings) {
                var plid = context.l10n.pluralize(n);
                out = context.l10n.strings[str].plurals[plid];
            } else {
                out = n === 1 ? str : plural;
            }
            out = format.format(out, args);
            return out;
        }

        window.gettext = get;
        window.ngettext = nget;

        return {
            gettext: get,
            ngettext: nget,
            getDirection: function(context) {
                var language = context ? context.language : navigator.language;
                if (language.indexOf('-') > -1) {
                    language = language.split('-')[0];
                }
                // http://www.w3.org/International/questions/qa-scripts
                // Arabic, Hebrew, Farsi, Pashto, Urdu
                return rtlList.indexOf(language) >= 0 ? 'rtl' : 'ltr';
            }
        };
    });
}
})();
