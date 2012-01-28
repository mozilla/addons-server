var purchases = {
    init: function() {
        $("#contribute-why").popup("#contribute-more-info", {
            pointTo: "#contribute-more-info"
        });
        $('.price-wrapper a').live('click', _pd(function(event) {
            /* Update the currency from the drop down. */
            var $w = $('.price-wrapper');
            $(this).hide().next().show();
            $w.find('select').live('change', _pd(function(event) {
                $w.find('.price').text(
                    $w.find('option:selected').attr('data-display')
                );
            }));
        }));
        $('button.paypal').live('click', function(event) {
            var el = this,
                classes = 'ajax-loading loading-submit disabled',
                url = $(el).closest('form').attr('action'),
                data = { result_type: 'json' };
            if ($('.price-wrapper option:selected').length) {
                data.currency = $('.price-wrapper option:selected').val();
            }
            if ($(el).attr('data-realurl')) {
                data.realurl = encodeURIComponent($(el).attr('data-realurl'));
            }
            $(el).addClass(classes);
            $.ajax({
                type: 'POST',
                url: url,
                data: data,
                dataType: 'json',
                /* false so that the action is considered within bounds of
                 * user interaction and does not trigger the Firefox popup blocker.
                 */
                async: false,
                success: function(json) {
                    $(el).removeClass(classes);
                    $('.modal').trigger('close'); // Hide all modals
                    if (json.status == 'COMPLETED') {
                        modalFromURL($(el).attr('data-thanksurl'));
                    } else if (json.paykey) {
                        /* This is supposed to be a global */
                        //dgFlow = new PAYPAL.apps.DGFlow({expType:'mini'});
                        dgFlow = new PAYPAL.apps.DGFlow({clicked: el.id});
                        dgFlow.startFlow(json.url);
                    } else {
                        if (!$('#paypal-error').length) {
                            $(el).closest('div').append('<div id="paypal-error" class="popup"></div>');
                        }
                        $('#paypal-error').text(json.error).popup(el, {pointTo:el}).render();
                    }
                }
            });
            setTimeout(purchases.waiting_thanks, 1000);
            return false;
        });
        purchases.result();
    },
    waiting_thanks: function() {
        /* This is a workaround for
         * https://bugzilla.mozilla.org/show_bug.cgi?id=704534
         * placing a callback on modalFromURL results in an error
         * inside install.js. Instead we need trigger this from the
         * window before PayPal starts making iframes. */
        if ($('.paypal-thank-you').length) {
            purchases.thanks(window);
        } else {
            setTimeout(purchases.waiting_thanks, 1000);
        }
    },
    record: function($install, callback) {
        /* Record the install of the app. This is badly named because it
         * is not necessarily related to a purchase. */
        if ($install.attr('data-record-url')) {
            $.ajax({
                url: $install.attr('data-record-url'),
                dataType: 'json',
                type: 'POST',
                success: function(data) {
                    if(callback) {
                        callback.apply(this, [data.receipt]);
                    }
                }
            });
        }
    },
    result: function() {
        /* Process the paypal result page. This is the complete or cancel
         * page. Its main job is to close and take us back to the modal */
        if ($('#paypal-result').length) {
            var top_opener = window.top,
                top_dgFlow = top_opener.dgFlow;
            if (!top_dgFlow && top.opener && top.opener.top.dgFlow) {
                top_opener = top.opener.top;
                top_dgFlow = top_opener.dgFlow;
            }

            if (top_dgFlow !== null) {
                var thanks_url = $('#paypal-thanks').attr('href'),
                    error_url = $('#paypal-error').attr('href'),
                    frame_elm = window.frameElement;

                if (thanks_url) {
                    top_opener.modalFromURL(thanks_url);
                } else if (error_url) {
                    top_opener.modalFromURL(error_url);
                }
                top_dgFlow.closeFlow();

                /* Close this popup/lightbox.
                 * The PP flow has a return_url which points back to our site
                 * and gets opened in an iframe. That is what the logic below
                 * should close.
                 */
                if (frame_elm) {
                    frame_elm.close();
                } else {
                    top.close();
                }
            }
        }
    },
    reset: function($button, $modalish) {
        /* This resets the button for this add-on to show that it's been
         * purchased and do the work for add-ons or web apps. */
        var $install = $button.closest('.install');
        /* Only do something if it's premium. */
        if ($install.hasClass('premium')) {
            $install.removeClass('premium');
            $button.removeClass('premium');
            if ($install.hasClass('webapp')) {
                $button.unbind().attr('href', '#');
                $button.find('span').text(gettext('Install App'));
                $install.attr('data-manifest-url',
                              $('.trigger_app_install', $modalish).attr('data-manifest-url'));
                $install.removeAttr('data-start-purchase');
            }
            $install.installButton();
        }
    },
    find_button: function($body) {
        /* Find the relevant button to reset. */
        return $('.install[data-addon=' +
                 $('#addon_info', $body).attr('data-addon') +']:visible',
                 $body).find('a.button');
    },
    thanks: function(win) {
        /* Process the thanks modal that we show. */
        var $body = $(win.document).find('body'),
            $button = purchases.find_button($body);
        purchases.reset($button, $body);
        purchases.trigger($body);
    },
    trigger: function(modal) {
        /* Trigger the downloads or install when we show the thanks
         * or already purchased pages and wire up click triggers. */
        if ($('.trigger_download', modal).exists()) {
            z.installAddon($('.addon-title', modal).text(),
                           $('.trigger_download', modal).attr('href'));
        } else if ($('.trigger_app_install', modal).exists()) {
            var dest = $('.trigger_app_install', modal).attr('data-manifest-url'),
                receipt = $('.trigger_app_install', modal).attr('data-receipt');
            purchases.install_app(dest, receipt);
            $('.trigger_app_install', modal).click(_pd(function() {
                purchases.install_app(dest, $(this).attr('data-receipt'));
            }));
        }
    },
    install_app: function(url, receipt) {
        var data = {};
        if(receipt) {
            data.receipt = receipt;
        }
        apps.install(url, {data: data});
    }
};

