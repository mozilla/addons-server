(function() {

    // Review/reply template.
    var reviewTemplate = getTemplate($('#review-template'));
    var reviewWithReply;

    var alwaysUseCharCounter = true;

    z.page.on('fragmentloaded', function() {
        // Hijack <select> with stars.
        $('select[name="rating"]').ratingwidget();

        // Remove character counter on review field on mobile for now
        // (770661).
        if (alwaysUseCharCounter || !z.capabilities.mobile) {
            initCharCount();
        }

        // Show add review modal on app/app_slug/reviews/add for desktop.
        if ($('.reviews.add-review').length) {
            addOrEditYourReview($('#add-first-review'));
        }

        if (reviewWithReply && reviewWithReply.length) {
            var review = $('#' + reviewWithReply.attr('id'));
            review.siblings('.reply').show();
            $('html, body').scrollTo(review);
        }
    });

    // Returns the review body text or '' if the supplied element is not found.
    function getBody($body) {
        var body = $body.clone();
        // Get the inner *text* of the review body.
        body.find('.view-reply').remove();
        body.find('br').replaceWith('\n');
        // `.text()` returns the unescaped text content, so re-escape it.
        return body.text().trim()
                   .replace(/&/g,'&amp;')
                   .replace(/</g,'&lt;')
                   .replace(/>/g,'&gt;');
    }

    function handleReviewOverlay(overlay) {
        // Stuff that is common to Edit and Reply.
        var $form = overlay.find('form');

        // Remove character counter on review field on mobile for now
        // (770661).
        if (alwaysUseCharCounter || !z.capabilities.mobile) {
            initCharCount(overlay);
        }

        overlay.addClass('show');

        overlay.on('submit', 'form', function(e) {
            overlay.removeClass('show');
            // Form submission is handled by POST hijacking.
        }).on('click', '.cancel', _pd(function() {
            overlay.removeClass('show');
        }));
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
            $.post(
                reviewEl.data('flag-url'),
                {flag: flag}
            ).done(function() {
                actionEl.replaceWith(gettext('Flagged for review'));
            });
        }));
    }

    function deleteReview(reviewEl, action) {
        reviewEl.addClass('deleting');
        $.post(action);
        setTimeout(function() {
            reviewEl.addClass('deleted');
            if (reviewEl.hasClass('reply')) {
                var $parent = reviewEl.closest('.replies').prev('.review');
                // If this was a reply, remove the "1 reply" link.
                $parent.find('.view-reply').remove();
                $parent.find('ul.actions li.reply').removeClass('hidden');

                reviewEl.parent().remove();
            } else {
                // Change edit review button to submit review button.
                $('#add-edit-review').text(gettext('Write a Review'));
                $('#add-review').children().text(gettext('Write a Review'));
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

    // Edit review on the review listing page.
    function editReview(reviewEl) {
        var overlay = makeOrGetOverlay('edit-review'),
            rating = reviewEl.data('rating'),
            action = reviewEl.closest('[data-edit-url]').data('edit-url'),
            body = getBody(reviewEl.find('.body'));
        overlay.html(reviewTemplate({title: gettext('Edit Review'),
                                     action: action, body: body}));
        if (reviewEl.hasClass('reply')) {
            overlay.find('select[name="rating"]').remove();
        } else {
            if (z.body.hasClass('desktop')) {
                overlay.find('select[name="rating"]').ratingwidget('large');
            } else {
                overlay.find('select[name="rating"]').ratingwidget();
            }
            overlay.find(format('.ratingwidget [value="{0}"]', rating)).click();
        }
        handleReviewOverlay(overlay);
    }

    // This gets used when you're not editing a review on the review list page.
    function addOrEditYourReview($senderEl) {
        var overlay = makeOrGetOverlay('edit-review'),
            rating = $senderEl.data('rating'),
            title = gettext('Write a Review'),
            body = getBody($('#current-review')),
            action = $senderEl.data('href');

        if (rating > 0) {
            title = gettext('Edit Your Review');
        }

        overlay.html(reviewTemplate({title: title, action: action,
                                     body: body}));

        overlay.find('select[name="rating"]').ratingwidget('large');
        overlay.find(format('.ratingwidget [value="{0}"]', rating)).click();
        handleReviewOverlay(overlay);
    }

    function replyReview(reviewEl, action, isNewReview) {
        var overlay = makeOrGetOverlay('edit-review'),
            title = gettext('Reply Review'),
            body = '';

        if (!isNewReview) {
            title = gettext('Edit Reply');
            body = getBody(reviewEl.find('.body'));
        }

        overlay.html(reviewTemplate({title: title, action: action,
                                     body: body}));
        overlay.addClass('reply');
        handleReviewOverlay(overlay);
    }

    // Toggle rating breakdown (on listing page only, not detail page).
    z.page.on('click', '.average-rating-listing', _pd(function() {
        $('.grouped-ratings').toggle();
    })).on('click', '.grouped-ratings-listing', _pd(function() {
        $('.grouped-ratings').hide();
    }));

    z.page.on('click', '.review .actions a, #add-first-review[data-href]', _pd(function(e) {
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
            case 'add-or-edit':
                addOrEditYourReview($this);
                break;
            case 'report':
                flagReview($review);
                break;
            case 'reply':
                replyReview($review, $this.attr('href'), true);
                break;
            case 'edit-reply':
                replyReview($review, $this.attr('href'));
                break;
        }
    }));

    // View reply.
    z.page.on('click', '.review .view-reply', _pd(function() {
        $(this).closest('.review').next('.replies').find('.reply').toggle();
    }));
})();
