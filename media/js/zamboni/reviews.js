$(document).ready(function() {
    var report = $('.review-reason').html();

    $(".review-reason").popup(".flag-review", {
        delegate: $(document.body),
        width: 'inherit',
        callback: function(obj) {
            var ct = $(obj.click_target),
                $popup = this;

            function addFlag(flag, note) {
                $.ajax({type: 'POST',
                        url: ct.attr("href"),
                        data: {flag: flag, note: note},
                        success: function() {
                            $popup.removeClass("other")
                                  .hideMe();
                            ct.replaceWith(gettext('Flagged for review'));
                        },
                        error: function(){ },
                        dataType: 'json'
                });
            };

            $popup.delegate("li a", "click", function(e) {
                e.preventDefault();
                var el = $(e.target);
                if (el.attr("href") == "#review_flag_reason_other") {
                    $popup.addClass('other')
                          .delegate("form", "submit", function(e) {
                              e.preventDefault();
                              var note = $popup.find('#id_note').val();
                              if (!note) {
                                  alert(gettext('Your input is required'));
                              } else {
                                  addFlag('review_flag_reason_other', note);
                              }
                          })
                          .setPos(ct)
                          .find('input[type=text]')
                          .focus();
                } else {
                    addFlag(el.attr("href").slice(1));
                }
            });

            $popup.html(report);
            return { pointTo: ct };
        }
    });

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
