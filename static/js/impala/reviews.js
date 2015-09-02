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

            $popup.delegate('li a', 'click', function(e) {
                e.preventDefault();
                var el = $(e.target);
                if (el.attr('href') == '#review_flag_reason_other') {
                    $popup.addClass('other')
                          .delegate('form', 'submit', function(e) {
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

    $('.primary').delegate('.review-edit', 'click', function(e) {
        e.preventDefault();
        var $form = $('#review-edit-form'),
            $review = $(this).closest('.review'),
            rating = $review.attr('data-rating'),
            edit_url = $('a.permalink', $review).attr('href') + 'edit',
            $cancel = $('#review-edit-cancel'),
            title_selector;

        clearErrors($form);
        $form.unbind().hide();
        $('.review').not($review).show();
        $form.detach().insertAfter($review);

        if ($review.find('h4').length) {
            $form.find('fieldset h3').remove();
            title_selector = 'h4 > b';
            $form.find('fieldset').prepend($review.find('h3').clone());
        } else {
            title_selector = 'h3 > b';
        }

        $form.find('#id_title').val($review.find(title_selector).text());

        if (rating == "") {
            // Replies do not have ratings, so do not show the label or widget for them
            $("label[for='id_rating']").hide();
            $form.find('.ratingwidget').hide();
        } else {
            // Fake a click on the right star rating for reviews that already have one.
            $("label[for='id_rating']").show();
            $form.find('.ratingwidget').show();
            $form.find('.ratingwidget input:radio[value=' + rating + ']').click();
        }
        $form.find('#id_body').val($review.children('p.description').html().replace(/<br>/g, '\n'));
        $review.hide();
        $form.show();
        $window.resize();
        location.hash = '#review-edit-form';

        function done_edit() {
            clearErrors($form);
            $form.unbind().hide();
            $review.show();
            $cancel.unbind();
            $window.resize();
        }

        $cancel.click(_pd(done_edit));

        $form.submit(function (e) {
            e.preventDefault();
            $.ajax({type: 'POST',
                url: edit_url,
                data: $form.serialize(),
                success: function(response, status) {
                    clearErrors($form);
                    $review.find(title_selector).text($form.find('#id_title').val());
                    var rating = $form.find('.ratingwidget input:radio:checked').val();
                    $('.stars', $review).removeClass('stars-0 stars-1 stars-2 stars-3 stars-4 stars-5').addClass('stars-' + rating);
                    rating = $review.attr('data-rating', rating);
                    $review.children('p.description').html(
                        $form.find('#id_body').val()
                             .replace(/&/g,'&amp;')
                             .replace(/</g,'&lt;')
                             .replace(/>/g,'&gt;')
                             .replace(/\n/g, '<br>'));
                    done_edit();
                },
                error: function(xhr) {
                    var errors = $.parseJSON(xhr.responseText);
                    populateErrors($form, errors);
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

    $('select[name="rating"]').ratingwidget();

    $('#detail-review-link').click(_pd(function(e) {
        $('#review-add-box form')
            .append('<input type="hidden" name="detailed" value="1">').submit();
    }));
});
