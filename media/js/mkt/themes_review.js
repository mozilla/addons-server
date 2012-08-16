(function($) {
    /* jQuery.ScrollTo by Ariel Flesler */
    $.fn.scrollTo = function(opts) {
        if (!this.length) return this;
        opts = $.extend({
            duration: 500,
            marginTop: 0,
            complete: undefined
        }, opts || { });
        var top = this.offset().top - opts.marginTop;
        $('html, body').animate({ 'scrollTop': top }, opts.duration, undefined, opts.complete);
        return this;
    };
})(jQuery);


(function($) {
    $.fn.themeQueue = function() {
        return this.each(function() {
            var queue = this;
            var currentTheme = 0;
            var cacheQueueHeight;
            var maxLocks = parseInt($('.theme-queue').data('max-locks'), 10);
            var moreUrl = $('.theme-queue').data('more-url');
            var actionConstants = $('#action-constants').data('actions');

            var themesList = $('div.theme', queue);
            var themes = themesList.map(function() {
                return {
                    element: this,
                    top: 0
                };
            }).get();

            function nthTheme(i) {
                return themesList[i];
            }

            $(window).scroll(_.throttle(function() {
                updateMetrics();
                var i = findCurrentTheme();
                if (i >= 0 && i != currentTheme) {
                    switchTheme(findCurrentTheme());
                }
                // Undo sidebar-truncation fix in goToTheme if user goes
                // into free-scrolling mode.
                if (i == 0) {
                    $('.sidebar').removeClass('lineup');
                }
            }, 250));

            $(document).keyup(function(e) {
                if (!$(queue).hasClass('shortcuts')) return;

                // Ignore key-bindings when textarea focused.
                if (fieldFocused(e) && e.which != z.keys.ENTER) return;

                // For using Enter to submit textareas.
                if (e.which == z.keys.ENTER && z.keys.ENTER in keymap) {
                    keymap[z.keys.ENTER]();
                }

                var key = String.fromCharCode(e.which).toLowerCase();
                if (!key in keymap) return;

                var action = keymap[key];
                if (action && !e.ctrlKey && !e.altKey && !e.metaKey) {
                    themeActions[action[0]](currentTheme, action[1]);
                }
            });

            // Pressing Enter in text field doesn't add carriage return.
            $('textarea').keypress(function(e) {
                if (e.keyCode == z.keys.ENTER) {
                    e.preventDefault();
                }
            });

            $('.theme', queue).removeClass('active');
            updateMetrics();
            switchTheme(findCurrentTheme());

            function updateMetrics() {
                var queueHeight = $(queue).height();
                if (queueHeight === cacheQueueHeight) return;
                cacheQueueHeight = queueHeight;

                $.each(themes, function(i, obj) {
                    var elem = $(obj.element);
                    obj.top = elem.offset().top + elem.outerHeight()/2;
                });
            }

            function getThemeParent(elem) {
                // Given an element (like an approve button),
                // return the theme for which it is related to.
                return $(elem).closest('.theme').data('id');
            }

            function goToTheme(i, delay, duration) {
                delay = delay || 0;
                duration = duration || 250;
                setTimeout(function() {
                    if (i >= 0 && i < themes.length) {
                        $(themes[i].element).scrollTo({ duration: duration, marginTop: 20 });
                        // Lines up the sidebar with the theme to avoid
                        // truncation with the footer.
                        if (i > 0) {
                            // Don't line up first one because header gets in
                            // the way.
                            $('.sidebar').addClass('lineup');
                        }
                    }
                }, delay);
                $('.rq-dropdown').hide();
            }

            function switchTheme(i) {
                $(themes[currentTheme].element).removeClass('active');
                $(themes[i].element).addClass('active');
                currentTheme = i;
            }

            function findCurrentTheme() {
                // Uses location of the window within the page to determine
                // which theme we're currently looking at.
                var pageTop = $(window).scrollTop();
                if (pageTop <= themes[currentTheme].top) {
                    for (var i = currentTheme - 1; i >= 0; i--) {
                        if (themes[i].top < pageTop) {
                            break;
                        }
                    }
                    return i+1;
                } else {
                    for (var i = currentTheme; i < themes.length; i++) {
                        // Scroll down the themes until we find a theme
                        // that is at the top of our page. That is our current
                        // theme.
                        if (pageTop <= themes[i].top) {
                            return i;
                        }
                    }
                }
            }

            var ajaxLockFlag = 0;
            function moreThemes() {
                // Don't do anything if max locks or currently making request
                // or not all themes reviewed. Using an exposed DOM element to
                // hold data, but we don't really care if they try to tamper
                // with that.
                var themeCount = $('#total').text();
                if (themesList.length >= maxLocks || ajaxLockFlag ||
                    $('#reviewed-count').text() != themeCount) {
                    return;
                }
                ajaxLockFlag = 1;
                var i = parseInt(themeCount, 10);

                $('button#more').html(gettext('Loading&hellip;'));
                $.get(moreUrl, function(data) {
                    // Update total.
                    $('#total').text(data.count);

                    // Insert the themes into the DOM.
                    $('#theme-queue-form').append(data.html);
                    themesList = $('div.theme', queue);
                    themes = themesList.map(function() {
                        return {
                            element: this,
                            top: 0
                        };
                    }).get();
                    $('.zoombox').zoomBox();

                    // Correct the new Django forms' prefixes
                    // (id_form-x-field) to play well with the formset.
                    var $input;
                    var newThemes = themesList.slice(themeCount, themesList.length);
                    $(newThemes).each(function(index, theme) {
                        $('input', theme).each(function(index, input) {
                            $input = $(input);
                            $input.attr('id', $input.attr('id').replace(/-\d-/, '-' + themeCount + '-'));
                            $input.attr('name', $input.attr('name').replace(/-\d-/, '-' + themeCount + '-'));
                        });
                        themeCount++;
                    });

                    // Update metadata on Django management form for
                    // formset.
                    updateTotalForms('form', 1);
                    $('#id_form-INITIAL_FORMS').val(themeCount.toString());

                    goToTheme(i, 250);
                    ajaxLockFlag = 0;

                    $('button#more').toggle().text(gettext('Load More')).unbind('click');
                });
            }

            var keymap = {
                j: ['next', null],
                k: ['prev', null],
                a: ['approve', null],
                r: ['reject_reason', null],
                d: ['duplicate', null],
                f: ['flag', null],
                m: ['moreinfo', null]
            };
            keymap[0] = ['other_reject_reason', 0];
            for (var j =1; j <= 9; j++) {
                keymap[j] = ['reject', j];
            }

            function setReviewed(i, text) {
                $(nthTheme(i)).addClass('reviewed');
                $('.status', themes[i].element).addClass('reviewed').text(text);
                $('#reviewed-count').text($('div.theme.reviewed').length);
                if ($(queue).hasClass('advance')) {
                    goToTheme(i+1, 250);
                } else {
                    delete keymap[z.keys.ENTER];
                    $('.rq-dropdown').hide();
                }
                if ($('#reviewed-count').text() == $('#total').text() &&
                    themesList.length < maxLocks) {
                    $('button#more').toggle().click(moreThemes);
                }
            }

            var isRejecting = false;
            $('li.reject_reason').click(function(e) {
                if (isRejecting) {
                    var i = getThemeParent(e.currentTarget);
                    var rejectId = $(this).data('id');
                    if (rejectId == 0) {
                        themeActions.other_reject_reason(i);
                    } else {
                        themeActions.reject(i, rejectId);
                    }
                }
            });

            var themeActions = {
                next: function (i) { goToTheme(i+1); },
                prev: function (i) { goToTheme(i-1); },

                approve: function (i) {
                    $('input.action', nthTheme(i)).val(actionConstants.approve);
                    setReviewed(i, gettext('Approved'));
                },

                reject_reason: function (i) {
                    // Open up dropdown of rejection reasons and set up
                    // key and click-bindings for choosing a reason. This
                    // function does not actually do the rejecting as the
                    // rejecting is only done once a reason is supplied.
                    $('.rq-dropdown:not(.reject-reason-dropdown)').hide();
                    $('.reject-reason-dropdown', nthTheme(i)).toggle();
                    isRejecting = true;
                },

                other_reject_reason: function(i) {
                    if (!isRejecting) { return; }

                    // Open text area to enter in a custom rejection reason.
                    $('.rq-dropdown:not(.reject-reason-detail-dropdown)').hide();
                    $('.reject-reason-detail-dropdown', nthTheme(i)).toggle();
                    var textArea = $('.reject-reason-detail-dropdown textarea', nthTheme(i)).focus();

                    // Submit link/URL of the duplicate.
                    var submit = function() {
                        if (textArea.val()) {
                            $('input.comment', nthTheme(i)).val(textArea.val());
                            textArea.blur();
                            themeActions.reject(i, 0);
                        } else {
                            $('.reject-reason-detail-dropdown .error-required').show();
                        }
                    };
                    keymap[z.keys.ENTER] = submit;
                    $('.reject-reason-detail-dropdown button').click(_pd(submit));
                },

                reject: function(i, rejectId) {
                    if (!isRejecting) { return; }

                    // Given the rejection reason, does the actual rejection of
                    // the Theme.
                    $('input.action', nthTheme(i)).val(actionConstants.reject);
                    $('input.reject-reason', nthTheme(i)).val(rejectId);
                    setReviewed(i, gettext('Rejected'));
                    isRejecting = false;
                },

                duplicate: function(i) {
                    // Open up dropdown to enter ID/URL of duplicate.
                    $('.rq-dropdown:not(.duplicate-dropdown)').hide();
                    $('.duplicate-dropdown', nthTheme(i)).toggle();
                    var textArea = $('.duplicate-dropdown textarea', nthTheme(i)).focus();

                    // Submit link/URL of the duplicate.
                    var submit = function() {
                        if (textArea.val()) {
                            $('input.action', nthTheme(i)).val(actionConstants.duplicate);
                            $('input.comment', nthTheme(i)).val(textArea.val());
                            textArea.blur();
                            setReviewed(i, gettext('Duplicate'));
                        } else {
                            $('.duplicate-dropdown .error-required').show();
                        }
                    };
                    keymap[z.keys.ENTER] = submit;
                    $('.duplicate-dropdown button').click(_pd(submit));
                },

                flag: function(i) {
                    // Open up dropdown to enter reason for flagging.
                    $('.rq-dropdown:not(.flag-dropdown)').hide();
                    $('.flag-dropdown', nthTheme(i)).toggle();
                    var textArea = $('.flag-dropdown textarea', nthTheme(i)).focus();

                    // Submit link/URL of the flag.
                    var submit = function() {
                        if (textArea.val()) {
                            $('input.action', nthTheme(i)).val(actionConstants.flag);
                            $('input.comment', nthTheme(i)).val(textArea.val());
                            textArea.blur();
                            setReviewed(i, gettext('Flagged'));
                        } else {
                            $('.flag-dropdown .error-required').show();
                        }
                    };
                    keymap[z.keys.ENTER] = submit;
                    $('.flag-dropdown button').click(_pd(submit));
                },

                moreinfo: function(i) {
                    // Open up dropdown to enter ID/URL of moreinfo.
                    $('.rq-dropdown:not(.moreinfo-dropdown)').hide();
                    $('.moreinfo-dropdown', nthTheme(i)).toggle();
                    var textArea = $('.moreinfo-dropdown textarea', nthTheme(i)).focus();

                    // Submit link/URL of the moreinfo.
                    var submit = function() {
                        if (textArea.val()) {
                            $('input.action', nthTheme(i)).val(actionConstants.moreinfo);
                            $('input.comment', nthTheme(i)).val(textArea.val());
                            textArea.blur();
                            setReviewed(i, gettext('Requested Info'));
                        } else {
                            $('.moreinfo-dropdown .error-required').show();
                        }
                    };
                    keymap[z.keys.ENTER] = submit;
                    $('.moreinfo-dropdown button').click(_pd(submit));
                }
            };

            $(document).delegate('button.approve', 'click', _pd(function(e) {
                themeActions.approve(getThemeParent(e.currentTarget));
            }))
            .delegate('button.reject', 'click', _pd(function(e) {
                themeActions.reject_reason(getThemeParent(e.currentTarget));
            }))
            .delegate('button.duplicate', 'click', _pd(function(e) {
                themeActions.duplicate(getThemeParent(e.currentTarget));
            }))
            .delegate('button.flag', 'click', _pd(function(e) {
                themeActions.flag(getThemeParent(e.currentTarget));
            }))
            .delegate('button.moreinfo', 'click', _pd(function(e) {
                themeActions.moreinfo(getThemeParent(e.currentTarget));
            }));
        });
    };

    $.fn.themeQueueOptions = function(queueSelector) {
        return this.each(function() {
            var self = this;

            $('input', self).click(onChange);
            $('select', self).change(onChange);
            onChange();

            function onChange(e) {
                var category = $('#rq-category', self).val();
                var advance = $('#rq-advance:checked', self).val();
                var shortcuts = $('#rq-shortcuts:checked', self).val();

                $(queueSelector)
                    .toggleClass('advance', !!advance)
                    .toggleClass('shortcuts', !!shortcuts);
            }
        });
    };
})(jQuery);


$(document).ready(function() {
    $('.zoombox').zoomBox();
    $('.theme-queue').themeQueue();
    $('.sidebar').themeQueueOptions('.theme-queue');
    $('button#commit').click(_pd(function(e) {
        $('#theme-queue-form').submit();
    }));
});
