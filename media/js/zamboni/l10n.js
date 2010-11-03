$(document).ready(function () {
    if (!$("#l10n-menu").length) return;
    var locales = [];
        dl = $('.default_locale').attr('href').substring(1);
        currentLocale = dl;

    var localePopup = $("#locale-popup").popup("#change-locale", {
        pointTo: "#change-locale",
        width: 200,
        callback: function() {
            discoverLocales();
            $el = $("#existing_locales").empty();
            $("#all_locales li").show();
            $.each(_.without(locales, dl), function() {
                var locale_row = $(format("#all_locales a[href$={0}]",[this])).parent();
                if (locale_row.length) {
                    $el.append("<li>" + locale_row.html() + "</li>");
                    locale_row.hide();
                }
            });

            $("#locale-popup").delegate('a', 'click', function (e) {
                e.preventDefault();
                $tgt = $(this);
                var new_locale = $tgt.attr("href").substring(1);
                if (!_.include(locales,new_locale)) {
                    locales.push(new_locale);
                }
                $("#change-locale").text($tgt.text());
                updateLocale(new_locale);
                localePopup.hideMe();
            });

            return true;
        }
    });

    function updateLocale(lang) {
        lang = lang || currentLocale;
        $(".trans").each(function () {
            var $el = $(this),
                field = $el.attr('data-name');
                label = $(format("label[for={0}]",[field]));
            if (!$el.children(format("[lang={0}]",[lang])).length) {
                var $ni = $el.children(format("[lang={0}]",[dl])).clone();
                $ni.attr('id',format('id_{0}_{1}',[field,lang]))
                   .val("").html("").attr("lang", lang).attr('name',[field,lang].join('_'));
                $el.append($ni);
            }
            if (label.length) {
                label.children(".locale").remove();
                label.append(format("<span class='locale'>{0}</span>",[$("#change-locale").text()]));
            }
        
        });
        if (currentLocale != lang) {
            currentLocale = lang;
        }
        $(format(".trans [lang!={0}]:visible", [currentLocale])).hide();
        $(format(".trans [lang={0}]", [lang])).show();
    }

    function discoverLocales(locale) {
        var seen_locales = {};
        $(".trans [lang]").each(function () {
            seen_locales[$(this).attr('lang')] = true;
        });
        locales = _.keys(seen_locales);
    }

    z.refreshL10n = function() {
        updateLocale();
    }
});