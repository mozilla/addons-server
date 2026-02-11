import $ from 'jquery';
import _ from 'underscore';
import { initCharCount, show_slug_edit } from './global';
import { _pd } from '../lib/prevent-default';
import { format } from '../lib/format';
import { slugify, validateFileUploadSize } from '../zamboni/global';
import { annotateLocalizedErrors, refreshL10n } from './l10n';
import { template } from '../lib/format';
import { capabilities } from '../zamboni/capabilities';
import { render } from 'timeago.js';

$(document).ready(function () {
  // Modals
  let $modalFile, $modalDelete, $modalDisable;

  // Edit Add-on
  $('#edit-addon').exists(initEditAddon);

  // Poll for suppressed email removal updates.
  $('.verify-email#verification_pending').exists(function () {
    setTimeout(function () {
      window.location.reload();
    }, 30_000);
  });

  //Ownership
  $('#authors_confirmed').exists(function () {
    initAuthorFields();
    initLicenseFields();
  });

  // Edit Versions
  $('.edit-version').exists(initEditVersions);

  // View versions
  $('#version-list').exists(initVersions);

  // Submission process
  $('.addon-submission-process').exists(function () {
    initLicenseFields();
    initCharCount();
    initSubmit();
  });

  // Validate addon (standalone)
  $('.validate-addon').exists(initSubmit);

  // Submission > Source
  $('#submit-source').exists(initSourceSubmitOutcomes);

  // Submission > Describe
  $('#submit-describe').exists(initCatFields);
  $('#submit-describe').exists(initCCLicense);

  // Submission > Media
  $('#submit-media').exists(function () {
    initUploadIcon();
    initUploadPreview();
  });

  // Developer experience survey
  $('#dev-survey-banner').exists(function () {
    initSurveyBanner();
  });

  // disable buttons if submission is explicitly disabled
  const submissionField = $('#submission-field');
  const submissionsDisabled =
    submissionField && submissionField.data('submissions-enabled') === false;

  $('.submission-buttons .button').toggleClass('disabled', submissionsDisabled);

  // Add-on uploader
  let $uploadAddon = $('#upload-addon');
  if ($('#upload-addon').length) {
    let opt = {
      cancel: $('.upload-file-cancel'),
      maxSize: $uploadAddon.data('max-upload-size'),
      submissionsDisabled,
    };
    opt.appendFormData = function (formData) {
      if ($('#addon-compat-upload').length) {
        formData.append('app_id', $('#id_application option:selected').val());
        formData.append(
          'version_id',
          $('#id_app_version option:selected').val(),
        );
      }
      // theme_specific is a django BooleanField, so the value will be the
      // litteral string "True" or "False". That's what the upload() view
      // expects.
      formData.append('theme_specific', $('#id_theme_specific').val());
    };
    $uploadAddon.addonUploader(opt);
  }

  $('.invisible-upload a').click(_pd(function () {}));

  // when to start and stop image polling
  if (
    $('#edit-addon-media').length &&
    $('#edit-addon-media').attr('data-checkurl') !== undefined
  ) {
    imageStatus.start();
  }
  $('#edit-addon-media').on('click', function () {
    imageStatus.cancel();
  });

  // hook up various links related to current version status
  if ($('#modal-delete').length) {
    $modalDelete = $('#modal-delete').modal('.delete-addon', {
      width: 400,
      callback: function (obj) {
        return fixPasswordField(this);
      },
    });
    if (window.location.hash === '#delete-addon') {
      $modalDelete.render();
    }
  }
  if ($('#modal-disable').length) {
    $modalDisable = $('#modal-disable').modal('.disable-addon', {
      width: 400,
      callback: function (d) {
        $('.version_id', this).val($(d.click_target).attr('data-version'));
        return true;
      },
    });
    if (window.location.hash === '#disable-addon') {
      $modalDisable.render();
    }
  }
  if ($('#modal-unlist').length) {
    const $modalUnlist = $('#modal-unlist').modal('.unlist-addon', {
      width: 400,
    });
    if (window.location.hash === '#unlist-addon') {
      $modalUnlist.render();
    }
  }
  // Show a confirmation modal for forms that have [data-confirm="selector"].
  // This is specifically used for the request full review form for unlisted
  // add-ons.
  $(document.body).on('submit', '[data-confirm]', function (e) {
    e.preventDefault();
    let $form = $(e.target);
    let $modal = $form.data('modal');
    if (!$modal) {
      $modal = $($form.data('confirm')).modal();
      $form.data('modal', $modal);
    }
    $modal.render();
    $modal.on('click', '.cancel', function (e) {
      e.preventDefault();
      e.stopPropagation();
      $modal.trigger('close');
    });
    $modal.on('submit', 'form', function (e) {
      e.preventDefault();
      $form.removeAttr('data-confirm');
      $form.submit();
    });
  });

  $('.enable-addon, .rejected-review-request').on('click', function () {
    $.ajax({
      type: 'POST',
      url: $(this).data('url'),
      success: function () {
        window.location.reload();
      },
    });
  });

  // API credentials page
  $('.api-credentials').on('submit', function () {
    // Disallow double-submit. Don't actually disable the buttons, because
    // then the correct one would not be submitted, but set the class to
    // emulate that.
    $(this).find('button').addClass('disabled');
  });
});

