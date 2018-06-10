/**
 * Small javascript helper to help admins edit translated content. Relies on
 * the same widgets as zamboni/l10n.js which is used in devhub, but is a much
 * simpler implementation as we only need to display all translations at all
 * times.
 *
 * Uses django.jQuery as it's meant as a companion to the django admin.
 */

django.jQuery(document).ready(function ($) {
    if (!$('body.change-form').length) {
        // This is only for change forms.
        return;
    }

    // Each localized field will be inside a <div class="trans">. We are
    // displaying all of them, so we want to add individual labels to let the
    // user know which one is for which locale.
    $('div.trans :input:visible').before(function() {
        let $elm = $(this);
        let $label = $('<label>');
        $label.prop('for', $elm.attr('id'))
        $label.text('[' + $elm.attr('lang') + ']');
        return $label;
    })
});
