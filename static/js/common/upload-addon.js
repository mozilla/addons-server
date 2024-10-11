/*
 * addonUploader()
 * Extends fileUploader()
 * Also, this can only be used once per page.  Or you'll have lots of issues with closures and scope :)
 */

(function ($) {
  /* Normalize results */
  function getErrors(results) {
    var errors = [];

    if (results.validation.messages) {
      $.each(results.validation.messages, function (i, v) {
        if (v.type == 'error') {
          errors.push(v.message);
        }
      });
    }
    return errors;
  }

  function checkTimeout(validation) {
    var timeout_id = [
      'validator',
      'unexpected_exception',
      'validation_timeout',
    ];
    return _.some(validation.messages, function (message) {
      return _.isEqual(message.id, timeout_id);
    });
  }

  $.fn.addonUploader = function (options) {
    var settings = {
      filetypes: ['zip', 'xpi', 'crx'],
      getErrors: getErrors,
      cancel: $(),
      maxSize: null, // Dynamically set by devhub.js
    };

    if (options) {
      $.extend(settings, options);
    }

    function parseErrorsFromJson(response, statusCode) {
      var json,
        errors = [];
      try {
        json = JSON.parse(response);
      } catch (err) {
        errors = [gettext('There was a problem contacting the server.')];
      }
      if (!errors.length) {
        errors = settings.getErrors(json);
      }
      return {
        errors: errors,
        json: json,
      };
    }

    return $(this).each(function () {
      var $upload_field = $(this),
        file = {};

      /* Add some UI */

      var ui_parent = $('<div>', {
          class: 'invisible-upload prominent cta',
          id: 'upload-file-widget',
        }),
        ui_link = $('<a>', {
          class: 'button prominent',
          href: '#',
          text: gettext('Select a file...'),
        }),
        ui_details = $('<div>', {
          class: 'upload-details',
          text: gettext('Your add-on should end with .zip, .xpi or .crx'),
        });

      const submissionsDisabled = !$(this).data('submissions-enabled');
      ui_link.toggleClass('disabled', submissionsDisabled);
      $upload_field.prop('disabled', submissionsDisabled);

      $upload_field.attr(
        'title',
        submissionsDisabled
          ? gettext('Add-on uploads are temporarily unavailable.')
          : $upload_field.attr('title'),
      );

      $upload_field.wrap(ui_parent);
      $upload_field.before(ui_link);
      $upload_field.parent().after(ui_details);

      if (!z.capabilities.fileAPI) {
        $('.invisible-upload').addClass('legacy');
      }

      /* Get things started */

      var upload_box,
        upload_title,
        upload_progress_outside,
        upload_progress_inside,
        upload_status,
        upload_results,
        upload_status_percent,
        upload_status_progress,
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
          upload_status_progress.text(
            format(gettext('{0} of {1}'), [
              formatFileSize(size),
              formatFileSize(file.size),
            ]),
          );
        }
      }

      /* Bind the events */

      $upload_field.on('upload_start', function (e, _file) {
        file = _file;

        /* Remove old upload box */
        if (upload_box) {
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
        $('.addon-upload-failure-dependant').prop({
          disabled: true,
          checked: false,
        });

        /* Create elements */
        upload_title = $('<strong>', { id: 'upload-status-text' });
        upload_progress_outside = $('<div>', { id: 'upload-status-bar' });
        upload_progress_inside = $('<div>').css('width', 0);
        upload_status = $('<div>', { id: 'uploadstatus' }).hide();
        upload_status_percent = $('<span>');
        upload_status_progress = $('<span>');
        upload_status_cancel_a = $('<a>', {
          href: '#',
          text: gettext('Cancel'),
        });
        upload_status_cancel = $('<span> &middot; </span>');
        upload_results = $('<div>', { id: 'upload-status-results' });
        upload_box = $('<div>', { class: 'upload-status ajax-loading' }).hide();

        /* Set up structure */
        upload_box.append(upload_title);
        upload_progress_outside.append(upload_progress_inside);
        upload_box.append(upload_progress_outside);
        upload_status.append(upload_status_percent);
        upload_status.append(' <span> &middot; </span> ');
        upload_status.append(upload_status_progress);
        upload_status.append(upload_status_cancel);
        upload_status_cancel.append(upload_status_cancel_a);

        upload_box.append(upload_status);
        upload_box.append(upload_results);

        /* Add to the dom and clean up upload_field */
        ui_details.after(upload_box);

        /* It's showtime! */
        upload_title.html(
          format(gettext('Uploading {0}'), [escape_(file.name)]),
        );
        upload_box.show();

        upload_box.addClass('ajax-loading');

        upload_status_cancel_a.click(
          _pd(function () {
            $upload_field.trigger('upload_action_abort');
          }),
        );
      });

      $upload_field.on('upload_progress', function (e, file, pct) {
        upload_progress_inside.animate(
          { width: pct + '%' },
          {
            duration: 300,
            step: function (i) {
              updateStatus(i, file.size);
            },
          },
        );
      });

      $upload_field.on('upload_errors', function (e, file, errors, results) {
        var all_errors = $.extend([], errors); // be nice to other handlers
        upload_progress_inside.stop().css({ width: '100%' });

        if ($('input#id_upload').val()) {
          $('.addon-upload-failure-dependant').prop({
            disabled: false,
            checked: false,
          });
        }

        $('.addon-create-theme-section .button').removeClass('concealed');
        $upload_field.val('').prop('disabled', false);
        $upload_field.trigger('reenable_uploader');

        upload_title.html(
          format(gettext('Error with {0}'), [escape_(file.name)]),
        );

        upload_progress_outside.attr('class', 'bar-fail');
        upload_progress_inside.fadeOut();

        $('<a>')
          .text(
            gettext(
              'Please make sure to report any linting related issues on GitHub',
            ),
          )
          .attr('href', 'https://github.com/mozilla/addons-linter/')
          .attr('class', 'addons-linter-info')
          .attr('target', '_blank')
          .attr('rel', 'noopener noreferrer')
          .appendTo(upload_results);

        var error_message = format(
          ngettext(
            'Your add-on failed validation with {0} error.',
            'Your add-on failed validation with {0} errors.',
            all_errors.length,
          ),
          [all_errors.length],
        );

        $('<strong>').text(error_message).appendTo(upload_results);

        var errors_ul = $('<ul>', { id: 'upload_errors' });

        $.each(all_errors.splice(0, 5), function (i, error) {
          errors_ul.append($('<li>', { html: error }));
        });

        if (all_errors.length > 0) {
          var message = format(
            ngettext(
              '&hellip;and {0} more',
              '&hellip;and {0} more',
              all_errors.length,
            ),
            [all_errors.length],
          );
          errors_ul.append($('<li>', { html: message }));
        }

        upload_results.append(errors_ul).addClass('status-fail');

        if (results && results.full_report_url) {
          // There might not be a link to the full report
          // if we get an early error like unsupported type.
          upload_results.append(
            $('<a>', {
              href: results.full_report_url,
              class: 'view-more',
              target: '_blank',
              rel: 'noopener noreferrer',
              text: gettext('See full validation report'),
            }),
          );
        }
      });

      $upload_field.on('upload_finished', function () {
        upload_box.removeClass('ajax-loading');
        upload_status_cancel.remove();
      });

      $upload_field.on('upload_success', function (e, file, results) {
        upload_title.html(
          format(gettext('Validating {0}'), [escape_(file.name)]),
        );

        var animateArgs = {
          duration: 300,
          step: function (i) {
            updateStatus(i, file.size);
          },
          complete: function () {
            $upload_field.trigger('upload_success_results', [file, results]);
          },
        };

        upload_progress_inside.animate({ width: '100%' }, animateArgs);
      });

      $upload_field.on(
        'upload_onreadystatechange',
        function (e, file, xhr, aborted) {
          var errors = [],
            $form = $upload_field.closest('form'),
            json = {},
            errOb;
          if (
            xhr.readyState == 4 &&
            xhr.responseText &&
            (xhr.status == 200 || xhr.status == 304 || xhr.status == 400)
          ) {
            errOb = parseErrorsFromJson(xhr.responseText, xhr.status);
            errors = errOb.errors;
            json = errOb.json;

            if (
              json &&
              json.upload &&
              (!json.validation ||
                !_.some(_.pluck(json.validation.messages, 'fatal')))
            ) {
              $form.find('input#id_upload').val(json.upload);
            }
            if (errors.length > 0) {
              $upload_field.trigger('upload_errors', [file, errors, json]);
            } else {
              $upload_field.trigger('upload_success', [file, json]);
              $upload_field.trigger('upload_progress', [file, 100]);
            }
            $upload_field.trigger('upload_finished', [file]);
          } else if (xhr.readyState == 4 && !aborted) {
            if (xhr.status == 413) {
              errors.push(
                format(
                  gettext('Your add-on exceeds the maximum size of {0}.'),
                  [formatFileSize(settings.maxSize)],
                ),
              );
            } else {
              // L10n: first argument is an HTTP status code
              errors.push(
                format(
                  gettext(
                    'Received an empty response from the server; status: {0}',
                  ),
                  [xhr.status],
                ),
              );
            }

            $upload_field.trigger('upload_errors', [file, errors]);
          }
        },
      );

      $('#id_admin_override_validation')
        .addClass('addon-upload-failure-dependant')
        .change(function () {
          if ($(this).prop('checked')) {
            // TODO: Disable these when unchecked, or bounce
            // between upload_errors and upload_success
            // handlers? I think the latter would mostly be a
            // bad idea, since failed validation might give us
            // the wrong results, and admins overriding
            // validation might need some additional leeway.
            $('.addon-upload-dependant').prop('disabled', false);
          } else {
            $('.addon-upload-dependant').prop('disabled', true);
          }
        });
      $('.addon-upload-failure-dependant').prop('disabled', true);

      function setCompatibilityCheckboxesValidity() {
        if (
          compatibilityCheckboxes.length === 0 ||
          !compatibilityCheckboxes.is(':visible') ||
          compatibilityCheckboxes.is(':checked')
        ) {
          // If there are no compatibility checkboxes or they aren't visible or
          // at least one is checked: remove custom validity on them.
          compatibilityCheckboxes.each(function (idx, item) {
            item.setCustomValidity('');
          });
        } else {
          // We need a least a visible checkbox checked to continue. Add an error
          // message to the first one.
          compatibilityCheckboxes[0].setCustomValidity(
            gettext(
              'Your extension has to be compatible with at least one application.',
            ),
          );
        }
      }

      var compatibilityCheckboxes = $('.compatible-apps input[type=checkbox]');
      var $newForm = $('.new-addon-file');
      var $channelChoice = $('input[name="channel"]');

      compatibilityCheckboxes.on('change', setCompatibilityCheckboxesValidity);
      setCompatibilityCheckboxesValidity(); // Initialize.

      function isUnlisted() {
        // True if there's radio input with 'name="channel"' with 'value="unlisted"' checked, or a
        // 'addon-is-listed' data on the new file form that is true.
        return (
          (typeof $newForm.data('addon-is-listed') != 'undefined' &&
            !$newForm.data('addon-is-listed')) ||
          ($channelChoice.length &&
            $('input[name="channel"]:checked').val() != 'listed')
        );
      }

      // is_unlisted checkbox: should the add-on be listed on AMO? If not,
      // change the addon upload button's data-upload-url.
      // If this add-on is unlisted, then tell the upload view so
      // it'll run the validator with the "listed=False"
      // parameter.
      var $submitAddonProgress = $('.submit-addon-progress');
      function updateListedStatus() {
        if (!isUnlisted()) {
          // It's a listed add-on.
          // /!\ For some reason, $upload_field.data('upload-url', val)
          // doesn't correctly set the value for the code that uses it
          // (in upload-base.js), at least in this context, so it
          // doesn't upload to the correct url. Using
          // .attr('data-upload-url', val) instead fixes that.
          $upload_field.attr(
            'data-upload-url',
            $upload_field.data('upload-url-listed'),
          );
          $submitAddonProgress.removeClass('unlisted');
        } else {
          // It's an unlisted add-on.
          $upload_field.attr(
            'data-upload-url',
            $upload_field.data('upload-url-unlisted'),
          );
          $submitAddonProgress.addClass('unlisted');
        }
        /* Don't allow submitting, need to reupload/revalidate the file. */
        $('.addon-upload-dependant').prop('disabled', true);
        $('.addon-upload-failure-dependant').prop({
          disabled: true,
          checked: false,
        });
        $('.upload-status').remove();
      }
      $channelChoice.on('change', updateListedStatus);
      if ($channelChoice.length) updateListedStatus();

      $('#id_is_manual_review').on('change', function () {
        $('.addon-upload-dependant').prop('disabled', !$(this).is(':checked'));
      });

      $upload_field.on('upload_success_results', function (e, file, results) {
        if (results.error) {
          // This shouldn't happen.  But it might.
          var error = gettext('Unexpected server error while validating.');
          $upload_field.trigger('upload_errors', [file, [error]]);
          return;
        }

        // Validation results?  If not, fetch the json again.
        if (!results.validation) {
          upload_progress_outside.attr('class', 'progress-idle');
          // Not loaded yet. Try again!
          setTimeout(function () {
            $.ajax({
              url: results.url,
              dataType: 'json',
              success: function (r) {
                $upload_field.trigger('upload_success_results', [file, r]);
              },
              error: function (xhr) {
                var errOb = parseErrorsFromJson(xhr.responseText, xhr.status);
                $upload_field.trigger('upload_errors', [
                  file,
                  errOb.errors,
                  errOb.json,
                ]);
                $upload_field.trigger('upload_finished', [file]);
              },
            });
          }, 1000);
        } else {
          // Remove hidden android compatibility input if present (it will
          // be re-added if necessary)
          $('#id_compatible_apps_hidden_android').remove();
          if (results.addon_type != 1) {
            // No source or compat app selection for themes/dicts/langpacks.
            $('.binary-source').hide();
            $('.compatible-apps').hide();
          } else {
            // Pre-check Android or not depending on what we detected in the
            // manifest.
            let $checkbox = $('#id_compatible_apps .android input');
            $checkbox
              .prop('checked', results.explicitly_compatible_with_android)
              .prop('disabled', results.explicitly_compatible_with_android)
              .parent()
              .prop(
                'title',
                results.explicitly_compatible_with_android === true
                  ? gettext(
                      'Explicitly marked as compatible with Firefox for Android in the manifest',
                    )
                  : '',
              );
            // In addition, if we automatically ticked and disabled the Android
            // checkbox, the browser won't submit the value. It's fine if
            // Firefox was also checked, but if not then we'd not submit
            // anything and the validation would fail server-side, so we
            // add/remove an hidden input to compensate.
            if (results.explicitly_compatible_with_android === true) {
              $checkbox
                .clone()
                .prop('id', 'id_compatible_apps_hidden_android')
                .prop('disabled', false)
                .prop('type', 'hidden')
                .insertAfter($checkbox);
            }
            $('.binary-source').show();
            $('.compatible-apps').show();
          }
          setCompatibilityCheckboxesValidity();

          var errors = getErrors(results),
            v = results.validation,
            timeout = checkTimeout(v);
          if (errors.length > 0 && !timeout) {
            $upload_field.trigger('upload_errors', [file, errors, results]);
            return;
          }

          $upload_field.val('').prop('disabled', false);

          /* Allow submitting */
          $('.addon-upload-dependant').prop('disabled', false);
          $('.addon-upload-failure-dependant').prop({
            disabled: true,
            checked: false,
          });
          $('.addon-create-theme-section').hide();

          upload_title.html(
            format(gettext('Finished validating {0}'), [escape_(file.name)]),
          );

          var message = '';
          var messageCount = v.warnings + v.notices;

          if (timeout) {
            message = gettext(
              'Your add-on validation timed out, it will be manually reviewed.',
            );
          } else if (v.warnings > 0) {
            message = format(
              ngettext(
                'Your add-on was validated with no errors and {0} warning.',
                'Your add-on was validated with no errors and {0} warnings.',
                v.warnings,
              ),
              [v.warnings],
            );
          } else if (v.notices > 0) {
            message = format(
              ngettext(
                'Your add-on was validated with no errors and {0} message.',
                'Your add-on was validated with no errors and {0} messages.',
                v.notices,
              ),
              [v.notices],
            );
          } else {
            message = gettext(
              'Your add-on was validated with no errors or warnings.',
            );
          }

          upload_progress_outside.attr('class', 'bar-success');
          upload_progress_inside.fadeOut();

          $upload_field.trigger('reenable_uploader');

          upload_results.addClass('status-pass');

          $('<strong>').text(message).appendTo(upload_results);

          let checklistWarningsIds = [
              'NO_DOCUMENT_WRITE',
              'DANGEROUS_EVAL',
              'NO_IMPLIED_EVAL',
              'UNSAFE_VAR_ASSIGNMENT',
              'MANIFEST_CSP',
            ],
            mv3NoticeId = '_MV3_COMPATIBILITY',
            checklistMessages = [],
            mv3CompatibilityMessage,
            // this.id is in the form ["abc_def_ghi', 'foo_bar', 'something'],
            // we usually only match one of the elements.
            matchId = function (id) {
              return this.hasOwnProperty('id') && _.contains(this.id, id);
            };

          if (results.validation.messages) {
            for (var i = 0; i < results.validation.messages.length; i++) {
              let current = results.validation.messages[i];

              if (current.extra) {
                // We want to ignore messages that are not coming from the
                // linter in the logic that decides whether or not to show the
                // submission checklist box. Those are tagged with extra: true.
                messageCount--;
              }

              // Check for warnings we want to higlight specifically.
              let matched = _.find(checklistWarningsIds, matchId, current);
              if (matched) {
                checklistMessages.push(gettext(current.message));
                // We want only once every possible warning hit.
                checklistWarningsIds.splice(
                  checklistWarningsIds.indexOf(matched),
                  1,
                );
                if (!checklistWarningsIds.length) break;
              }

              // Manifest v3 warning is a custom one added by addons-server
              // that should be added once, regardless of whether or not we're
              // displaying the submission warning box.
              if (_.find([mv3NoticeId], matchId, current)) {
                let mv3CompatibilityBox = $('<div>')
                  .attr('class', 'submission-warning')
                  .appendTo(upload_results);
                $('<h5>').text(current.message).appendTo(mv3CompatibilityBox);
                // That description is split into several paragraphs and can
                // contain HTML for links.
                current.description.forEach(function (item) {
                  $('<p>').html(item).appendTo(mv3CompatibilityBox);
                });
              }
            }
          }

          if (messageCount > 0) {
            // Validation checklist should be displayed if there is at least
            // one message coming from the linter.
            let checklist_box = $('<div>')
                .attr('class', 'submission-warning')
                .appendTo(upload_results),
              checklist = [
                gettext(
                  'Include detailed version notes (this can be done in the next step).',
                ),
                gettext(
                  'If your add-on requires an account to a website in order to be fully tested, include a test username and password in the Notes to Reviewer (this can be done in the next step).',
                ),
              ];

            $('<h5>')
              .text(gettext('Add-on submission checklist'))
              .appendTo(checklist_box);
            $('<p>')
              .text(
                gettext(
                  'Please verify the following points before finalizing your submission. This will minimize delays or misunderstanding during the review process:',
                ),
              )
              .appendTo(checklist_box);
            if (results.validation.metadata.contains_binary_extension) {
              checklistMessages.push(
                gettext(
                  'Minified, concatenated or otherwise machine-generated scripts (excluding known libraries) need to have their sources submitted separately for review. Make sure that you use the source code upload field to avoid having your submission rejected.',
                ),
              );
            }
            var checklist_ul = $('<ul>');
            $.each(checklist, function (i) {
              $('<li>').text(checklist[i]).appendTo(checklist_ul);
            });
            checklist_ul.appendTo(checklist_box);
            if (checklistMessages.length) {
              $('<h6>')
                .text(
                  gettext(
                    'The validation process found these issues that can lead to rejections:',
                  ),
                )
                .appendTo(checklist_box);
              var messages_ul = $('<ul>');
              $.each(checklistMessages, function (i) {
                // Note: validation messages can contain HTML, in the form of
                // links or entities, because devhub.views.json_upload_detail()
                // uses processed_validation with escapes and linkifies linter
                // messages (and escape_all() on non-linter messages).
                // So we need to use html() and not text() to display them.
                $('<li>').html(checklistMessages[i]).appendTo(messages_ul);
              });
              messages_ul.appendTo(checklist_box);
            }

            if (results.full_report_url) {
              // There might not be a link to the full report
              // if we get an early error like unsupported type.
              $('<a>')
                .text(gettext('See full validation report'))
                .attr('href', results.full_report_url)
                .attr('target', '_blank')
                .attr('rel', 'noopener noreferrer')
                .appendTo(checklist_box);
            }
          }
        }
      });
    });
  };
})(jQuery);