$(document).ready(function () {
  $.ajaxSetup({ cache: false });

  $('.more-actions-popup').each(function () {
    let el = $(this);
    el.popup(el.closest('li').find('.more-actions'), {
      width: 'inherit',
      offset: { x: 15 },
      callback: function (obj) {
        return { pointTo: $(obj.click_target) };
      },
    });
  });

  $('.modal-delete').each(function () {
    let el = $(this);
    el.modal(el.siblings('.delete-addon'), {
      width: 400,
      callback: function (obj) {
        fixPasswordField(this);
        return { pointTo: $(obj.click_target) };
      },
    });
  });

  truncateFields();

  initCompatibility();

  $(document).on('click', '.addon-edit-cancel', function () {
    const parent_div = $(this).closest('.edit-addon-section');
    parent_div.load($(this).attr('href'), function () {
      $('.tooltip').tooltip('#tooltip');
      hideSameSizedIcons();
      refreshL10n();
    });
    if (parent_div.is('#edit-addon-media')) {
      imageStatus.start();
    }
    return false;
  });
});

let noEdit = $('body').hasClass('no-edit');

if (noEdit) {
  const $primary = $('.primary');
  const $els = $primary.find('input, select, textarea, button, a.button');
  $els.prop('disabled', true);
  $primary.find('span.handle, a.remove').hide();
  $('.primary h3 a.button').remove();
  $(document).ready(function () {
    $els.off().off();
  });
}

function truncateFields() {
  // TODO (potch) find a good fix for this later
  // as per Bug 622030...
  return;
  // let els = [
  //         "#addon-description",
  //         "#developer_comments"
  //     ];
  // $(els.join(', ')).each(function(i,el) {
  //     let $el = $(el),
  //         originalHTML = $el.html();
  //     $el.on("click", "a.truncate_expand", function(e) {
  //         e.preventDefault();
  //         $el.html(originalHTML).css('max-height','none');
  //     })
  //     .vtruncate({
  //         truncText: format("&hellip; <a href='#' class='truncate_expand'>{0}</a>",[gettext("More")])
  //     });
  // });
}

function addonFormSubmit() {
  const parent_div = $(this);

  // If the baseurl changes (the slug changed) we need to go to the new url.
  let baseurl = function () {
    return parent_div.find('#addon-edit-describe').attr('data-baseurl');
  };
  $('.edit-media-button button').prop('disabled', false);
  $('form', parent_div).submit(function (e) {
    e.preventDefault();
    let old_baseurl = baseurl();
    parent_div.find('.item').removeClass('loaded').addClass('loading');
    let $document = $(document),
      scrollBottom = $document.height() - $document.scrollTop(),
      $form = $(this);

    $.post($form.attr('action'), $form.serialize(), function (d) {
      parent_div.html(d).each(addonFormSubmit);
      // The HTML has changed after we posted the form, thus the need to retrieve the new HTML
      $form = parent_div.find('form');
      let hasErrors = $form.find('.errorlist').length;
      $('.tooltip').tooltip('#tooltip');
      if (!hasErrors && old_baseurl && old_baseurl !== baseurl()) {
        document.location = baseurl();
      }
      $document.scrollTop($document.height() - scrollBottom);
      truncateFields();
      annotateLocalizedErrors(parent_div);
      if (parent_div.is('#edit-addon-media')) {
        imageStatus.start();
        hideSameSizedIcons();
      }
      if ($form.find('#addon-categories-edit').length) {
        initCatFields();
      }

      if (!hasErrors) {
        let e = $(
          format('<b class="save-badge">{0}</b>', [gettext('Changes Saved')]),
        ).appendTo(parent_div.find('h3').first());
        setTimeout(function () {
          e.css('opacity', 0);
          setTimeout(function () {
            e.remove();
          }, 200);
        }, 2000);
      }
    });
  });
  reorderPreviews();
  refreshL10n();
}

$('#user-form-template .author-email').attr({
  placeholder: gettext("Enter a new author's email address"),
  readonly: false,
});

function initEditAddon() {
  if (noEdit) return;

  // Load the edit form.
  $('#edit-addon').on('click', 'h3 a', function (e) {
    e.preventDefault();

    const a = e.target;
    const parent_div = $(a).closest('.edit-addon-section');

    parent_div.find('.item').addClass('loading');
    parent_div.load($(a).attr('data-editurl'), function () {
      $('.tooltip').tooltip('#tooltip');
      if (parent_div.find('#addon-categories-edit').length) {
        initCatFields();
      }
      $(this).each(addonFormSubmit);
      initInvisibleUploads();
    });

    return false;
  });

  // Init icon javascript.
  hideSameSizedIcons();
  initUploadIcon();
  initUploadPreview();
}

function create_new_preview_field() {
  let forms_count = $('#id_files-TOTAL_FORMS').val(),
    last = $('#file-list .preview').last(),
    last_clone = last.clone();

  $('input, textarea, div', last_clone).each(function () {
    let re = new RegExp(format('-{0}-', [forms_count - 1])),
      new_count = '-' + forms_count + '-',
      el = $(this);

    $.each(['id', 'name', 'data-name'], function (k, v) {
      if (el.attr(v)) {
        el.attr(v, el.attr(v).replace(re, new_count));
      }
    });
  });
  $(last).after(last_clone);
  $('#id_files-TOTAL_FORMS').val(parseInt(forms_count, 10) + 1);

  return last;
}

function renumberPreviews() {
  const previews = $('#file-list').children('.preview:visible');
  previews.each(function (i, el) {
    $(this).find('.position input').val(i);
  });
  $(previews)
    .find('.handle')
    .toggle(previews.length > 1);
}

function reorderPreviews() {
  let preview_list = $('#file-list');

  if (preview_list.length) {
    preview_list.sortable({
      items: '.preview:visible',
      handle: '.handle',
      containment: preview_list,
      tolerance: 'pointer',
      update: renumberPreviews,
    });

    renumberPreviews();
  }
}

