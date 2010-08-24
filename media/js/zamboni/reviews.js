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

    $('.primary').delegate('.review-edit', 'click', function(e) {
        e.preventDefault();
        var $form = $("#review-edit-form"),
            $review = $(this).parents(".review"),
            rating = $review.attr("data-rating"),
            edit_url = $("a.permalink", $review).attr("href") + "edit";
            $cancel = $("#review-edit-cancel");

        $review.attr("action", edit_url);
        $form.detach().insertAfter($review);
        $("#id_title").val($review.children("h5").text());
        $(".ratingwidget input:radio[value=" + rating + "]", $form).click();
        $("#id_body").val($review.children("p.review-body").text());
        $review.hide();
        $form.show();

        function done_edit() {
            $form.unbind().hide();
            $review.show();
            $cancel.unbind();
        }

        $cancel.click(function(e) {
            e.preventDefault();
            done_edit();
        });

        $form.submit(function (e) {
            e.preventDefault();
            $.ajax({type: 'POST',
                url: edit_url,
                data: $form.serialize(),
                success: function(response, status) {
                    $review.children("h5").text($("#id_title").val());
                    rating = $(".ratingwidget input:radio:checked", $form).val();
                    $(".stars", $review).removeClass('stars-0 stars-1 stars-2 stars-3 stars-4 stars-5').addClass('stars-' + rating);
                    rating = $review.attr("data-rating", rating);
                    $review.children("p.review-body").text($("#id_body").val());
                    done_edit();
                },
                dataType: 'json'
            });
            return false;
        });
    });


    $('.delete-review').click(function(e) {
        e.preventDefault();
        var target = $(e.target);
        $.post(target.attr('href'), function() {
            target.replaceWith(gettext('Marked for deletion'));
        });
        target.closest('.review').addClass('deleted');
    });
});