$(document).ready(function() {
    purchases.init();
});

/**
 * Contributions Lightbox
 * TODO(jbalogh): save from amo2009.
 */
var contributions = {
    commentlimit: 255, // paypal-imposed comment length limit

    init: function() {
        // prepare overlay content
        var cb = $('#contribute-box');
        var contrib_limit = parseFloat($('#contrib-too-much').attr('data-max-amount'));
        cb.find('li label').click(function(e) {
            e.preventDefault();
            $(this).siblings(':radio').attr('checked', 'checked');
            $(this).children('input:text').focus();
        }).end()
        .find('input:text').keypress(function() {
            $(this).parent().siblings(':radio').attr('checked', 'checked');
        }).end()
        .find('textarea').keyup(function() {
            var txt = $(this).val(),
                limit = contributions.commentlimit,
                counter = $(this).siblings('.commentlen');
            if (txt.length > limit) {
                $(this).val(txt.substr(0, limit));
            }
            counter.text(limit - Math.min(txt.length, limit));
        }).keyup().end()
        .find('#contrib-too-much').hide().end()
        .find('#contrib-too-little').hide().end()
        .find('#contrib-not-entered').hide().end()
        .find('form').submit(function() {
            var contrib_type = $(this).find('input:checked').val();
            if (contrib_type == 'onetime') {
                var amt = $(this).find('input[name="'+contrib_type+'-amount"]').val();
                $(this).find('.error').hide();
                // parseFloat will catch everything except 1@, +amt will though
                if (isNaN(parseFloat(amt)) || ((+amt) != amt)) {
                    $(this).find('#contrib-not-entered').show();
                    return false;
                }
                if (amt > contrib_limit) {
                    $(this).find('#contrib-too-much').show();
                    return false;
                }
                if (parseFloat(amt) < 0.01) {
                    $(this).find('#contrib-too-little').show();
                    return false;
                }
            }
            var $self = $(this);
            $self.find('#contribute-actions').children().toggleClass('js-hidden');
            $.ajax({type: 'POST',
                url: $(this).attr('action') + '?result_type=json',
                data: $(this).serialize(),
                /* So popup blocker doesn't fire */
                async: false,
                success: function(json) {
                    if (json.status == 'COMPLETED') {
                        /* If pre approval returns, close show a thank you. */
                        $self.find('#paypal-complete').show();
                        $self.find('#contribute-actions').hide();
                    } else if (json.paykey) {
                        /* This is supposed to be a global */
                        //dgFlow = new PAYPAL.apps.DGFlow({expType:'mini'});
                        dgFlow = new PAYPAL.apps.DGFlow({clicked: 'contribute-box'});
                        dgFlow.startFlow(json.url);
                        $self.find('span.cancel a').click();
                    } else {
                        $self.find('#paypal-error').show();
                    }
                }
            });
            $self.find('#contribute-actions').children().toggleClass('js-hidden');
            return false;
        });

        // enable overlay; make sure we have the jqm package available.
        if (!cb.jqm) {
            return;
        }
        cb.jqm({
                overlay: 100,
                overlayClass: 'contrib-overlay',
                onShow: function(hash) {
                    // avoid bleeding-through form elements
                    if ($.browser.opera) {
                        this.inputs = $(':input:visible').css('visibility', 'hidden');
                    }
                    // clean up, then show box
                    hash.w.find('.error').hide();
                    hash.w
                        .find('input:text').val('').end()
                        .find('textarea').val('').keyup().end()
                        .find('input:radio:first').attr('checked', 'checked').end()
                        .fadeIn();

                },
                onHide: function(hash) {
                    if ($.browser.opera) {
                        this.inputs.css('visibility', 'visible');
                    }
                    hash.w.fadeOut();
                    hash.w.find('#paypal-complete').hide().end()
                          .find('#contribute-actions').show().end()
                          .find('.error').hide();
                    hash.o.remove();
                },
                trigger: '#contribute-button',
                toTop: true
            })
            .jqmAddClose(cb.find('.cancel a'));

        if (window.location.hash === '#contribute-confirm') {
            $('#contribute-button').click();
        }
    }

};