function initUploadPreview() {
  let forms = {},
    $f = $('#edit-addon-media, #submit-media');

  function upload_start_all(e) {
    // Remove old errors.
    $('.edit-addon-media-screenshot-error').hide();

    // Don't let users submit a form.
    $('.edit-media-button button').prop('disabled', true);
  }

  function upload_finished_all(e) {
    // They can submit again
    $('.edit-media-button button').prop('disabled', false);
  }

  function upload_start(e, file) {
    const form = create_new_preview_field();
    forms['form_' + file.instance] = form;

    $(form)
      .show()
      .find('.preview-thumb')
      .addClass('loading')
      .css('background-image', 'url(' + file.dataURL + ')');
    renumberPreviews();
  }

  function upload_finished(e, file) {
    const form = forms['form_' + file.instance];
    form.find('.preview-thumb').removeClass('loading');
    renumberPreviews();
  }

  function upload_success(e, file, upload_hash) {
    const form = forms['form_' + file.instance];
    form.find('[name$="upload_hash"]').val(upload_hash);
  }

  function upload_errors(e, file, errors) {
    let form = forms['form_' + file.instance],
      $el = $(form),
      error_msg = gettext('There was an error uploading your file.'),
      $error_title = $('<strong>').text(error_msg),
      $error_list = $('<ul>');

    $el.addClass('edit-addon-media-screenshot-error');

    $.each(errors, function (i, v) {
      $error_list.append('<li>' + v + '</li>');
    });

    $el.find('.preview-thumb').addClass('error-loading');

    $el
      .find('.edit-previews-text')
      .addClass('error')
      .html('')
      .append($error_title)
      .append($error_list);
    $el.find('.delete input').prop('checked', true);
    renumberPreviews();
  }

  if (capabilities.fileAPI) {
    $f.on('upload_finished', '#screenshot_upload', upload_finished)
      .on('upload_success', '#screenshot_upload', upload_success)
      .on('upload_start', '#screenshot_upload', upload_start)
      .on('upload_errors', '#screenshot_upload', upload_errors)
      .on('upload_start_all', '#screenshot_upload', upload_start_all)
      .on('upload_finished_all', '#screenshot_upload', upload_finished_all)
      .on('change', '#screenshot_upload', function (e) {
        $(this).imageUploader();
      });
  }

  $('#edit-addon-media, #submit-media').on(
    'click',
    '#file-list .remove',
    function (e) {
      e.preventDefault();
      let row = $(this).closest('.preview');
      row.find('.delete input').prop('checked', true);
      row.slideUp(300, renumberPreviews);
    },
  );
}

function initInvisibleUploads() {
  if (!capabilities.fileAPI) {
    $('.invisible-upload').addClass('legacy');
  }
}

function initUploadIcon() {
  initInvisibleUploads();

  $('#edit-addon-media, #submit-media').on(
    'click',
    '#icons_default a',
    function (e) {
      e.preventDefault();

      let $error_list = $('#icon_preview').parent().find('.errorlist'),
        $parent = $(this).closest('li');

      $('input', $parent).prop('checked', true);
      $('#icons_default a.active').removeClass('active');
      $(this).addClass('active');

      $('#id_icon_upload').val('');
      $('#icon_preview').show();

      $('#icon_preview_32 img').attr('src', $('img', $parent).attr('src'));
      $('#icon_preview_64 img').attr('src', $('img', $parent).data('src-64'));
      $('#icon_preview_128 img').attr('src', $('img', $parent).data('src-128'));
      $error_list.html('');
    },
  );

  // Upload an image!
  let $f = $('#edit-addon-media, #submit-media'),
    upload_errors = function (e, file, errors) {
      let $error_list = $('#icon_preview').parent().find('.errorlist');
      $.each(errors, function (i, v) {
        $error_list.append('<li>' + v + '</li>');
      });
    },
    upload_success = function (e, file, upload_hash) {
      $('#id_icon_upload_hash').val(upload_hash);
      $('#icons_default a.active').removeClass('active');

      $('#icon_preview img').attr('src', file.dataURL);

      $('#icons_default input:checked').prop('checked', false);
      $(
        'input[name="icon_type"][value="' + file.type + '"]',
        $('#icons_default'),
      ).prop('checked', true);
    },
    upload_start = function (e, file) {
      let $error_list = $('#icon_preview').parent().find('.errorlist');
      $error_list.html('');

      $('.icon_preview img', $f).addClass('loading');

      $('.edit-media-button button').prop('disabled', true);
    },
    upload_finished = function (e) {
      $('.icon_preview img', $f).removeClass('loading');
      $('.edit-media-button button').prop('disabled', false);
    };

  $f.on('upload_success', '#id_icon_upload', upload_success)
    .on('upload_start', '#id_icon_upload', upload_start)
    .on('upload_finished', '#id_icon_upload', upload_finished)
    .on('upload_errors', '#id_icon_upload', upload_errors)
    .on('change', '#id_icon_upload', function (e) {
      if (capabilities.fileAPI) {
        $(this).imageUploader();
      } else {
        $('#icon_preview').hide();
      }
    });
}

function fixPasswordField($context) {
  // This is a hack to prevent password managers from automatically
  // deleting add-ons.  See bug 630126.
  $context.find('input[type="password"]').each(function () {
    let $this = $(this);
    if ($this.attr('data-name')) {
      $this.attr('name', $this.attr('data-name'));
    }
  });
  return true;
}

