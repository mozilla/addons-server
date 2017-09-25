$(document).ready(function() {

    var report = $('.review-reason').html(),
        $window = $(window);

    $('.review-reason').popup('.flag-review', {
        delegate: $(document.body),
        width: 'inherit',
        callback: function(obj) {
            var ct = $(obj.click_target),
                $popup = this;
            //reset our event handlers
            $popup.hideMe();

            function addFlag(flag, note) {
                $.ajax({type: 'POST',
                        url: ct.attr('href'),
                        data: {flag: flag, note: note},
                        success: function() {
                            $popup.removeClass('other')
                                  .hideMe();
                            ct.closest('.item').addClass('flagged');
                            ct.replaceWith(gettext('Flagged for review'))
                              .addClass('flagged');
                        },
                        error: function(){ },
                        dataType: 'json'
                });
            };

            $popup.on('click', 'li a', function(e) {
                e.preventDefault();
                var el = $(e.target);
                if (el.attr('href') == '#review_flag_reason_other') {
                    $popup.addClass('other')
                          .on('submit', 'form', function(e) {
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
                    addFlag(el.attr('href').slice(1));
                }
            });

            $popup.removeClass("other");
            $popup.html(report);
            return { pointTo: ct };
        }
    });

    // A review comment can either be a review or a review reply
    function review_comment_edit_click(comment_form_id, comment_title_widget_id, comment_body_widget_id, comment_cancel_btn_id) {
        return function(e) {
            e.preventDefault();
            var $form = $('#' + comment_form_id),
                $review = $(this).closest('.review'),
                edit_url = $('a.permalink', $review).attr('href') + 'edit',
                $cancel = $('#' + comment_cancel_btn_id),
                title_selector;

            clearErrors($form);
            $form.off().hide();
            $('.review').not($review).show();
            $form.detach().insertAfter($review);

            if ($review.find('h4').length) {
                $form.find('fieldset h3').remove();
                title_selector = 'h4 > b';
                $form.find('fieldset').prepend($review.find('h3').clone());
            } else {
                title_selector = 'h3 > b';
            }

            $form.find('#' + comment_title_widget_id).val($review.find(title_selector).text());
            $form.find('#' + comment_body_widget_id).val($review.children('p.description').html().replace(/<br>/g, '\n'));
            $review.hide();
            $form.show();
            $window.resize();
            location.hash = '#' + comment_form_id;

            function done_edit() {
                clearErrors($form);
                $form.off().hide();
                $review.show();
                $cancel.off();
                $window.resize();
            }

            $cancel.click(_pd(done_edit));

            $form.submit(function (e) {
                e.preventDefault();
                $.ajax({
                    type: 'POST',
                    url: edit_url,
                    data: $form.serialize(),
                    success: function(response, status) {
                        clearErrors($form);
                        $review.find(title_selector).text($form.find('#' + comment_title_widget_id).val());
                        var rating = $form.find('.ratingwidget input:radio:checked').val();
                        $('.stars', $review).removeClass('stars-0 stars-1 stars-2 stars-3 stars-4 stars-5').addClass('stars-' + rating);
                        rating = $review.attr('data-rating', rating);
                        $review.children('p.description').html(
                            $form.find('#' + comment_body_widget_id).val()
                                .replace(/&/g,'&amp;')
                                .replace(/</g,'&lt;')
                                .replace(/>/g,'&gt;')
                                .replace(/\n/g, '<br>'));
                        done_edit();
                    },
                    error: function(xhr) {
                        var errors = JSON.parse(xhr.responseText);
                        populateErrors($form, errors);
                    },
                    dataType: 'json'
                });
                return false;
            });
        }
    }

    $('.primary').on('click', '.review-reply-edit',
        review_comment_edit_click(
            'review-reply-edit-form',
            'id_review_reply_title',
            'id_review_reply_body',
            'review-reply-edit-cancel'
        )
    );

    $('.primary').on('click', '.review-edit',
        review_comment_edit_click(
            'review-edit-form',
            'id_review_title',
            'id_review_body',
            'review-edit-cancel'
        )
    );

    $('.delete-review').click(function(e) {
        e.preventDefault();
        var target = $(e.target);
        $.post(target.attr('href'), function() {
            target.replaceWith(gettext('Marked for deletion'));
        });
        target.closest('.review').addClass('deleted');
    });

    $('select[name="rating"]').ratingwidget();

    $('#detail-review-link').click(_pd(function(e) {
        $('#review-add-box form')
            .append('<input type="hidden" name="detailed" value="1">').submit();
    }));
});
