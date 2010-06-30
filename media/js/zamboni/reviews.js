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
                    var flag = $(e.target).attr('href').slice(1)
                    if (flag == 'other') {
                        // Show the Other form and bind the submit.
                        parent.addClass('other');
                        $(this).find('form').submit(function(e){
                            e.preventDefault();
                            var note = parent.find('#id_note').val();
                            addFlag(parent, url, 'other', note);
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
                success: function(){
                    el.find('.flag-review')
                        .replaceWith(gettext('Flagged for review'));
                },
                error: function(){ },
                dataType: 'json'
        });
    };
});