function initVersions() {
  $('#modals').hide();
  let versions;
  $.getJSON($('#version-list').attr('data-stats'), function (json) {
    versions = json;
  });

  $('#modal-delete-version').modal('.version-delete .remove', {
    width: 400,
    callback: function (d) {
      /* This sucks because of ngettext. */
      let el = $(d.click_target),
        version = versions[el.data('version')],
        is_current = el.data('is-current') === 1,
        can_be_disabled = el.data('can-be-disabled') === 1,
        header = $('h3', this),
        files = $('#del-files', this);
      header.text(format(header.attr('data-tmpl'), version));
      files.text(
        format(
          ngettext('{files} file', '{files} files', version.files),
          version,
        ),
      );
      $('.version_id', this).val(version.id);
      $('.current-version-warning', this).toggle(is_current);
      // If the version is promoted and current, show the warning and
      // hide the whole form.
      $('.promoted-version-warning', this).toggle(!can_be_disabled);
      $('form', this).toggle(can_be_disabled);
      return true;
    },
  });

  if ($('#modal-rollback-version').length) {
    const CHANNEL_UNLISTED = '1',
          CHANNEL_LISTED = '2';
    let $modalRollback = $('#modal-rollback-version').modal('.version-rollback', {
      width: 600
    });
    if (window.location.hash === '#rollback-version') {
      $modalRollback.render();
    }

    let $channelInputs = $('#id_channel input'),
        $hiddenChannelInput = $('input[name="channel"][type="hidden"]'),
        $listedVersionRow = $('#listed-version-row'),
        $unlistedVersionRow = $('#unlisted-version-row'),
        $listedVersionSelect = $('#id_listed_version'),
        $unlistedVersionSelect = $('#id_unlisted_version');

    const explainerAndReleaseNotesUpdate = function (event) {
      const $explainer = $('#rollback-explainer-row'),
            $releaseNotes = $('#id_release_notes'),
            $target = $(event.target);

      const currentVersion = $target.parent().data('current-version');
      let selectedVersion = 'm.m';
      if ($target.val()) {
        selectedVersion = $('#' + event.target.id + ' option:selected').text()
      }
      const formatted = $explainer.data('template').replace('[n.n]', '[' + currentVersion + ']').replace('[m.m]', '[' + selectedVersion + ']');
      $explainer.text(formatted);

      if (!$releaseNotes.data('last-value') || $releaseNotes.val() == $releaseNotes.data('last-value')) {
        // If user has modified the field, don't overwrite it.
        const formattedNotes = $releaseNotes.prop('defaultValue').replace('[m.m]', '[' + selectedVersion + ']');
        $releaseNotes.val(formattedNotes);
        $releaseNotes.data('last-value', formattedNotes);
      }
    };

    $listedVersionSelect.on('change', explainerAndReleaseNotesUpdate);
    $unlistedVersionSelect.on('change', explainerAndReleaseNotesUpdate);

    $channelInputs.on('change', function () {
      $listedVersionRow.hide();
      $unlistedVersionRow.hide();
      $channelInputs.each(function (index, element) {
        const $radio = $(element);
        if ($radio.val() == CHANNEL_LISTED && $radio.prop('checked')) {
          $listedVersionRow.show();
          $listedVersionSelect.trigger('change');
        }
        if ($radio.val() == CHANNEL_UNLISTED && $radio.prop('checked')) {
          $unlistedVersionRow.show();
          $unlistedVersionSelect.trigger('change');
        }
      });
    })
    .trigger('change');

    if ($hiddenChannelInput) {
      if ($hiddenChannelInput.val() == CHANNEL_UNLISTED) {
        $unlistedVersionSelect.trigger('change');
      } else if ($hiddenChannelInput.val() == CHANNEL_LISTED) {
        $listedVersionSelect.trigger('change');
      }
    }
  }

  function addToReviewHistory(json, historyContainer, reverseOrder) {
    let empty_note = historyContainer.children('.review-entry-empty');
    json.forEach(function (note) {
      let clone = empty_note.clone(true, true);
      clone.attr('class', 'review-entry');
      if (note['highlight'] == true) {
        clone.addClass('new');
      }
      clone.find('.action')[0].textContent = note['action_label'];
      let user = clone.find('.user_name');
      user[0].textContent = note['user']['name'];
      let date = clone.find('.timeago');
      date[0].textContent = note['date'];
      date.attr('datetime', note['date']);
      date.attr('title', note['date']);
      clone.find('pre:contains("$comments")')[0].textContent = note['comments'];
      if (note['attachment_url']) {
        clone.find('.review-entry-attachment').removeClass('hidden');
        clone.find('.attachment_url').attr('href', note['attachment_url']);
        clone.find('.attachment_size')[0].textContent =
          `(${note['attachment_size']})`;
      }
      if (reverseOrder) {
        historyContainer.append(clone);
      } else {
        clone.insertAfter(historyContainer.children('.review-entry-failure'));
      }
    });
    render(document.querySelectorAll('time.timeago'));
  }

  function loadReviewHistory(div, nextLoad) {
    div.removeClass('hidden');
    const replybox = div.children('.dev-review-reply');
    if (replybox.length == 1) {
      replybox[0].scrollIntoView(false);
    }
    let sessionId = div.data('session-id');
    let container = div.children('.history-container');
    container.children('.review-entry-loading').removeClass('hidden');
    container.children('.review-entry-failure').addClass('hidden');
    let api_url;
    if (!nextLoad) {
      container.children('.review-entry').remove();
      api_url = div.data('api-url');
    } else {
      api_url = div.data('next-url');
    }
    let success = function (json) {
      addToReviewHistory(json['results'], container);
      let loadmorediv = container.children('div.review-entry-loadmore');
      if (json['next']) {
        loadmorediv.removeClass('hidden');
        container.prepend(loadmorediv);
        div.attr('data-next-url', json['next']);
      } else {
        loadmorediv.addClass('hidden');
      }
    };
    let fail = function (xhr) {
      container.children('.review-entry-failure').removeClass('hidden');
      container
        .children('.review-entry-failure')
        .append(
          '<pre>' +
            api_url +
            ', ' +
            xhr.statusText +
            ', ' +
            xhr.responseText +
            '</pre>',
        );
    };
    $.ajax({
      url: api_url,
      type: 'get',
      beforeSend: function (xhr) {
        xhr.setRequestHeader('Authorization', 'Session ' + sessionId);
      },
      complete: function (xhr) {
        container.children('.review-entry-loading').addClass('hidden');
      },
      processData: false,
      contentType: false,
      success: success,
      error: fail,
    });
  }
  $('.review-history-show').click(function (e) {
    e.preventDefault();
    let version = $(this).data('version');
    let $show_link = $('#review-history-show-' + version);
    $show_link.addClass('hidden');
    $show_link.next().removeClass('hidden');
    loadReviewHistory($($show_link.data('div')));
  });
  $('.review-history-hide').click(function (e) {
    e.preventDefault();
    let $tgt = $(this);
    $tgt.addClass('hidden');
    let prev = $tgt.prev();
    prev.removeClass('hidden');
    $(prev.data('div')).addClass('hidden');
  });
  $('a.review-history-loadmore').click(function (e) {
    e.preventDefault();
    let $tgt = $(this);
    loadReviewHistory($($tgt.data('div')), true);
  });
  $('.review-history-hide').prop('style', '');
  $('.review-history.hidden').prop('style', '');
  $('.history-container .hidden').prop('style', '');
  render(document.querySelectorAll('time.timeago'));

  $('.dev-review-reply-form').submit(function (e) {
    e.preventDefault();
    const $replyForm = $(e.target);
    if ($replyForm.children('textarea').val() == '') {
      return false;
    }
    let submitButton = $replyForm.children('button');
    $.ajax({
      type: 'POST',
      url: $replyForm.attr('action'),
      data: $replyForm.serialize(),
      beforeSend: function (xhr) {
        submitButton.prop('disabled', true);
        let sessionId = $replyForm.data('session-id');
        xhr.setRequestHeader('Authorization', 'Session ' + sessionId);
      },
      success: function (json) {
        let historyDiv = $($replyForm.data('history'));
        let container = historyDiv.children('.history-container');
        addToReviewHistory([json], container, true);
        $replyForm.children('textarea').val('');
      },
      complete: function () {
        submitButton.prop('disabled', false);
      },
      dataType: 'json',
    });
    return false;
  });
}

