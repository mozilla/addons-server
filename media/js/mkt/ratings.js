(function() {

    z.page.on('fragmentloaded', function() {
        flagOverlay = makeOrGetOverlay('flag-review');

        // Hijack <select> with stars.
        $('select[name="rating"]').ratingwidget();

        // Remove character counter on review field on mobile for now
        // (770661).
        if (!z.capabilities.mobile) {
            initCharCount();
        }
    });

    function getBody($body) {
        var body = $body.clone();
        // Get the inner *text* of the review body.
        body.find('.view-reply').remove();
        body.find('br').replaceWith('\n');
        return body.text().trim();
    }

    function handleReviewOverlay(overlay) {
        // Stuff that is common to Edit and Reply.
        var $form = overlay.find('form');

        // Remove character counter on review field on mobile for now
        // (770661).
        if (!z.capabilities.mobile) {
            initCharCount();
        }

        function validate() {
            var $error = overlay.find('.req-error'),
                $comment = overlay.find('textarea'),
                msg = $comment.val().strip(),
                $parent = $comment.closest('.simple-field'),
                $cc = overlay.find('.char-count'),
                valid = !$cc.hasClass('error') && msg;
            if (valid) {
                $parent.removeClass('error');
                $error.remove();
                overlay.off('submit.disable', 'form');
            } else {
                if (!$parent.hasClass('error')) {
                    $parent.addClass('error');
                }
                if (!msg && !$error.length) {
                    $(format('<div class="error req-error">{0}</div>',
                             gettext('This field is required.'))).insertBefore($cc);
                }
                overlay.on('submit.disable', 'form', false);
            }
            return valid;
        }

        overlay.addClass('show');

        overlay.on('submit', 'form', _pd(function(e) {
            // Trigger validation.
            if (validate(e)) {
                $.post($form.attr('action'), $form.serialize(), function() {
                    $(window).trigger('refreshfragment');
                });
            }
        })).on('click', '.cancel', _pd(function() {
            overlay.removeClass('show');
        })).on('change.comment keyup.comment', 'textarea', _.throttle(validate, 250));
    }

    function flagReview(reviewEl) {
        var overlay = makeOrGetOverlay('flag-review');
        overlay.addClass('show');
        overlay.one('click', '.cancel', _pd(function() {
            overlay.removeClass('show');
        })).one('click', '.menu a', _pd(function(e) {
            var flag = $(e.target).attr('href').slice(1),
                actionEl = reviewEl.find('.actions .flag');
            overlay.removeClass('show');
            actionEl.text(gettext('Sending report...'));
            $.ajax({
                type: 'POST',
                url: reviewEl.data('flag-url'),
                data: {flag: flag},
                success: function() {
                    actionEl.replaceWith(gettext('Flagged for review'));
                },
                error: function(){ },
                dataType: 'json'
            });
        }));
    }

    function deleteReview(reviewEl, action) {
        reviewEl.addClass('deleting');
        $.post(action);
        setTimeout(function() {
            reviewEl.addClass('deleted');
            // Change edit review button to submit review button.
            $('#add-edit-review').text(gettext('Write a Review'));
            $('#add-review').children().text(gettext('Write a Review'));
            if (reviewEl.hasClass('reply')) {
                var $parent = reviewEl.prev('.review');
                // If this was a reply, remove the "1 reply" link.
                $parent.find('.view-reply').remove();
                // Show "Reply" and "Delete" icons.
                $parent.find('li.hidden').removeClass('hidden');
            }
            $('.notification.box').remove();

            // If already existing Django message, replace message.
            var success = $('.success h2');
            if (success.length) {
                success.text(gettext('Your review was successfully deleted!'));
            } else {
                $('#page').prepend($('<section class="full notification-box">' +
                    '<div class="success"><h2>' +
                    gettext('Your review was successfully deleted!') +
                    '</h2></div></section>'));
            }
        }, 500);
    }

    function editReview(reviewEl, action) {
        var overlay = makeOrGetOverlay('edit-review'),
            rating = reviewEl.data('rating'),
            action = reviewEl.closest('[data-edit-url]').data('edit-url'),
            body = getBody(reviewEl.find('.body'));
        overlay.html(format($('#edit-review-template').html(),
                            {action: action, body: body}));
        if (reviewEl.hasClass('reply')) {
            overlay.find('select[name="rating"]').remove();
        } else {
            overlay.find('select[name="rating"]').ratingwidget();
            overlay.find(format('.ratingwidget [value="{0}"]', rating)).click();
        }
        handleReviewOverlay(overlay);
    }

    function replyReview(reviewEl, action) {
        var overlay = makeOrGetOverlay('reply-review');
        overlay.html(format($('#reply-review-template').html(),
                            {action: action}));
        handleReviewOverlay(overlay);
        z.page.on('fragmentloaded', function() {
            var newReview = '#' + reviewEl.attr('id');
            // Replies are hidden by default, so show this one.
            $(newReview).siblings('.reply').show();
            // Jump to new review.
            window.location = newReview;
        });
    }

    function editReply(reviewEl, action) {
        var overlay = makeOrGetOverlay('edit-reply-review'),
            body = getBody(reviewEl.find('.body'));
        overlay.html(format($('#edit-reply-review-template').html(),
                            {action: action, body: body}));
        handleReviewOverlay(overlay);
    }

    // Toggle rating breakdown (on listing page only, not detail page).
    z.page.on('click', '.average-rating-listing', _pd(function() {
        $('.grouped-ratings').toggle();
    }));
    z.page.on('click', '.grouped-ratings-listing', _pd(function() {
        $('.grouped-ratings').hide();
    }));

    z.page.on('click', '.review .actions a', _pd(function(e) {
        var $this = $(this),
            action = $this.data('action');
        if (!action) return;
        var $review = $this.closest('.review');
        switch (action) {
            case 'delete':
                deleteReview($review, $this.attr('href'));
                break;
            case 'edit':
                editReview($review);
                break;
            case 'report':
                flagReview($review);
                break;
            case 'reply':
                replyReview($review, $this.attr('href'));
                break;
            case 'edit-reply':
                editReply($review, $this.attr('href'));
                break;
        }
    }));

    // View reply.
    z.page.on('click', '.review .view-reply', _pd(function() {
        $(this).closest('.review').next('.replies').find('.reply').toggle();
    }));

})();
