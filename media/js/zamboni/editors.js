$(function() {
    if($('.daily-message').length) {
        initDailyMessage();
    }


    var show_comments = function(e) {
        e.preventDefault()
        var me = e.target;
        $(me).hide()
        $(me).next().show()
        $(me).parents('tr').next().show()
    }

    var hide_comments = function(e) {
        e.preventDefault();
        var me = e.target;
        $(me).hide();
        $(me).prev().show()
        $(me).parents('tr').next().hide()
    }


    $('a.show').click(show_comments);
    $('a.hide').click(hide_comments);

    if ($('#queue-search').length) {
        initQueueSearch($('#queue-search'));
    }

    if($('#review-actions').length > 0) {
        function showForm(element, pageload) {
            var $element = $(element),
                value = $element.find('input').val(),
                $data_toggle = $('#review-actions-form').find('.data-toggle');

            pageload = pageload || false;
            $element.closest('.review-actions').addClass('on');
            $('.review-actions .action_nav ul li').removeClass('on-tab');
            $element.find('input').attr('checked', true);

            $element.addClass('on-tab');

            if (pageload) {
              $('#review-actions-form').show();
            } else {
              $('#review-actions-form').slideDown();
              $('#review-actions').find('.errorlist').remove();
            }

            $data_toggle.hide();
            $data_toggle.filter('[data-value*="' + value + '"]').show();
        }

        $('#review-actions .action_nav ul li').click(function(){ showForm(this); });

        $('.review-actions-canned select').change(function() {
            $('#id_comments').val($(this).val());
        });

        var review_checked = $('#review-actions [name=action]:checked');
        if(review_checked.length > 0) {
          showForm(review_checked.closest('li'), true);
        }

    }
});

function initDailyMessage(doc) {
    var canCloseMsg,
        $motd = $('.daily-message', doc);
    try {
        if ('localStorage' in window && window['localStorage'] !== null) {
            canCloseMsg = true;
        }
    } catch(e) {
        // Exception thrown when cookies are off (bug in older Firefox)
        canCloseMsg = false;
    }
    if ($('#editor-motd', doc).length) {
        // The message on the MOTD page should never be closable
        canCloseMsg = false;
    }
    if (!canCloseMsg) {
        // Don't show close button, don't attach handlers
        return;
    }
    $motd.find('.close').show();
    if (window.localStorage['motd_closed'] == $('p', $motd).text()) {
        $motd.hide();
    }
    $motd.find('.close').click(function(e) {
        e.stopPropagation();
        window.localStorage['motd_closed'] = $('.daily-message p').text();
        $motd.slideUp();
    });
}

function initQueueSearch(doc) {
    $('#toggle-queue-search', doc).click(function(e) {
        e.preventDefault();
        $(e.target).blur();
        if ($('#advanced-search:visible', doc).length) {
            $('#advanced-search', doc).slideUp();
        } else {
            $('#advanced-search', doc).slideDown();
        }
    });

    $('#id_application_id', doc).change(function(e) {
        var maxVer = $('#id_max_version', doc),
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
}
