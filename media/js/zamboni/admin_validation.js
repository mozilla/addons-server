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

    var $version_popup = $('#set-max-version').popup('a.set-max-version', {
        callback: function(obj) {
            var $ct = $(obj.click_target);
            var msg = ngettext('Set {0} addon-on to a max version of {1}.',
                               'Set {0} addon-ons to a max version of {1}.',
                               $ct.attr('data-job-count'));
            $(this).children('p').text(format(msg, [$ct.attr('data-job-count'),
                                                   $ct.attr('data-job-version')]));
            $(this).children('form').attr('action', $ct.attr('data-job-url'));
            return { pointTo: $ct };
        }
    });
    $('#set-max-version span.cancel a').click(function() {
        $version_popup.hideMe();
    });

    var $notify_popup = $('#notify').popup('a.notify', {
        callback: function(obj) {
            var $ct = $(obj.click_target);
            var msg = ngettext('This will send emails to the authors of {0} file.',
                               'This will send emails to the authors of {0} files.',
                               $ct.attr('data-notify-count'));
            $(this).find('p').eq(0).text(format(msg, [$ct.attr('data-notify-count')]));
            $(this).children('form').attr('action', $ct.attr('data-job-url'));
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
        } else {
            return true;
        }
    });
    $('#notify span.cancel a').click(function() {
        $notify_popup.hideMe();
    });
}


})();
