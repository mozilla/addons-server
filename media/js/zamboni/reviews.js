$(document).ready(function() {
    var report = $('.review-reason').parent().html();
    $('.flag-review').addPopup(report)
        .bind('newPopup', function(e, popup) {
            // If there's a click on one of the flag links, submit it.
            // If they pick other, show the extra text field.
            $(popup).click(function(e) {
                var parent = $(this).parent(),
                    url = parent.find('.flag-review').attr('href');
                if ($(e.target).filter('a').length) {
                    e.preventDefault();
                    var flag = $(e.target).attr('href').slice(1);
                    if (flag == 'review_flag_reason_other') {
                        // Show the Other form and bind the submit.
                        parent.addClass('other').find('input[type=text]').focus();
                        $(this).find('form').submit(function(e){
                            e.preventDefault();
                            var note = parent.find('#id_note').val();
                            if (!note) {
                                alert(gettext('Your input is required'));
                                return false;
                            }
                            addFlag(parent, url, 'review_flag_reason_other',
                                    note);
                        });
                    } else {
                        addFlag(parent, url, flag, '');
                    }
                }
            });
        });

    var addFlag = function(el, url, flag, note) {
        $.ajax({type: 'POST',
                url: url,
                data: {flag: flag, note: note},
                success: function() {
                    el.find('.flag-review')
                        .replaceWith(gettext('Flagged for review'));
                },
                error: function(){ },
                dataType: 'json'
        });
        el.click();
    };

    $('.delete-review').click(function(e) {
        e.preventDefault();
        var target = $(e.target);
        $.post(target.attr('href'), function() {
            target.replaceWith(gettext('Marked for deletion'));
        });
        target.closest('.review').addClass('deleted');
    });
});