function initSubmit() {
  let dl = $('body').attr('data-default-locale');
  let el = format('#trans-name [lang="{0}"]', dl);
  $(el).attr('id', 'id_name');
  $('#submit-describe')
    .on('keyup', el, slugify)
    .on('blur', el, slugify)
    .on('click', '#edit_slug', show_slug_edit)
    .on('change', '#id_slug', function () {
      $('#id_slug').attr('data-customized', 1);
      let v = $('#id_slug').val();
      if (!v) {
        $('#id_slug').attr('data-customized', 0);
        slugify();
      }
    })
    .on('keyup blur', showNameSummaryCroppingWarnings);
  $('#id_slug').each(slugify);
  showNameSummaryCroppingWarnings();
  reorderPreviews();
  initSubmitModals();
  $('.invisible-upload [disabled]').prop('disabled', false);
  $('.invisible-upload .disabled').removeClass('disabled');
}

function showNameSummaryCroppingWarnings() {
  let exceeds_max_length = false,
    max_length = $('.edit-addon-details .char-count').data('maxlength'),
    name_default_val = $('[name^="name_"]:visible').val(),
    summary_default_val = $('[name^="summary_"]:visible').val(),
    selectors =
      '.combine-name-summary [name^="name_"]:hidden, .combine-name-summary [name^="summary_"]:hidden';

  $(selectors).each(function (index, element) {
    let locale = $(element).attr('lang'),
      name_val = $('[name="name_' + locale + '"]').val() || name_default_val,
      summary_val =
        $('[name="summary_' + locale + '"]').val() || summary_default_val;
    if (locale != 'init' && name_val.length + summary_val.length > max_length) {
      exceeds_max_length = true;
      return false;
    }
  });

  $('#name-summary-locales-warning').toggle(exceeds_max_length);
}

function generateErrorList(o) {
  let list = $("<ul class='errorlist'></ul>");
  $.each(o, function (i, v) {
    list.append($(format('<li>{0}</li>', v)));
  });
  return list;
}

function initEditVersions() {
  if (noEdit) return;
  $('#file-list').on('click', 'a.remove', function () {
    let row = $(this).closest('tr');
    $('input:first', row).prop('checked', true);
    row.hide();
    row.next().show();
  });

  $('#file-list').on('click', 'a.undo', function () {
    let row = $(this).closest('tr').prev();
    $('input:first', row).prop('checked', false);
    row.show();
    row.next().hide();
  });

  $('.show_file_history').click(
    _pd(function () {
      $(this)
        .closest('p')
        .hide()
        .closest('div')
        .find('.version-comments')
        .fadeIn();
    }),
  );
}

