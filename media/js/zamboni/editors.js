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

    if($('.review-actions').length > 0) {
        $('.review-actions > ul li').click(function(){
            $(this).closest('.review-actions').addClass('on');
            $('.review-actions > ul li').filter('.on-tab').removeClass('on-tab');
            $(this).find('input').attr('checked', true);

            $(this).addClass('on-tab');

            $('#review-actions-form').slideDown();
        });

        $('.review-actions-canned select').change(function() {
            $('#id_comments').val($(this).val());
        });
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
        $('#advanced-search', doc).toggle();
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
