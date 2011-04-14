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
        initReviewActions();
    }
});

function initReviewActions() {
    var groups = $('#id_canned_response').find('optgroup');
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

        /* Fade out canned responses */
        var label = $element.text().trim();
        groups.css('color', '#AAA');
        groups.filter("[label='"+label+"']").css('color', '#444');
    }

    $('#review-actions .action_nav ul li').click(function(){ showForm(this); });

    /* Canned Response stuff */
    $('.review-actions-canned select').change(function() {
        insertAtCursor($('#id_comments'), $(this).val());
    });

    var review_checked = $('#review-actions [name=action]:checked');
    if(review_checked.length > 0) {
      showForm(review_checked.closest('li'), true);
    }

    /* File checkboxes */
    var $files_input = $('#review-actions .review-actions-files').find('input:enabled');

    if($files_input.length == 1 || ! $('#review-actions .review-actions-files').attr('data-uncheckable')) {
        // Add a dummy, disabled input
        $files_input.attr({'checked': true}).hide();
        $files_input.after($('<input>', {'type': 'checkbox', 'checked': true, 'disabled': true}));
    }

    function toggle_input(){
        var $files_checked = $files_input.filter(':checked');
        $('.review-actions-save input').attr('disabled', $files_checked.length < 1);

        // If it's not :visible, we can assume it's been replaced with a dummy :disabled input
        $('#review-actions-files-warning').toggle($files_checked.filter(':enabled:visible').length > 1);
    }

    $files_input.change(toggle_input).each(toggle_input);

    /* Install Triggers */

    $('.files .install').click(_pd(function(){
        var $this = $(this),
            installer = $this.is('[data-type=search-tools]') ? z.installSearch : z.installAddon;
        installer($this.text(), $this.attr('href'), "")
    }));

}

function insertAtCursor(textarea, text) {
    var area = $(textarea)[0],
        scrollPos = area.scrollTop;
    // IE
    if (document.selection) {
        area.focus();
        var rng = document.selection.createRange();
        rng.text = text + rng.text;
    // FF/Safari/Chrome
    } else if (area.selectionStart || area.selectionStart == '0') {
        area.focus();
        var startPos = area.selectionStart;
        area.value = area.value.substring(0, startPos) + text + area.value.substring(startPos, area.value.length);
        area.setSelectionRange(startPos + text.length, startPos + text.length);
        // everything else - append text to end
    } else {
        area.value += text;
    }
    // restore scrollbar location
    area.scrollTop = scrollPos;
}


function initDailyMessage(doc) {
    var $motd = $('.daily-message', doc),
        storage = z.Storage();
    if ($('#editor-motd', doc).length) {
        // The message on the MOTD page should never be closable, so don't
        // show close button nor attach handlers.
        return;
    }
    $motd.find('.close').show();
    if (storage.get('motd_closed') == $('p', $motd).text()) {
        $motd.hide();
    }
    $motd.find('.close').click(function(e) {
        e.stopPropagation();
        storage.set('motd_closed', $('.daily-message p').text());
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
