(function() {
"use strict";

$(function() {
    if ($('#admin-validation').length) {
        initAdminValidation($('#admin-validation'));
    }
});


function initAdminValidation(doc) {
    var $elem = $('#id_application', doc);

    $elem.change(function(e) {
        var maxVer = $('#id_curr_max_version, #id_target_version', doc),
            sel = $(e.target),
            appId = $('option:selected', sel).val();

        if (!appId) {
            $('option', maxVer).remove();
            maxVer.append(format('<option value="{0}">{1}</option>',
                                 ['', gettext('Select an application first')]));
            return;
        }
        $.post(sel.attr('data-url'), {'application_id': appId}, function(d) {
            $('option', maxVer).remove();
            $.each(d.choices, function(i, ch) {
                maxVer.append(format('<option value="{0}">{1}</option>',
                                     [ch[0], ch[1]]));
            });
        });
    });

    if ($elem.children('option:selected').val() &&
        !$('#id_curr_max_version option:selected, ' +
           '#id_target_version option:selected', doc).val()) {
        // If an app is selected when page loads and it's not a form post.
        $elem.trigger('change');
    }

    var $popup = $('#notify').popup('td a.v-popup', {
        width: '600px',
        callback: function(obj) {
            var $ct = $(obj.click_target),
                msg = '',
                form = '';
            if ($ct.hasClass('set-max-version')) {
                // L10n: {0} is the number of add-ons, {1} is a version like 4.0
                msg = ngettext('Set {0} add-on to a max version of {1} and email the author.',
                               'Set {0} add-ons to a max version of {1} and email the authors',
                               $ct.attr('data-job-count'));
                msg = format(msg, [$ct.attr('data-job-count'), $ct.attr('data-job-version')]);
                form = $('#success-form').html();
            } else {
                msg = ngettext('This will send emails to the authors of {0} file.',
                               'This will send emails to the authors of {0} files.',
                               $ct.attr('data-notify-count'));
                msg = format(msg, [$ct.attr('data-notify-count')]);
                form = $('#failure-form').html();
            }
            $(this).find('p').eq(0).text(msg);
            $(this).children('form').attr('action', $ct.attr('data-job-url'));
            $(this).find('div').eq(1).html(form); // note eq(0) is the csrf hidden div
            return { pointTo: $ct };
        }
    });

    $('#notify form').submit(function(e) {
        var $form = $(this);
        if ($form.attr('data-valid') != 'valid') {
            $.post($form.attr('data-url'), $(this).serialize(), function(json) {
                if (json && json.valid) {
                    $form.attr('data-valid', 'valid').submit();
                } else {
                    $form.find('p.error').text(json.error).show();
                }
            });
            e.preventDefault();
            return false;
        } else {
            return true;
        }
    });
    $('#notify form span.cancel a').click(_pd(function() {
        $popup.hideMe();
    }));
}

})();