function initCatFields(delegate) {
  let $delegate = $(delegate || '#addon-categories-edit');
  $delegate.find('div.addon-app-cats').each(function () {
    let main_selector = '.addon-categories',
      misc_selector = '.addon-misc-category';
    let $parent = $(this);
    let $grand_parent = $(this).closest('[data-max-categories]'),
      $main = $parent.find(main_selector),
      $misc = $parent.find(misc_selector),
      maxCats = parseInt($grand_parent.attr('data-max-categories'), 10);
    let checkMainDefault = function () {
      let checkedLength = $('input:checked', $main).length,
        disabled = checkedLength >= maxCats;
      $('input:not(:checked)', $main).prop('disabled', disabled);
      return checkedLength;
    };
    let checkMain = function () {
      let checkedLength = checkMainDefault();
      $('input', $misc).prop('checked', checkedLength <= 0);
    };
    let checkOther = function () {
      $('input', $main).prop('checked', false).prop('disabled', false);
    };
    checkMainDefault();
    $parent.on('change', main_selector + ' input', checkMain);
    $parent.on('change', misc_selector + ' input', checkOther);
  });
}

function initLicenseFields() {
  $('#id_has_eula').change(function (e) {
    if ($(this).prop('checked')) {
      $('.eula').show().removeClass('hidden');
    } else {
      $('.eula').hide();
    }
  });
  $('#id_has_priv').change(function (e) {
    if ($(this).prop('checked')) {
      $('.priv').show().removeClass('hidden');
    } else {
      $('.priv').hide();
    }
  });
  let other_val = $('.license-other').attr('data-val');
  $('.license').click(function (e) {
    if ($(this).val() == other_val) {
      $('.license-other').show().removeClass('hidden');
    } else {
      $('.license-other').hide();
    }
  });
}

function initAuthorFields() {
  // Add the help line after the blank author row.
  $('#author-roles-help').popup('#what-are-roles', {
    pointTo: $('#what-are-roles'),
  });

  if (noEdit) return;

  let request = false,
    timeout = false,
    empty_form = template(
      $('#user-form-template')
        .html()
        .replace(/__prefix__/g, '{0}'),
    ),
    authors = $('#authors_confirmed'),
    authors_pending_confirmation = $('#authors_pending_confirmation');
  authors.sortable({
    items: '.author',
    handle: '.handle',
    containment: authors,
    tolerance: 'pointer',
    update: renumberAuthors,
  });
  addAuthorRow();

  $('.author .errorlist').each(function () {
    $(this)
      .parent()
      .find('.author-email')
      .addClass('tooltip')
      .addClass('invalid')
      .addClass('formerror')
      .attr('title', $(this).text());
  });

  authors.on('click', '.remove', function (e) {
    e.preventDefault();
    let tgt = $(this),
      row = tgt.parents('li'),
      manager = $('#id_user_form-TOTAL_FORMS');
    if (authors.children('.author:visible').length > 1) {
      if (row.hasClass('initial')) {
        row.find('.delete input').prop('checked', true);
        row.hide();
      } else {
        row.remove();
        manager.val(authors.children('.author').length);
      }
      renumberAuthors();
    }
  });

  authors_pending_confirmation
    .on('keypress', '.author-email', validateUser)
    .on('keyup', '.author-email', validateUser)
    .on('click', '.remove', function (e) {
      e.preventDefault();
      let tgt = $(this),
        row = tgt.parents('li'),
        manager = $('#id_authors_pending_confirmation-TOTAL_FORMS');
      if (row.hasClass('initial')) {
        row.find('.delete input').prop('checked', true);
        row.hide();
      } else {
        row.remove();
        manager.val(authors.children('.author').length);
      }
    });

  function validateUser(e) {
    let tgt = $(this),
      row = tgt.parents('li');
    if (row.hasClass('blank')) {
      tgt.removeClass('placeholder').attr('placeholder', undefined);
      row.removeClass('blank').addClass('author');
      // Now that we've added a user, if it was hidden we need to show
      // the Authors pending confirmation section header.
      authors_pending_confirmation
        .parents('tr')
        .find('th')
        .removeClass('invisible');
      addAuthorRow();
    }
  }

  function renumberAuthors() {
    authors.children('.author').each(function (i, el) {
      $(this).find('.position input').val(i);
    });
    if ($('.author:visible').length > 1) {
      authors.sortable('enable');
      $('.author .remove').show();
      $('.author .handle').css('visibility', 'visible');
    } else {
      authors.sortable('disable');
      $('.author .remove').hide();
      $('.author .handle').css('visibility', 'hidden');
    }
  }
  function addAuthorRow() {
    let numForms = authors_pending_confirmation.children('.author').length,
      manager = $('#id_authors_pending_confirmation-TOTAL_FORMS');
    authors_pending_confirmation.append(empty_form([numForms]));
    manager.val(authors_pending_confirmation.children('.author').length);
  }
}

function initCompatibility() {
  $(document).on(
    'click',
    'p.add-app a',
    _pd(function (e) {
      let outer = $(this).closest('form');

      $('tr.app-extra', outer).each(function () {
        addAppRow(this);
      });

      $('.new-apps', outer).toggle();

      $('.new-apps ul').on(
        'click',
        'a',
        _pd(function (e) {
          let $this = $(this),
            sel = format('tr.app-extra td[class="{0}"]', [$this.attr('class')]),
            $row = $(sel, outer);
          $row
            .parents('tr.app-extra')
            .find('input:checkbox')
            .prop('checked', false)
            .closest('tr')
            .removeClass('app-extra');
          $this.closest('li').remove();
          if (!$('tr.app-extra', outer).length) {
            $('p.add-app', outer).hide();
          }
        }),
      );
    }),
  );

  $(document).on(
    'click',
    '.compat-versions .remove',
    _pd(function (e) {
      let $this = $(this),
        $row = $this.closest('tr');
      $row.addClass('app-extra');
      if (!$row.hasClass('app-extra-orig')) {
        $row.find('input:checkbox').prop('checked', true);
      }
      $('p.add-app:hidden', $this.closest('form')).show();
      addAppRow($row);
    }),
  );
}

