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

    $.fn.addonUploader = function( options ) {
        var settings = {'filetypes': ['xpi', 'jar', 'xml'], 'getErrors': getErrors, 'cancel': $()};

        if (options) {
            $.extend( settings, options );
        }

        function parseErrorsFromJson(response) {
            var json, errors = [];
            try {
                json = JSON.parse(response);
            } catch(err) {
                errors = [gettext("There was a problem contacting the server.")];
            }
            if (!errors.length) {
                errors = settings['getErrors'](json);
            }
            return {
                errors: errors,
                json: json
            }
        }

        return $(this).each(function(){
            var $upload_field = $(this),
                file = {};

            /* Add some UI */

            var ui_parent = $('<div>', {'class': 'invisible-upload prominent cta', 'id': 'upload-file-widget'}),
                ui_link = $('<a>', {'class': 'button prominent', 'href': '#', 'text': gettext('Select a file...')}),
                ui_details = $('<div>', {'class': 'upload-details', 'text': gettext('Your add-on should end with .xpi, .jar or .xml')});

            $upload_field.attr('disabled', false);
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

            function textSize(bytes) {
                // Based on code by Cary Dunn (http://bit.ly/d8qbWc).
                var s = ['bytes', 'KB', 'MB', 'GB', 'TB', 'PB'];
                if(bytes === 0) return bytes + " " + s[1];
                var e = Math.floor( Math.log(bytes) / Math.log(1024) );
                return (bytes / Math.pow(1024, Math.floor(e))).toFixed(2)+" "+s[e];
            }

            function updateStatus(percentage, size) {
                if (percentage) {
                    upload_status.show();
                    p = Math.round(percentage);
                    size = (p / 100) * size;

                    // L10n: {0} is the percent of the file that has been uploaded.
                    upload_status_percent.text(format(gettext('{0}% complete'), [p]));

                    // L10n: "{bytes uploaded} of {total filesize}".
                    upload_status_progress.text(format(gettext('{0} of {1}'),
                                [textSize(size), textSize(file.size)]));
                }
            }

            /* Bind the events */

            $upload_field.bind("upload_start", function(e, _file){
                file = _file;

                /* Remove old upload box */
                if(upload_box) {
                    upload_box.remove();
                }

                /* Remove old errors */
                $upload_field.closest('form').find('.errorlist').remove();

                /* Don't allow submitting */
                $('.addon-upload-dependant').attr('disabled', true);
                $('.addon-upload-failure-dependant').attr({'disabled': true,
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

            $upload_field.bind("upload_progress", function(e, file, pct) {
                upload_progress_inside.animate({'width': pct + '%'},
                    {duration: 300, step:function(i){ updateStatus(i, file.size); } });
            });

            $upload_field.bind("upload_errors", function(e, file, errors, results){
                var all_errors = $.extend([], errors);  // be nice to other handlers
                upload_progress_inside.stop().css({'width': '100%'});

                if ($('input#id_upload').val()) {
                    $('.addon-upload-failure-dependant').attr({'disabled': false,
                                                               'checked': false});
                }

                $upload_field.val("").attr('disabled', false);
                $upload_field.trigger("reenable_uploader");

                upload_title.html(format(gettext('Error with {0}'), [escape_(file.name)]));

                upload_progress_outside.attr('class', 'bar-fail');
                upload_progress_inside.fadeOut();

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
                                                    'text': gettext('See full validation report')}));
                }


            });

            $upload_field.bind("upload_finished", function(e, file, results) {
                upload_box.removeClass("ajax-loading");
                upload_status_cancel.remove();
            });

            $upload_field.bind("upload_success", function(e, file, results) {
                upload_title.html(format(gettext('Validating {0}'), [escape_(file.name)]));

                var animateArgs = {duration: 300, step:function(i){ updateStatus(i, file.size); }, complete: function() {
                    $upload_field.trigger("upload_success_results", [file, results]);
                }};

                upload_progress_inside.animate({'width': '100%'}, animateArgs);
            });

            $upload_field.bind("upload_onreadystatechange", function(e, file, xhr, aborted) {
                var errors = [],
                    $form = $upload_field.closest('form'),
                    json = {},
                    errOb;
                if (xhr.readyState == 4 && xhr.responseText &&
                        (xhr.status == 200 ||
                         xhr.status == 304 ||
                         xhr.status == 400)) {

                    errOb = parseErrorsFromJson(xhr.responseText);
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
                    // L10n: first argument is an HTTP status code
                    errors = [format(gettext("Received an empty response from the server; status: {0}"),
                                     [xhr.status])];

                    $upload_field.trigger("upload_errors", [file, errors]);
                }
            });


            $upload_field.bind("upload_success_results", function(e, file, results) {
                if(results.error) {
                    // This shouldn't happen.  But it might.
                    var error = gettext('Unexpected server error while validating.');
                    $upload_field.trigger("upload_errors", [file, [error]]);
                    return;
                }

                // Validation results?  If not, fetch the json again.
                if(! results.validation) {
                    upload_progress_outside.attr('class', 'progress-idle');
                    // Not loaded yet. Try again!
                    setTimeout(function(){
                        $.ajax({
                            url: results.url,
                            dataType: 'json',
                            success: function(r) {
                                $upload_field.trigger("upload_success_results", [file, r]);
                            },
                            error: function(xhr, textStatus, errorThrown) {
                                var errOb = parseErrorsFromJson(xhr.responseText);
                                $upload_field.trigger("upload_errors", [file, errOb.errors, errOb.json]);
                                $upload_field.trigger("upload_finished", [file]);
                            }
                        });
                    }, 1000);
                } else {
                    var errors = getErrors(results),
                        v = results.validation;
                    if(errors.length > 0) {
                        $upload_field.trigger("upload_errors", [file, errors, results]);
                        return;
                    }

                    $upload_field.val("").attr('disabled', false);

                    /* Allow submitting */
                    $('.addon-upload-dependant').attr('disabled', false);
                    $('.addon-upload-failure-dependant').attr({'disabled': true,
                                                               'checked': false});

                    upload_title.html(format(gettext('Finished validating {0}'), [escape_(file.name)]));

                    var message = "";

                    var warnings = v.warnings + v.notices;
                    if(warnings > 0) {
                        message = format(ngettext(
                                    "Your add-on passed validation with no errors and {0} warning.",
                                    "Your add-on passed validation with no errors and {0} warnings.",
                                    warnings), [warnings]);
                    } else {
                        message = gettext("Your add-on passed validation with no errors or warnings.");
                    }

                    upload_progress_outside.attr('class', 'bar-success');
                    upload_progress_inside.fadeOut();

                    $upload_field.trigger("reenable_uploader");

                    upload_results.addClass("status-pass");

                    $("<strong>").text(message).appendTo(upload_results);

                    if (results.full_report_url) {
                        // There might not be a link to the full report
                        // if we get an early error like unsupported type.
                        upload_results.append($("<a>", {'href': results.full_report_url,
                                                        'target': '_blank',
                                                        'text': gettext('See full validation report')}));
                    }

                    $(".platform ul.error").empty();
                    $(".platform ul.errorlist").empty();
                    if (results.validation.detected_type == 'search' ||
                        results.validation.detected_type == 'webapp') {
                        $(".platform").hide();
                    } else {
                        $(".platform:hidden").show();
                        $('.platform label').removeClass('platform-disabled');
                        $('input.platform').attr('disabled', false);
                        if (results.platforms_to_exclude &&
                            results.platforms_to_exclude.length) {
                            // e.g. after uploading a Mobile add-on
                            var excluded = false;
                            $('input.platform').each(function(e) {
                                var $input = $(this);
                                if ($.inArray($input.val(),
                                              results.platforms_to_exclude) !== -1) {
                                    excluded = true;
                                    $('label[for=' + $input.attr('id') + ']').addClass('platform-disabled');
                                    $input.attr('checked', false);
                                    $input.attr('disabled', true);
                                }
                            });
                            $.each(['.desktop-platforms', '.mobile-platforms'], function(i, sel) {
                                var disabled = $(sel + ' input:disabled').length,
                                    all = $(sel + ' input').length;
                                if (disabled > 0 && disabled == all) {
                                    $(sel + ' label').addClass('platform-disabled');
                                }
                            });
                            if (excluded) {
                                var msg = gettext('Some platforms are not available for this type of add-on.');
                                $('.platform').prepend(
                                    format('<ul class="errorlist"><li>{0}</li></ul>',
                                           msg));
                            }
                        }
                    }
                }

            });

        });
    };
})(jQuery);
