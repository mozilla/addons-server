/*
 * addonUploader()
 * Extends fileUploader()
 * Also, this can only be used once per page.  Or you'll have lots of issues with closures and scope :)
 */

(function($) {
    /* Normalize results */
    function getErrors(results) {
      var errors = [];

      if(results.validation.messages) {
          $.each(results.validation.messages, function(i, v){
            if(v.type == "error") {
              errors.push(v.message);
            }
          });
      }
      return errors;
    }

    function checkTimeout(validation) {
        var timeout_id = ['validator', 'unexpected_exception', 'validation_timeout'];
        return _.some(validation.messages, function(message) {
            return _.isEqual(message.id, timeout_id);
        });
    }

    $.fn.addonUploader = function( options ) {
        var settings = {
            'filetypes': ['zip', 'xpi', 'crx', 'jar', 'xml'],
            'getErrors': getErrors,
            'cancel': $(),
            'maxSize': 200 * 1024 * 1024 // 200M
        };

        if (options) {
            $.extend( settings, options );
        }

        function parseErrorsFromJson(response, statusCode) {
            var json, errors = [];
            try {
                json = JSON.parse(response);
            } catch(err) {
                errors = [gettext("There was a problem contacting the server.")];
                try {
                    Raven.captureMessage('Error parsing upload status JSON.', {
                        extra: {
                            status_code: statusCode,
                            content: response,
                        },
                    });
                } catch (e) {
                    console.log(e);
                }
            }
            if (!errors.length) {
                errors = settings.getErrors(json);
            }
            return {
                errors: errors,
                json: json
            };
        }

        return $(this).each(function(){
            var $upload_field = $(this),
                file = {};

            /* Add some UI */

            var ui_parent = $('<div>', {'class': 'invisible-upload prominent cta', 'id': 'upload-file-widget'}),
                ui_link = $('<a>', {'class': 'button prominent', 'href': '#', 'text': gettext('Select a file...')}),
                ui_details = $('<div>', {'class': 'upload-details', 'text': gettext('Your add-on should end with .zip, .xpi, .crx, .jar or .xml')});

            $upload_field.prop('disabled', false);
            $upload_field.wrap(ui_parent);
            $upload_field.before(ui_link);
            $upload_field.parent().after(ui_details);

            if (!z.capabilities.fileAPI) {
                $('.invisible-upload').addClass('legacy');
            }

            /* Get things started */

            var upload_box, upload_title, upload_progress_outside, upload_progress_inside,
                upload_status, upload_results, upload_status_percent, upload_status_progress,
                upload_status_cancel;

            $upload_field.fileUploader(settings);

            function updateStatus(percentage, size) {
                if (percentage) {
                    upload_status.show();
                    p = Math.round(percentage);
                    size = (p / 100) * size;

                    // L10n: {0} is the percent of the file that has been uploaded.
                    upload_status_percent.text(format(gettext('{0}% complete'), [p]));

                    // L10n: "{bytes uploaded} of {total filesize}".
                    upload_status_progress.text(format(gettext('{0} of {1}'),
                                [fileSizeFormat(size), fileSizeFormat(file.size)]));
                }
            }

            /* Bind the events */

            $upload_field.on("upload_start", function(e, _file){
                file = _file;

                /* Remove old upload box */
                if(upload_box) {
                    upload_box.remove();
                }

                /* Remove old errors */
                $upload_field.closest('form').find('.errorlist').remove();

                /* Set defaults */
                $('#id_is_manual_review').prop('checked', false);

                /* Don't allow submitting */
                // The create theme wizard button is actually a link,
                // so it's pointless to set the disabled property on it,
                // instead add the special "concealed" class.
                $('.addon-create-theme-section .button').addClass('concealed');
                $('.addon-upload-dependant').prop('disabled', true);
                $('.addon-upload-failure-dependant').prop({'disabled': true,
                                                           'checked': false});

                /* Create elements */
                upload_title = $('<strong>', {'id': 'upload-status-text'});
                upload_progress_outside = $('<div>', {'id': 'upload-status-bar'});
                upload_progress_inside = $('<div>').css('width', 0);
                upload_status = $('<div>', {'id': 'uploadstatus'}).hide();
                upload_status_percent = $('<span>');
                upload_status_progress = $('<span>');
                upload_status_cancel_a = $('<a>', {'href': '#', 'text': gettext('Cancel')});
                upload_status_cancel = $('<span> &middot; </span>');
                upload_results = $('<div>', {'id': 'upload-status-results'});
                upload_box = $("<div>", {'class': 'upload-status ajax-loading'}).hide();

                /* Set up structure */
                upload_box.append(upload_title);
                upload_progress_outside.append(upload_progress_inside);
                upload_box.append(upload_progress_outside);
                upload_status.append(upload_status_percent);
                upload_status.append(" <span> &middot; </span> ");
                upload_status.append(upload_status_progress);
                upload_status.append(upload_status_cancel);
                upload_status_cancel.append(upload_status_cancel_a);

                upload_box.append(upload_status);
                upload_box.append(upload_results);

                /* Add to the dom and clean up upload_field */
                ui_details.after(upload_box);

                /* It's showtime! */
                upload_title.html(format(gettext('Uploading {0}'), [escape_(file.name)]));
                upload_box.show();

                upload_box.addClass("ajax-loading");

                upload_status_cancel_a.click(_pd(function(){
                    $upload_field.trigger("upload_action_abort");
                }));
            });

            $upload_field.on("upload_progress", function(e, file, pct) {
                upload_progress_inside.animate({'width': pct + '%'},
                    {duration: 300, step:function(i){ updateStatus(i, file.size); } });
            });

            $upload_field.on("upload_errors", function(e, file, errors, results){
                var all_errors = $.extend([], errors);  // be nice to other handlers
                upload_progress_inside.stop().css({'width': '100%'});

                if ($('input#id_upload').val()) {
                    $('.addon-upload-failure-dependant').prop({'disabled': false,
                                                               'checked': false});
                }

                $('.addon-create-theme-section .button').removeClass('concealed');
                $upload_field.val("").prop('disabled', false);
                $upload_field.trigger("reenable_uploader");

                upload_title.html(format(gettext('Error with {0}'), [escape_(file.name)]));

                upload_progress_outside.attr('class', 'bar-fail');
                upload_progress_inside.fadeOut();

                if (results && results.processed_by_addons_linter) {
                    $("<a>").text(gettext('We have enabled a new linter to process your Add-on. Please make sure to report any issues on GitHub'))
                            .attr('href', 'https://github.com/mozilla/addons-linter/')
                            .attr('class', 'addons-linter-info')
                            .attr('target', '_blank')
                            .attr('rel', 'noopener noreferrer')
                            .appendTo(upload_results);
                }

                var error_message = format(ngettext(
                        "Your add-on failed validation with {0} error.",
                        "Your add-on failed validation with {0} errors.",
                        all_errors.length), [all_errors.length]);

                $("<strong>").text(error_message).appendTo(upload_results);

                var errors_ul = $('<ul>', {'id': 'upload_errors'});

                $.each(all_errors.splice(0, 5), function(i, error) {
                    errors_ul.append($("<li>", {'html': error }));
                });

                if(all_errors.length > 0) {
                    var message = format(ngettext('&hellip;and {0} more',
                                                  '&hellip;and {0} more',
                                                  all_errors.length), [all_errors.length]);
                    errors_ul.append($('<li>', {'html': message}));
                }

                upload_results.append(errors_ul).addClass('status-fail');

                if (results && results.full_report_url) {
                    // There might not be a link to the full report
                    // if we get an early error like unsupported type.
                    upload_results.append($("<a>", {'href': results.full_report_url,
                                                    'class': 'view-more',
                                                    'target': '_blank',
                                                    'rel': 'noopener noreferrer',
                                                    'text': gettext('See full validation report')}));
                }
            });

            $upload_field.on("upload_finished", function() {
                upload_box.removeClass("ajax-loading");
                upload_status_cancel.remove();
            });

            $upload_field.on("upload_success", function(e, file, results) {
                upload_title.html(format(gettext('Validating {0}'), [escape_(file.name)]));

                var animateArgs = {duration: 300, step:function(i){ updateStatus(i, file.size); }, complete: function() {
                    $upload_field.trigger("upload_success_results", [file, results]);
                }};

                upload_progress_inside.animate({'width': '100%'}, animateArgs);
            });

            $upload_field.on("upload_onreadystatechange", function(e, file, xhr, aborted) {
                var errors = [],
                    $form = $upload_field.closest('form'),
                    json = {},
                    errOb;
                if (xhr.readyState == 4 && xhr.responseText &&
                        (xhr.status == 200 ||
                         xhr.status == 304 ||
                         xhr.status == 400)) {

                    errOb = parseErrorsFromJson(xhr.responseText, xhr.status);
                    errors = errOb.errors;
                    json = errOb.json;

                    if (json && json.upload && (
                          !json.validation ||
                          !_.some(_.pluck(json.validation.messages, 'fatal')))) {
                        $form.find('input#id_upload').val(json.upload);
                    }
                    if(errors.length > 0) {
                        $upload_field.trigger("upload_errors", [file, errors, json]);
                    } else {
                        $upload_field.trigger("upload_success", [file, json]);
                        $upload_field.trigger("upload_progress", [file, 100]);
                    }
                    $upload_field.trigger("upload_finished", [file]);

                } else if(xhr.readyState == 4 && !aborted) {
                    if (xhr.status == 413) {
                        errors.push(
                            format(
                                gettext("Your add-on exceeds the maximum size of {0}."),
                                [fileSizeFormat(settings.maxSize)]));
                    } else {
                        // L10n: first argument is an HTTP status code
                        errors.push(
                            format(
                                gettext("Received an empty response from the server; status: {0}"),
                                [xhr.status]));
                    }

                    $upload_field.trigger("upload_errors", [file, errors]);
                }
            });

            $('#id_admin_override_validation').addClass('addon-upload-failure-dependant')
                .change(function () {
                    if ($(this).prop('checked')) {
                        // TODO: Disable these when unchecked, or bounce
                        // between upload_errors and upload_success
                        // handlers? I think the latter would mostly be a
                        // bad idea, since failed validation might give us
                        // the wrong results, and admins overriding
                        // validation might need some additional leeway.
                        $('.platform:hidden').show();
                        $('.platform label').removeClass('platform-disabled');
                        $('.addon-upload-dependant').prop('disabled', false);
                    } else {
                        $('.addon-upload-dependant').prop('disabled', true);
                    }
                });
            $('.addon-upload-failure-dependant').prop('disabled', true);

            var $newForm = $('.new-addon-file');
            var $channelChoice = $('input[name="channel"]');

            function isUnlisted() {
              // True if there's radio input with 'name="channel"' with 'value="unlisted"' checked, or a
              // 'addon-is-listed' data on the new file form that is true.
              return ((typeof($newForm.data('addon-is-listed')) != 'undefined' && !$newForm.data('addon-is-listed')) ||
                      ($channelChoice.length && $('input[name="channel"]:checked').val() != 'listed'));
            }

            // is_unlisted checkbox: should the add-on be listed on AMO? If not,
            // change the addon upload button's data-upload-url.
            // If this add-on is unlisted, then tell the upload view so
            // it'll run the validator with the "listed=False"
            // parameter.
            var $submitAddonProgress = $('.submit-addon-progress');
            function updateListedStatus() {
              if (!isUnlisted()) {  // It's a listed add-on.
                // /!\ For some reason, $upload_field.data('upload-url', val)
                // doesn't correctly set the value for the code that uses it
                // (in upload-base.js), at least in this context, so it
                // doesn't upload to the correct url. Using
                // .attr('data-upload-url', val) instead fixes that.
                $upload_field.attr('data-upload-url', $upload_field.data('upload-url-listed'));
                $submitAddonProgress.removeClass('unlisted');
              } else {  // It's an unlisted add-on.
                $upload_field.attr('data-upload-url', $upload_field.data('upload-url-unlisted'));
                $submitAddonProgress.addClass('unlisted');
              }
              /* Don't allow submitting, need to reupload/revalidate the file. */
              $('.addon-upload-dependant').prop('disabled', true);
              $('.addon-upload-failure-dependant').prop({'disabled': true,
                                                         'checked': false});
              $('.upload-status').remove();
            }
            $channelChoice.on('change', updateListedStatus);
            if ($channelChoice.length) updateListedStatus();

            $('#id_is_manual_review').on('change', function() {
                $('.addon-upload-dependant').prop('disabled', !($(this).is(':checked')));
            });

            $upload_field.on("upload_success_results", function(e, file, results) {
                if(results.error) {
                    // This shouldn't happen.  But it might.
                    var error = gettext('Unexpected server error while validating.');
                    $upload_field.trigger("upload_errors", [file, [error]]);
                    return;
                }

                // Validation results?  If not, fetch the json again.
                if (! results.validation) {
                    upload_progress_outside.attr('class', 'progress-idle');
                    // Not loaded yet. Try again!
                    setTimeout(function() {
                        $.ajax({
                            url: results.url,
                            dataType: 'json',
                            success: function(r) {
                                $upload_field.trigger("upload_success_results", [file, r]);
                            },
                            error: function(xhr) {
                                var errOb = parseErrorsFromJson(xhr.responseText, xhr.status);
                                $upload_field.trigger("upload_errors", [file, errOb.errors, errOb.json]);
                                $upload_field.trigger("upload_finished", [file]);
                            }
                        });
                    }, 1000);
                } else {
                    if (results.addon_type==10) {
                        // No source or platform selection for static themes.
                        $('.binary-source').hide();
                        $('.supported-platforms').hide();
                    } else {
                        $('.binary-source').show();
                        $('.supported-platforms').show();
                    }
                    var errors = getErrors(results),
                        v = results.validation,
                        timeout = checkTimeout(v);
                    if (errors.length > 0 && !timeout) {
                        $upload_field.trigger("upload_errors", [file, errors, results]);
                        return;
                    }

                    $upload_field.val("").prop('disabled', false);

                    /* Allow submitting */
                    $('.addon-upload-dependant').prop('disabled', false);
                    $('.addon-upload-failure-dependant').prop({'disabled': true,
                                                               'checked': false});
                    $('.addon-create-theme-section').hide();

                    upload_title.html(format(gettext('Finished validating {0}'), [escape_(file.name)]));

                    var message = "";
                    var messageCount = v.warnings + v.notices;

                    if (timeout) {
                        message = gettext(
                                    "Your add-on validation timed out, it will be manually reviewed.");
                    } else if (v.warnings > 0) {
                        message = format(ngettext(
                                    "Your add-on was validated with no errors and {0} warning.",
                                    "Your add-on was validated with no errors and {0} warnings.",
                                    v.warnings), [v.warnings]);
                    } else if (v.notices > 0) {
                        message = format(ngettext(
                                    "Your add-on was validated with no errors and {0} message.",
                                    "Your add-on was validated with no errors and {0} messages.",
                                    v.notices), [v.notices]);
                    } else {
                        message = gettext("Your add-on was validated with no errors or warnings.");
                    }

                    upload_progress_outside.attr('class', 'bar-success');
                    upload_progress_inside.fadeOut();

                    $upload_field.trigger("reenable_uploader");

                    upload_results.addClass("status-pass");

                    $("<strong>").text(message).appendTo(upload_results);

                    // Specific messages for unlisted addons.
                    var validation_type = results.validation.detected_type;
                    if ((["extension", "dictionary", "languagepack"].indexOf(validation_type) != -1) && isUnlisted()) {
                      $("<p>").text(gettext("Your submission will be automatically signed.")).appendTo(upload_results);
                    }

                    if (results.validation.is_upgrade_to_webextension) {
                        var warning_box = $('<div>').attr('class', 'important-warning').appendTo(upload_results);

                        $('<h5>').text(gettext("WebExtension upgrade")).appendTo(warning_box);
                        $('<p>').text(gettext(
                            "We allow and encourage an upgrade but you cannot reverse this process. Once your users have the WebExtension installed, they will not be able to install a legacy add-on."
                        )).appendTo(warning_box);

                        $('<a>').text(gettext('Porting a legacy Firefox add-on on MDN'))
                                .attr('href', 'https://developer.mozilla.org/en-US/Add-ons/WebExtensions/Porting_a_legacy_Firefox_add-on')
                                .attr('target', '_blank')
                                .attr('rel', 'noopener noreferrer')
                                .appendTo(warning_box);
                    }

                    if (messageCount > 0) {
                        // Validation checklist
                        var checklist_box = $('<div>').attr('class', 'submission-checklist').appendTo(upload_results),
                            checklist = [
                                gettext("Include detailed version notes (this can be done in the next step)."),
                                gettext("If your add-on requires an account to a website in order to be fully tested, include a test username and password in the Notes to Reviewer (this can be done in the next step)."),
                            ],
                            warnings_id = [
                                'NO_DOCUMENT_WRITE',
                                'DANGEROUS_EVAL',
                                'NO_IMPLIED_EVAL',
                                'UNSAFE_VAR_ASSIGNMENT',
                                'MANIFEST_CSP',
                                'set_innerHTML',
                                'namespace_pollution',
                                'dangerous_global'
                            ], current, matched, messages = [],
                            // this.id is in the form ["testcases_javascript_instanceactions", "_call_expression", "createelement_variable"],
                            // we usually only match one of the elements.
                            matchId = function (id) {
                              return this.hasOwnProperty('id') && _.contains(this.id, id);
                            };


                        $('<h5>').text(gettext("Add-on submission checklist")).appendTo(checklist_box);
                        $('<p>').text(gettext("Please verify the following points before finalizing your submission. This will minimize delays or misunderstanding during the review process:")).appendTo(checklist_box);
                        if (results.validation.metadata.contains_binary_extension) {
                            messages.push(gettext("Compiled binaries, as well as minified or obfuscated scripts (excluding known libraries) need to have their sources submitted separately for review. Make sure that you use the source code upload field to avoid having your submission rejected."));
                        }
                        for (var i = 0; i < results.validation.messages.length; i++) {
                            current = results.validation.messages[i];
                            matched = _.find(warnings_id, matchId, current);
                            if (matched) {
                                messages.push(gettext(current.message));
                                // We want only once every possible warning hit.
                                warnings_id.splice(warnings_id.indexOf(matched), 1);
                                if (!warnings_id.length) break;
                            }
                        }
                        var checklist_ul = $('<ul>');
                        $.each(checklist, function (i) {
                            $('<li>').text(checklist[i]).appendTo(checklist_ul);
                        });
                        checklist_ul.appendTo(checklist_box);
                        if (messages.length) {
                            $('<h6>').text(gettext("The validation process found these issues that can lead to rejections:")).appendTo(checklist_box);
                            var messages_ul = $('<ul>');
                            $.each(messages, function (i) {
                                // Note: validation messages are supposed to be already escaped by
                                // devhub.views.json_upload_detail(), which does an escape_all()
                                // call on messages. So we need to use html() and not text() to
                                // display them, since they can contain HTML entities.
                                $('<li>').html(messages[i]).appendTo(messages_ul);
                            });
                            messages_ul.appendTo(checklist_box);
                        }

                        if (results.full_report_url) {
                            // There might not be a link to the full report
                            // if we get an early error like unsupported type.
                            $('<a>').text(gettext('See full validation report'))
                                    .attr('href', results.full_report_url)
                                    .attr('target', '_blank')
                                    .attr('rel', 'noopener noreferrer')
                                    .appendTo(checklist_box);
                        }
                    }

                    $(".platform ul.error").empty();
                    $(".platform ul.errorlist").empty();
                    if (results.validation.detected_type == 'search') {
                        $(".platform").hide();
                    } else {
                        $(".platform:hidden").show();
                        $('.platform label').removeClass('platform-disabled');
                        $('input.platform').prop('disabled', false);
                        if (results.platforms_to_exclude &&
                            results.platforms_to_exclude.length) {
                            // e.g. after uploading a Mobile add-on
                            var excluded = false;
                            $('input.platform').each(function() {
                                var $input = $(this);
                                if ($.inArray($input.val(),
                                              results.platforms_to_exclude) !== -1) {
                                    excluded = true;
                                    $('label[for=' + $input.attr('id') + ']').addClass('platform-disabled');
                                    $input.prop('checked', false);
                                    $input.prop('disabled', true);
                                }
                            });
                            var platforms_selector = '.supported-platforms',
                                disabled = $(platforms_selector + ' input:disabled').length,
                                all = $(platforms_selector + ' input').length;
                            if (disabled > 0 && disabled == all) {
                                $(platforms_selector + ' label').addClass('platform-disabled');
                            }
                            if (excluded) {
                                if ($('.platform input[type=checkbox]').length === $('.platform input[type=checkbox]:disabled').length) {
                                    msg = gettext('Sorry, no supported platform has been found.');
                                }
                            }
                        }
                    }
                }

            });

        });
    };
})(jQuery);
