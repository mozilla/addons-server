$(function() {
    // Main page
    if($('#editors_main').length) {
        initEditorsMain();
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
});

function initEditorsMain() {
    var $motd = $('#editors_main .daily-message');
    try {
        if('localStorage' in window && window['localStorage'] !== null) {
            if(window.localStorage['motd_closed'] == $('p', $motd).text()) {
                $motd.hide();
            }
            $motd.find('.close').click(close_motd);
            $motd.find('.close').show();
        }
    } catch(e){}

    function close_motd(e) {
        e.stopPropagation();
        try {
            if('localStorage' in window && window['localStorage'] !== null) {
                window.localStorage['motd_closed'] = $('#editors_main .daily-message p').text();
            }
            $motd.slideUp();
        } catch(e){}
    }
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