function imagePoller() {
  this.start = function (override, delay) {
    if (override || !this.poll) {
      this.poll = window.setTimeout(this.check, delay || 1000);
    }
  };
  this.stop = function () {
    window.clearTimeout(this.poll);
    this.poll = null;
  };
}

let imageStatus = {
  start: function () {
    this.icon = new imagePoller();
    this.preview = new imagePoller();
    this.icon.check = function () {
      let self = imageStatus,
        node = $('#edit-addon-media');
      $.getJSON(node.attr('data-checkurl'), function (json) {
        if (json !== null && json.icons) {
          $('#edit-addon-media')
            .find('img')
            .each(function () {
              $(this).attr('src', self.newurl($(this).attr('src')));
            });
          self.icon.stop();
          self.stopping();
        } else {
          self.icon.start(true, 2500);
          self.polling();
        }
      });
    };
    this.preview.check = function () {
      let self = imageStatus;
      $('div.preview-thumb').each(function () {
        check_images(this);
      });
      function check_images(el) {
        let $this = $(el);
        if ($this.hasClass('preview-successful')) {
          return;
        }
        let img = new Image();
        img.onload = function () {
          $this
            .removeClass('preview-error preview-unknown')
            .addClass('preview-successful');
          $this.attr(
            'style',
            'background-image:url(' + self.newurl($this.attr('data-url')) + ')',
          );
          if (!$('div.preview-error').length) {
            self.preview.stop();
            self.stopping();
          }
        };
        img.onerror = function () {
          setTimeout(function () {
            check_images(el);
          }, 2500);
          self.polling();
          $this.attr('style', '').addClass('preview-error');
          img = null;
        };
        img.src = self.newurl($this.attr('data-url'));
      }
    };
    this.icon.start();
    this.preview.start();
  },
  polling: function () {
    if (this.icon.poll || this.preview.poll) {
      let node = $('#edit-addon-media');
      if (!node.find('b.image-message').length) {
        $(
          format('<b class="save-badge image-message">{0}</b>', [
            gettext('Image changes being processed'),
          ]),
        ).appendTo(node.find('h3').first());
      }
    }
  },
  newurl: function (orig) {
    let bst = new Date().getTime();
    orig += (orig.indexOf('?') > 1 ? '&' : '?') + bst;
    return orig;
  },
  cancel: function () {
    this.icon.stop();
    this.preview.stop();
    this.stopping();
  },
  stopping: function () {
    if (!this.icon.poll && !this.preview.poll) {
      $('#edit-addon-media').find('b.image-message').remove();
    }
  },
};

function hideSameSizedIcons() {
  const icon_sizes = [];
  $('#icon_preview_readonly img')
    .show()
    .each(function () {
      const size = $(this).width() + 'x' + $(this).height();
      if ($.inArray(size, icon_sizes) >= 0) {
        $(this).hide();
      }
      icon_sizes.push(size);
    });
}

function addAppRow(obj) {
  let outer = $(obj).closest('form'),
    appClass = $('td.app', obj).attr('class');
  if (!$('.new-apps ul', outer).length) {
    $('.new-apps', outer).html('<ul></ul>');
  }
  let sel = format('.new-apps ul a[class="{0}"]', [appClass]);
  if (!$(sel, outer).length) {
    // Append app to <ul> if it's not already listed.
    let appLabel = $('td.app', obj).text(),
      appHTML =
        '<li><a href="#" class="' + appClass + '">' + appLabel + '</a></li>';
    $('.new-apps ul', outer).append(appHTML);
  }
}

function compatModalCallback(obj) {
  let $widget = this,
    ct = $(obj.click_target),
    form_url = ct.attr('data-updateurl');

  if ($widget.hasClass('ajax-loading')) return;
  $widget.addClass('ajax-loading');
  $widget.load(form_url, function (e) {
    $widget.removeClass('ajax-loading');
  });

  $(document).on('submit', 'form.compat-versions', function (e) {
    e.preventDefault();
    $widget.empty();

    if ($widget.hasClass('ajax-loading')) return;
    $widget.addClass('ajax-loading');

    let widgetForm = $(this);
    $.post(widgetForm.attr('action'), widgetForm.serialize(), function (data) {
      $widget.removeClass('ajax-loading');
      if ($(data).find('.errorlist').length) {
        $widget.html(data);
      } else {
        let c = $(
          '.item[data-addonid=' +
            widgetForm.attr('data-addonid') +
            '] .item-actions li.compat',
        );
        c.load(c.attr('data-src'));
        $widget.hideMe();
      }
    });
  });

  return { pointTo: ct };
}

