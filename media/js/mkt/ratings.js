(function() {
    z.page.on('fragmentloaded', function() {
        setTimeout(function() {
            // Make sure the class got updated.
            if (!$('body.reviews').length) {
                return;
            }

            // Remove character counter on review field on mobile for now
            // (770661).
            if (z.capabilities.getDeviceType() != 'mobile') {
                initCharCount();
            }

            // Hijack <select> with stars.
            $('select[name="rating"]').ratingwidget();

            // Toggle rating breakdown.
            var $breakdown = $('.grouped-ratings');
            $('.average-rating').on('click', _pd(function() {
                $breakdown.toggle();
            }));
            $breakdown.on('click', _pd(function() {
                $breakdown.hide();
            }));

            // "More reviews" button.
            var $more = $('.load-more');
            $more.on('click', _pd(function() {
                var $new = $('#review-list .review:visible:last ~ .review:lt(5)');
                $new.show();
                if ($new.attr('id')) {
                    // Jump to top of new reviews.
                    window.location = '#' + $new.attr('id');
                }
                // If all the reviews are visible, fetch more.
                if (!$('#review-list .review:hidden').length) {
                    // TODO: Pull in more reviews.
                    //$.get($more.attr('href'), function(data) {
                    //});
                }
            }));

            // View reply.
            z.page.on('click', '.review .view-reply', _pd(function() {
                $(this).closest('.review').siblings('.reply').toggle();
            }));

            z.page.on('click', '.review .actions a', function(e) {
                var $this = $(this),
                    action = $this.data('action');
                if (!action) return;
                e.stopPropagation();
                e.preventDefault();
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
                }
            });

            var editTemplate = $('#edit-review-template').html(),
                replyTemplate = $('#reply-review-template').html(),
                flagOverlay = makeOrGetOverlay('flag-review'),
                reviewToFlag,
                flagURL;

            function flagReview(reviewEl) {
                flagURL = reviewEl.data('flag-url');
                reviewToFlag = reviewEl;
                flagOverlay.addClass('show');
            }

            flagOverlay.on('click', '.cancel', _pd(function() {
                flagOverlay.removeClass('show');
            })).on('click', '.menu a', _pd(function(e) {
                var flag = $(e.target).attr('href').slice(1),
                    actionEl = reviewToFlag.find('.actions .flag');
                flagOverlay.removeClass('show');
                actionEl.text(gettext('Sending report...'));
                $.ajax({type: 'POST',
                        url: flagURL,
                        data: {flag: flag},
                        success: function() {
                            actionEl.replaceWith(gettext('Flagged for review'));
                        },
                        error: function(){ },
                        dataType: 'json'
                });
            }));

            function deleteReview(reviewEl, action) {
                reviewEl.addClass('deleting');
                $.post(action);
                setTimeout(function() {
                    reviewEl.addClass('deleted');
                    if (reviewEl.hasClass('reply')) {
                        var $parent = reviewEl.prev('.review');
                        // If this was a reply, remove the "1 reply" link.
                        $parent.find('.view-reply').remove();
                        // Show "Reply" and "Delete" icons.
                        $parent.find('li.hidden').removeClass('hidden');
                    }
                    $('.notification.box').remove();
                    $('#page').prepend($('<section class="full notification-box">' +
                        '<div class="success"><h2>' +
                        gettext('Your review was successfully deleted!') +
                        '</h2></div></section>'));
                }, 500);
            }

            function handleReviewOverlay(overlay) {
                // Stuff that is common to Edit and Reply.
                var $form = overlay.find('form');

                // Remove character counter on review field on mobile for now
                // (770661).
                if (z.capabilities.getDeviceType() != 'mobile') {
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

            function editReview(reviewEl, action) {
                var overlay = makeOrGetOverlay('edit-review'),
                    body = reviewEl.find('.body').html().trim(),
                    rating = reviewEl.data('rating'),
                    action = reviewEl.closest('[data-edit-url]').data('edit-url');
                overlay.html(format(editTemplate, {action: action, body: body}));
                overlay.find('select[name="rating"]').ratingwidget();
                overlay.find(format('.ratingwidget [value="{0}"]', rating)).click();
                handleReviewOverlay(overlay);
            }

            function replyReview(reviewEl, action) {
                var overlay = makeOrGetOverlay('reply-review');
                overlay.html(format(replyTemplate, {action: action}));
                handleReviewOverlay(overlay);
                z.page.on('fragmentloaded', function() {
                    var newReview = '#' + reviewEl.attr('id');
                    // Replies are hidden by default, so show this one.
                    $(newReview).siblings('.reply').show();
                    // Jump to new review.
                    window.location = newReview;
                });
            }
        }, 0);
    });
})();
