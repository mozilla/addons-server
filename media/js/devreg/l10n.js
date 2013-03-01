// Yes, this is out here for a reason.
// We want to hide the non-default locales as fast as possible.
(function() {
    var dl = $('body').attr("data-default-locale");
    if (dl) {
        $(format(".trans>:not([lang='{0}'])", dl)).hide();
        $(format(".trans [lang='{0}']", dl)).show();
    }
})();

$(document).ready(function () {
    if (!$("#l10n-menu").length) return;
    var locales = [],
        dl = $('body').attr("data-default-locale"),
        currentLocale = dl,
        unsavedModalMsg = $('#modal-l10n-unsaved .msg').html(),
        unsavedModal = $('#modal-l10n-unsaved').modal(),
        rmLocaleModalMsg = $('#modal-l10n-rm .msg').html(),
        rmLocaleModal = $('#modal-l10n-rm').modal(),
        modalActions = $(".modal-actions", unsavedModal),
        translations = {}; //hold the initial values of the fields to check for changes

    $(".primary").delegate(".trans input, .trans textarea", "change keyup paste blur", checkTranslation);
    $("form").submit(function () {
        $(this).find(".trans .cloned").remove();
    });

    function popuplateTranslations(el) { //load in the initial values of the translations
        el.find(".trans input[lang], .trans textarea[lang]").each(function() {
            var $input = $(this),
                $trans = $input.closest(".trans"),
                transKey = $trans.attr("data-name")+'_'+$input.attr('lang');
            translations[transKey] = $input.val();
        });
    }

    function showExistingLocales() {
        discoverLocales();
        $el = $("#existing_locales").empty();
        $("#all_locales li").show();
        $.each(_.without(locales, dl), function() {
            var locale_row = $(format("#all_locales a[href$='{0}']",[this])).parent();
            if (locale_row.length) {
                $el.append(format("<li><a title='{msg}'class='remove' href='#'>x</a>{row}</li>",
                    {   msg: gettext('Remove this localization'),
                        row: locale_row.html()
                    }));
                locale_row.hide();
            }
        });
    }

    function checkTranslation(e, t) {
        var $input = e.originalEvent ? $(this) : $(format("[lang='{0}']", [e]), t),
            $trans = $input.closest(".trans"),
            lang = e.originalEvent ? $input.attr("lang") : e,
            $dl = $(format("[lang='{0}']", [dl]), $trans),
            transKey = $trans.attr("data-name")+'_'+lang;
        if ($input.length == 0 || $input.is('span')) {
            // No translation of this element exists for the
            // requested language.
            return;
        }
        if (!(transKey in translations)) {
            translations[transKey] = $input.val();
        }
        if (lang != dl) {
            if ($input.val() == $dl.val() && $input.val().trim().length) {
                $input.addClass("cloned");
            } else if (!$input.val().trim().length) {
                if (e.originalEvent && e.type == "focusout") {
                    $input.val($dl.val()).addClass("cloned");
                } else {
                    $input.removeClass("cloned");
                }
            } else {
                $input.removeClass("cloned");
            }
        }
        if (translations[transKey] != $input.val()) {
            $input.addClass("unsaved");
        } else {
            $input.removeClass("unsaved");
        }
    }

    $(".primary").delegate(".errorlist .l10n", "click", switchLocale);

    $("#all_locales").delegate("a", "switch", switchLocale);

    // If the locale switcher is visible, use the cookie.
    var initLocale = dl;
    if ($('#l10n-menu:visible').length) {
        initLocale = $.cookie('current_locale');
    }
    $(format("#all_locales a[href$='{0}']",[initLocale])).trigger("switch");

    function switchLocale(e) {
        e.preventDefault();
        $tgt = $(this);
        var new_locale = $tgt.attr("data-lang") || $tgt.attr("href").substring(1);
        var unsaved = $("form .trans .unsaved");

        if (unsaved.length && new_locale != currentLocale) {
            unsavedModal.children(".msg")
                .html(format(unsavedModalMsg,[$("#change-locale").text()]));
            unsavedModal.render();
            $("#l10n-save-changes").unbind().click(function () {
                var unsavedForms = $('form:has(.trans .unsaved)');
                var numFormsLeft = unsavedForms.length;
                var erroredForms = 0;
                modalActions.addClass("ajax-loading");
                modalActions.find("button").addClass("disabled");
                unsavedForms.each(function() {
                    var $form = $(this);
                    $.ajax({
                        url: $form.attr('action'),
                        type: "post",
                        data: $form.serialize(),
                        error: function() {
                            modalActions.removeClass("ajax-loading");
                        },
                        success: function(d) {
                            var $resp = $(d);
                            if ($form.attr('id') && $resp.find('#' + $form.attr('id')).length) {
                                $resp = $resp.find('#' + $form.attr('id'));
                            }
                            // Add locale names to error messages
                            annotateLocalizedErrors($resp);
                            numFormsLeft--;
                            if ($resp.find(".errorlist").length) { //display errors if they occur
                                $form.html($resp.html());
                                updateLocale();
                                if ($resp.find(format(".errorlist li[data-lang='{0}']", currentLocale)).length) {
                                    erroredForms++;
                                }
                            } else { //clean up the errors we inserted
                                popuplateTranslations($form);
                                $form.find(".unsaved").removeClass("unsaved");
                                $form.find(".errorlist").remove();
                            }
                            if (numFormsLeft < 1) {
                                if (erroredForms) {
                                    window.scrollTo(0,$(".errorlist .l10n").closest("form").offset().top);
                                    $(".errorlist").first().siblings(".trans")
                                        .find("input:visible, textarea:visible").focus();
                                } else {
                                    updateLocale(new_locale);
                                }
                            }
                            modalActions.removeClass("ajax-loading");
                            modalActions.find("button").removeClass("disabled");
                            unsavedModal.hideMe();
                        }
                    });
                });
            });
            $("#l10n-discard-changes").click(function () {
                $('.trans .unsaved').remove();
                updateLocale(new_locale);
                unsavedModal.hideMe();
            });
            $("#l10n-cancel-changes").click(function () {
                unsavedModal.hideMe();
            });
        } else {
            updateLocale(new_locale);
        }

        if(localePopup) {
            localePopup.hideMe();
        }
    }

    var localePopup = $("#locale-popup").popup("#change-locale", {
        pointTo: "#change-locale",
        width: 200,
        callback: function() {
            showExistingLocales();
            $("#locale-popup").delegate('a:not(.remove)', 'click', switchLocale);
            $("#locale-popup").delegate('a.remove', 'click', function (e) {
                e.preventDefault();
                e.stopPropagation();
                var toRemove = $(this).closest("li").find("a:not(.remove)").attr("href").substring(1);
                rmLocaleModal.children(".msg").html(format(rmLocaleModalMsg,toRemove));
                rmLocaleModal.render();
                $('#l10n-cancel-rm').unbind().click(rmLocaleModal.hideMe);
                function cleanUp() {
                    $(".modal-actions", rmLocaleModal).removeClass('ajax-loading');
                    rmLocaleModal.hideMe();
                }
                $('#l10n-confirm-rm').unbind().click(function(e) {
                    $(".modal-actions", rmLocaleModal).addClass('ajax-loading');
                    $.ajax({
                        url: $('#l10n-menu').attr('data-rm-locale'),
                        type: "post",
                        data: {locale: toRemove},
                        error: function() {
                            cleanUp();
                        },
                        success: function() {
                            if (currentLocale == toRemove) {
                                updateLocale(dl);
                            }
                            $('.trans [lang='+toRemove+']').remove();
                            cleanUp();
                        }
                    });
                });
            });
            return true;
        }
    });

    function updateLocale(lang) {
        lang = lang || currentLocale;
        if (currentLocale != lang) {
            currentLocale = lang;
        }
        if (!_.include(locales,lang)) {
            locales.push(lang);
        }
        var current = $(format("#locale-popup [href$='{0}']", [lang])).first().clone();
        current.find('em').remove();
        $("#change-locale").text(current.text());
        $(".trans").each(function () {
            var $el = $(this),
                field = $el.attr('data-name'),
                label = $(format("label[data-for='{0}']",[field]));
            if (!$el.find(format("[lang='{0}']",[lang])).length) {
                if ($el.children(".trans-init").length) {
                    var $ni = $el.children(".trans-init").clone();
                    $ni.attr({
                        "class": "",
                        lang: lang,
                        id: format('id_{0}_{1}', field, lang),
                        name: [field,lang].join('_'),
                        value: $el.find(format("[lang='{0}']",[dl])).val()
                    });
                    if (lang != dl) $ni.addClass("cloned");
                } else {
                    var $ni = $el.find(format("[lang='{0}']",dl)).clone();
                    $ni.attr({
                        "class": "cloned",
                        lang: lang
                    });
                }
                $el.append($ni);
            }
            checkTranslation(lang, $el);
            if (label.length) {
                label.children(".locale").remove();
                label.append(format("<span class='locale'>{0}</span>",[$("#change-locale").text()]));
                label_for = $el.children(format("[lang='{0}']",[lang])).attr('id');
                label.attr('for', label_for);
            }

        });
        $(format(".trans>:not([lang='{0}'])", currentLocale)).hide();
        $(format(".trans [lang='{0}']", currentLocale)).show();
        initCharCount();
        if ($.cookie('current_locale') != currentLocale &&
            currentLocale != dl) {
            $.cookie('current_locale', null);
            $.cookie('current_locale', currentLocale, {expires: 0});
        }
    }

    function discoverLocales(locale) {
        var seen_locales = {};
        $(".trans [lang]").each(function () {
            seen_locales[$(this).attr('lang')] = true;
        });
        locales = _.keys(seen_locales);
    }

    z.refreshL10n = function(lang) {
        updateLocale(lang);
    };
    updateLocale();
});


function annotateLocalizedErrors($el) {
    $el.find(".errorlist li[data-lang]:not(.l10n)").each(function() {
        var err = $(this),
            t = err.text(),
            l = $(format("#locale-popup [href$='{0}']", [err.attr('data-lang')])).first().text();
        err.text(format("{0}: ",[l])+t).addClass("l10n");
    });
}


function loc(s) {
    // A noop function for strings that are not ready to be localized.
    return s;
}