function initCCLicense() {
  function setCopyright(isCopyr) {
    // Set the license options based on whether the copyright license is selected.
    if (isCopyr) {
      $('.noncc').addClass('disabled');
      // Choose "No" and "No" for the "commercial" and "derivative" questions.
      $(
        'input[name="cc-noncom"][value=1], input[name="cc-noderiv"][value=2]',
      ).prop('checked', true);
    } else {
      $('.noncc').removeClass('disabled');
    }
  }
  function setLicenseFromWizard() {
    let cc_data = $('input[name^="cc-"]:checked')
      .map(function () {
        return this.dataset.cc;
      })
      .get();
    let radio = $(
      '#submit-describe #license-list input[type=radio][data-cc="' +
        cc_data.join(' ') +
        '"]',
    );
    if (radio.length) {
      radio.prop('checked', true);
      return radio;
    }
    cc_data.pop();
    radio = $(
      '#submit-describe #license-list input[type=radio][data-cc="' +
        cc_data.join(' ') +
        '"]',
    );
    if (radio.length) {
      radio.prop('checked', true);
      return radio;
    }
    cc_data.pop();
    radio = $(
      '#submit-describe #license-list input[type=radio][data-cc="' +
        cc_data.join(' ') +
        '"]',
    );
    radio.prop('checked', true);
    return radio;
  }
  function setWizardFromLicense($license) {
    // Update license wizard if license manually selected.
    $('.noncc.disabled').removeClass('disabled');
    $('input[name^="cc-"]').prop('checked', false);
    $('input[name^="cc-"]:not([data-cc]').prop('checked', true);
    _.each($license.data('cc').split(' '), function (cc) {
      $('input[type=radio][name^="cc-"][data-cc="' + cc + '"]').prop(
        'checked',
        true,
      );
      setCopyright(cc == 'copyr');
    });
  }
  function updateLicenseBox($license) {
    if ($license.length) {
      let licenseTxt = $license.data('name');
      let url = $license.next('a');
      if (url.length) {
        licenseTxt = format(
          '<a href="{0}">{1}</a>',
          url.attr('href'),
          licenseTxt,
        );
      }
      let $p = $('#theme-license');
      $p.show()
        .find('#cc-license')
        .html(licenseTxt)
        .attr('class', 'license icon ' + $license.data('cc'));
    }
  }
  function licenseChangeHandler() {
    let $license = $(
      '#submit-describe #license-list input[type=radio][name=license-builtin]:checked',
    );
    if ($license.length) {
      setWizardFromLicense($license);
      updateLicenseBox($license);
    } else {
      $('.noncc').addClass('disabled');
    }
  }

  $('#submit-describe input[name="cc-attrib"]').change(function () {
    setCopyright($('input[name="cc-attrib"]:checked').data('cc') == 'copyr');
  });
  $('#submit-describe input[name^="cc-"]').change(function () {
    let $license = setLicenseFromWizard();
    updateLicenseBox($license);
  });
  $(
    '#submit-describe #license-list input[type=radio][name=license-builtin]',
  ).change(licenseChangeHandler);

  $('#theme-license .select-license').click(
    _pd(function () {
      $('#license-list').toggle();
    }),
  );
  licenseChangeHandler();
}

function initSourceSubmitOutcomes() {
  $('#submit-source #id_has_source input')
    .change(function () {
      $('#option_no_source').hide();
      $('#option_yes_source').hide();
      $('#submit-source #id_has_source input').each(function (index, element) {
        let $radio = $(element);
        if ($radio.val() == 'yes' && $radio.prop('checked')) {
          $('#option_yes_source').show();
          $('#id_source').attr('required', true);
        }
        if ($radio.val() == 'no' && $radio.prop('checked')) {
          $('#option_no_source').show();
          $('#id_source').attr('required', null);
        }
      });
    })
    .change();
  $('#submit-source').submit(function () {
    // Drop the upload if 'no' is selected.
    $('#submit-source #id_has_source input').each(function (index, element) {
      let $radio = $(element);
      if ($radio.val() == 'no' && $radio.prop('checked')) {
        $('#id_source').val('');
      }
    });
  });
  $('#id_source').on('change', validateFileUploadSize);
}

function initSubmitModals() {
  // Called during the submit addon step

  // Hide the primary container of all modals
  $('#modals').hide();

  // Used by "Cancel and disable version" button during submission process
  if ($('#modal-confirm-submission-cancel').length > 0) {
    let $modalForm = $('#modal-confirm-submission-cancel'),
      $modalDelete = $modalForm.modal('.confirm-submission-cancel', {
        width: 400,
      });

    // Submitting the form in the modal is not useful. Instead, after
    // receiving user confirmation, form that contains the
    // "confirm-submission-cancel" button should POST to an alternate URL
    $modalForm.find('form').on('submit', function onSubmit(e) {
      e.preventDefault();

      // this alternate URL is stored in this modal's submit button
      // so change the form action attribute and submit it
      let $confirmButton = $('.confirm-submission-cancel'),
        $mainForm = $confirmButton.closest('form'),
        cancelUrl = $confirmButton.attr('formaction');

      $mainForm.attr('action', cancelUrl);
      $mainForm.trigger('submit');

      return false; // don't follow the a.href link
    });
  }

  // Warn about Android compatibility (if selected).
  if ($('#modal-confirm-android-compatibility').length > 0) {
    let confirmedOnce = false;
    let $input = $('#id_compatible_apps label.android input[type=checkbox]');

    const $modalAndroidConfirm = $(
      '#modal-confirm-android-compatibility',
    ).modal('#id_compatible_apps label.android', {
      width: 525,
      callback: function shouldShowAndroidModal(options) {
        if ($input.prop('disabled')) {
          return false;
        }
        if (confirmedOnce) {
          setTimeout(function () {
            // $().modal() calls preventDefault() before firing the callback
            // but the checkbox is temporarily checked anyway when clicking on
            // it (not the label). To work around this, we wrap our toggling
            // in a setTimeout() to force it to wait for the event to be
            // processed.
            $input.prop('checked', !$input.prop('checked'));
            $input.trigger('change');
          }, 0);
        }
        return !confirmedOnce;
      },
    });

    $('#modal-confirm-android-compatibility')
      .find('form')
      .on('submit', function onSubmit(e) {
        e.preventDefault();
        $input.prop('checked', true);
        $input.trigger('change');
        $modalAndroidConfirm.trigger('close');
        confirmedOnce = true;
      });
  }
}

function initSurveyBanner() {
  const banner = $('#dev-survey-banner');
  const link = $('#dev-survey-banner .survey-link');
  const dismiss = $('#dev-survey-banner .survey-dismiss');
  const responseUrl = banner.attr('response-url');

  link.add(dismiss).on('click', () => {
    $.post(responseUrl);
    banner.hide();
  });
}
