(function() {
"use strict";

$(function() {
    if ($('#admin-validation').length) {
        initAdminValidation($('#admin-validation'));
    }
});


function initAdminValidation(doc) {
    var $elem = $('#id_application', doc),
        statInterval,
        incompleteJobs = {};

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
        $.post(sel.attr('data-url'), {'application': appId}, function(d) {
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
            // L10n: {0} is the number of add-ons, {1} is a version like 4.0
            msg = ngettext('Set {0} add-on to a max version of {1} and email the author.',
                           'Set {0} add-ons to a max version of {1} and email the authors.',
                           $ct.attr('data-job-count-passing')) + ' ' +
                  ngettext('Email author of {2} add-on which failed validation.',
                           'Email authors of {2} add-ons which failed validation.',
                           $ct.attr('data-job-count-failing'));

            msg = format(msg, [$ct.attr('data-job-count-passing'), $ct.attr('data-job-version'),
                               $ct.attr('data-job-count-failing')]);
            $(this).find('p.error').text('');  // clear any existing errors.
            $(this).find('p').eq(0).text(msg);
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
            return false;
        } else {
            return true;
        }
    });
    $('#notify form span.cancel a').click(_pd(function() {
        $popup.hideMe();
    }));

    function startStats() {
        var incompleteJobIds = [],
            checkStatus;
        $('tr.job-result').each(function(i, el) {
            var $el = $(el),
                $td = $el.children('td.tests-finished'),
                isComplete = parseInt($el.attr('data-is-complete'), 10),
                jobId = parseInt($el.attr('data-job-id'), 10);
            if (!isComplete) {
                incompleteJobIds.push(jobId);
                incompleteJobs[jobId] = $td;
                createProgressBar($td);
            }
        });
        if (incompleteJobIds.length) {
            var checkStatus = function() {
                $('#admin-validation').trigger('checkstats', [incompleteJobIds]);
            };
            checkStatus();
            statInterval = setInterval(checkStatus, 3000);
        }
    }

    startStats();

    $('td').on('receivestats', function(ev, stats) {
        var $el = $(this),
            $tr = $el.parent(),
            complete = stats.percent_complete;
        $tr.children('td.tested').text(stats.total);
        $tr.children('td.failing').text(stats.failing);
        $tr.children('td.passing').text(stats.passing);
        $tr.children('td.exceptions').text(stats.errors);
        $('.job-status-bar div', $el).animate({'width': complete + '%'},
                                              {duration: 500});
        if (stats.completed_timestamp != '') {
            delete incompleteJobs[stats.job_id];
            $('.job-status-bar', $el).remove();
            $el.text(stats.completed_timestamp);
            jobCompleted();
        }
    });

    $('#admin-validation').on('checkstats', function(ev, job_ids) {
        $.ajax({type: 'POST',
                url: $(this).attr('data-status-url'),
                data: {job_ids: JSON.stringify(job_ids)},
                cache: false,
                success: function(data) {
                    $.each(data, function(jobId, stats) {
                        if (incompleteJobs[jobId]) {
                            incompleteJobs[jobId].trigger('receivestats', [stats]);
                        } else {
                            if (typeof console !== 'undefined')
                                console.log('checkstats: Job ID does not exist: ' + jobId);
                        }
                    });
                },
                error: function(XMLHttpRequest, textStatus, errorThrown) {
                    if (typeof console !== 'undefined')
                        console.log('error: ' + textStatus);
                },
                dataType: 'json'
        });
    });

    function createProgressBar($el) {
        var bar = {};
        bar.progress_outside = $('<div>', {'class': 'job-status-bar'});
        bar.progress_inside = $('<div>').css('width', 0);
        bar.progress_outside.append(bar.progress_inside);
        $el.append(bar.progress_outside);
        bar.progress_outside.show();
    }

    function jobCompleted() {
        var allDone = true;
        $.each(incompleteJobs, function(jobId, el) {
            allDone = false;
        });
        if (allDone) {
            clearInterval(statInterval);
        }
    }
}

})();
