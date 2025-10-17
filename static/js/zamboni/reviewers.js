import $ from 'jquery';
import _ from 'underscore';
import { _pd } from '../lib/prevent-default';
import { Storage } from '../zamboni/storage';
import { b64toBlob } from './helpers';
import { validateFileUploadSize } from './global';
import { format } from '../lib/format';
import { z } from '../zamboni/z';
import { capabilities } from '../zamboni/capabilities';

$(document).ready(function () {
  if ($('.daily-message').length) {
    initDailyMessage();
  }

  let show_comments = function (e) {
    e.preventDefault();
    let $me = $(e.target);
    $me.hide();
    $me.next().show();
    $me.parents('tr').next().show();
  };

  let hide_comments = function (e) {
    e.preventDefault();
    let $me = $(e.target);
    $me.hide();
    $me.prev().show();
    $me.parents('tr').next().hide();
  };

  $('a.show').click(show_comments);
  $('a.hide').click(hide_comments);

  if ($('#review-actions').length > 0) {
    initReviewActions();
  }

  if ($('#extra-review-actions').length) {
    initExtraReviewActions();
  }

  if ($('.all-backgrounds').length) {
    initBackgroundImagesForTheme();
  }

  if (
    $('#scroll_sidebar').length &&
    !$('body.mobile, body.tablet').length &&
    !capabilities.mobile
  ) {
    initScrollingSidebar();
  }

  if ($('#addon-queue').length) {
    initQueue();
  }

  if ($('.version-adu').length > 0) {
    initVersionsADU();
  }

  if ($('.review-held-action-form').length > 0) {
    let comments_field = $('.review-held-action-form #id_comments');
    let choices = $('.review-held-action-form #id_choice input');

    choices.click(function () {
      if ($('.review-held-action-form #id_choice input:checked').val() == 'cancel') {
        comments_field.attr('disabled', false);
      } else {
        comments_field.attr('disabled', true);
      }
    })
  }

  // Show add-on ID when icon is clicked
  if ($('#addon[data-id], #persona[data-id]').length) {
    $('#addon .icon').click(function () {
      window.location.hash = 'id=' + $('#addon, #persona').attr('data-id');
    });
  }

  if ($('#addon-queue-filter-form').length) {
    let filter_form = $('#addon-queue-filter-form form')[0];

    $('#addon-queue-filter-form button').click(function () {
      if (filter_form.hidden) {
        filter_form.hidden = false;
      } else {
        filter_form.hidden = true;
      }
    });
    if (
      $('#addon-queue-filter-form input[type="checkbox"]').length ==
      $('#addon-queue-filter-form input[type="checkbox"]:checked').length
    ) {
      filter_form.hidden = true;
    }

    $('#addon-queue-filter-form .select-all').click(function (e) {
      e.preventDefault();
      $('#addon-queue-filter-form input[type="checkbox"]').prop(
        'checked',
        true,
      );
    });
    $('#addon-queue-filter-form .select-none').click(function (e) {
      e.preventDefault();
      $('#addon-queue-filter-form input[type="checkbox"]').prop(
        'checked',
        false,
      );
    });
  }

  let policySelectionInputs = $('.review-actions-policies-select input[name="cinder_policies"]');
  policySelectionInputs.change((event) => {
    let checkbox = event.target;
    $("#policy-text-" + checkbox.value)[0].hidden = !checkbox.checked;
  });
  policySelectionInputs.trigger("click").trigger("click");

});

function initReviewActions() {
  function showForm(element, pageload) {
    let $element = $(element),
      value = $element.find('input').val(),
      $data_toggle = $('form.review-form').find('.data-toggle'),
      $data_toggle_hide = $('form.review-form').find('.data-toggle-hide'),
      $comments = $('#id_comments'),
      boilerplate_text = $element.find('input').attr('data-value');

    pageload = pageload || false;
    $element.closest('.review-actions').addClass('on');
    $('.review-actions .action_nav #id_action > *').removeClass('on-tab');
    $element.find('input').prop('checked', true);

    // Input message into empty comments textbox.
    if ($comments.val().length === 0 && boilerplate_text) {
      insertAtCursor($comments, boilerplate_text);
    }
    $element.addClass('on-tab');

    if (pageload) {
      $('#review-actions-form').show();
    } else {
      $('#review-actions-form').slideDown();
      $('#review-actions').find('.errorlist').remove();
    }

    // Hide everything, then show the ones containing the value we're interested in.
    $data_toggle.hide().prop('disabled', true);
    $data_toggle.parent('label').hide();
    $data_toggle
      .filter('[data-value~="' + value + '"]')
      .show()
      .prop('disabled', false);
    $data_toggle
      .filter('[data-value~="' + value + '"]')
      .parent('label')
      .show();
    // For data_toggle_hide, the opposite - show everything, then hide the ones containing
    // the value we're interested in.
    $data_toggle_hide.show().prop('disabled', false);
    $data_toggle_hide.parent('label').show();
    $data_toggle_hide
      .filter('[data-value~="' + value + '"]')
      .hide()
      .prop('disabled', true);
    $data_toggle_hide
      .filter('[data-value~="' + value + '"]')
      .parent('label')
      .hide();

    showHideDelayedRejectionDateWidget();
  }

  function showHideDelayedRejectionDateWidget() {
    var delayed_rejection_input = $(
      '#id_delayed_rejection input[name=delayed_rejection]:checked',
    );
    console.log(delayed_rejection_input);
    var delayed_rejection_date_widget = $('#id_delayed_rejection_date');
    if (delayed_rejection_input.prop('value') == 'True') {
      delayed_rejection_date_widget.prop('disabled', false);
    } else {
      delayed_rejection_date_widget.prop('disabled', true);
    }
  }

  $('#id_delayed_rejection input[name=delayed_rejection]').change(
    showHideDelayedRejectionDateWidget,
  );

  $('#review-actions .action_nav #id_action > *:not(.disabled)').click(
    function () {
      showForm(this);
    },
  );

  let review_checked = $('#review-actions [name=action]:checked');
  if (review_checked.length > 0) {
    showForm(review_checked.parentsUntil('#id_action', 'div'), true);
  }

  /* Review action reason stuff */
  $('.review-actions-reasons-select input').change(function () {
    const cannedResponse = this.dataset.value;
    if (cannedResponse.length) {
      if (this.checked) {
        insertAtCursor($('#id_comments'), cannedResponse);
      } else {
        // Attempt to remove the canned response related to the reason.
        $('#id_comments').val(
          $('#id_comments').val().replace(cannedResponse, ''),
        );
      }
    }
  });

  /* Install Triggers */

  // IT IS TOTALLY UNCLEAR WHERE THESE VALUES ARE SET.
  $('.files .install').click(
    _pd(function () {
      let $this = $(this),
        installer = $this.is('[data-type="search-tools"]')
          ? z.installSearch
          : z.installAddon;
      installer($this.text(), $this.attr('href'), '');
    }),
  );

  /* Who's currently on this page? */

  function check_currently_viewing() {
    const addon_id = $('#addon').data('id');
    const url = $('#addon').data('url');
    const $current = $('.currently_viewing_warning');

    const updateWarning = (title) => {
      let $current_div = $current.filter('div');
      $current_div.find('strong').remove();
      $current_div.prepend($('<strong>', { text: title }));
    };

    $.post(url, { addon_id: addon_id }, (d) => {
      const show = d.is_user != 1 && typeof d.current_name != 'undefined';

      $current.toggle(show);
      if (show) {
        let title;
        if (d.is_user == 2) {
          /* 2 is when the editor has reached the lock limit */
          title = d.current_name;
        } else {
          title = format(gettext('{name} was viewing this page first.'), {
            name: d.current_name,
          });
        }
        updateWarning(title);
      }
    }).fail(() => {
      $current.toggle(true);
      updateWarning(gettext('Review page polling failed.'));
    });
  }
  if (!(capabilities.localStorage && window.localStorage.dont_poll)) {
    check_currently_viewing();
    const interval = $('#addon').data('review-viewing-interval');
    setInterval(check_currently_viewing, interval * 1000);
  }

  /* Item History */
  $('.review-files tr.listing-header').click(function () {
    $(this).next('tr.listing-body').toggle();
  });

  let storage = Storage(),
    eh_setting = storage.get('reviewers_history'),
    eh_els = $('#history .review-files tr.listing-body'),
    eh_size = eh_els.length;
  if (!eh_setting) eh_setting = 3;

  toggleHistory();

  function toggleHistory() {
    eh_els.slice(eh_size - eh_setting, eh_setting).show();
    eh_els.slice(0, eh_size - eh_setting).hide();
  }

  $('.eh_open').click(
    _pd(function () {
      eh_setting = $(this).attr('data-num');
      storage.set('reviewers_history', eh_setting);
      toggleHistory();
      highlightHistory();
    }),
  );

  function highlightHistory() {
    $('#history a').removeClass('on');
    $(format('#history a[data-num="{0}"]', eh_setting)).addClass('on');
  }
  highlightHistory();

  $('.review-resolve-abuse-reports .select-all').click(function (e) {
    e.preventDefault();
    $('.review-resolve-abuse-reports input[type="checkbox"]').prop(
      'checked',
      true,
    );
  });
  $('.review-resolve-abuse-reports .select-none').click(function (e) {
    e.preventDefault();
    $('.review-resolve-abuse-reports input[type="checkbox"]').prop(
      'checked',
      false,
    );
  });
  $('.review-resolve-abuse-reports .expand-all').click(function (e) {
    e.preventDefault();
    $('.review-resolve-abuse-reports details').prop(
      'open',
      true,
    );
  });
   $('.review-resolve-abuse-reports .collapse-all').click(function (e) {
    e.preventDefault();
     $('.review-resolve-abuse-reports details').prop(
      'open',
      false,
    );
  });
}

function callReviewersAPI(apiUrl, method, data, successCallback) {
  let sessionId = $('form.more-actions').data('session-id');
  if (data) {
    data = JSON.stringify(data);
  }
  $.ajax({
    url: apiUrl,
    data: data,
    type: method,
    beforeSend: function (xhr) {
      xhr.setRequestHeader('Authorization', 'Session ' + sessionId);
    },
    processData: false,
    contentType: 'application/json',
    success: successCallback,
  });
}

$('#id_attachment_file').on('change', validateFileUploadSize);

function initExtraReviewActions() {
  /* Inline actions that should trigger a XHR and modify the form element
   * accordingly.
   */
  // Checkbox-style actions. Only for subscribe/unsubscribe.
  $('#notify_new_listed_versions').click(
    _pd(function () {
      let $input = $(this).prop('disabled', true); // Prevent double-send.
      let checked = !$input.prop('checked'); // It's already changed.
      let apiUrl;
      if (checked) {
        apiUrl = $input.data('api-url-unsubscribe-listed');
      } else {
        apiUrl = $input.data('api-url-subscribe-listed');
      }
      callReviewersAPI(apiUrl, 'post', null, function () {
        $input.prop('disabled', false);
        $input.prop('checked', !checked);
      });
    }),
  );

  $('#notify_new_unlisted_versions').click(
    _pd(function () {
      let $input = $(this).prop('disabled', true); // Prevent double-send.
      let checked = !$input.prop('checked'); // It's already changed.
      let apiUrl;
      if (checked) {
        apiUrl = $input.data('api-url-unsubscribe-unlisted');
      } else {
        apiUrl = $input.data('api-url-subscribe-unlisted');
      }
      callReviewersAPI(apiUrl, 'post', null, function () {
        $input.prop('disabled', false);
        $input.prop('checked', !checked);
      });
    }),
  );

  $('#due_date_update').on(
    'change',
    _pd(function () {
      $('#submit_due_date_update').removeClass('disabled');
    }),
  );

  $('#submit_due_date_update').on(
    'click',
    _pd(function () {
      $(this).addClass('disabled');
      let $input = $('#due_date_update').prop('disabled', true); // Prevent double-send.
      let apiUrl = $input.data('api-url');
      let data = { due_date: $input.val(), version: $input.data('api-data') };
      callReviewersAPI(apiUrl, 'post', data, function (response) {
        $input.prop('disabled', false);
      });
    }),
  );

  const showToggleWrapper = () => {
    $(
      '#attachment_input_wrapper, #attachment_file_wrapper, #attachment_back',
    ).addClass('hidden');
    $('#attachment-type-toggle').removeClass('hidden');
    $('#id_attachment_file, #id_attachment_input').val('');
  };
  const showFileWrapper = (e) => {
    e?.preventDefault();
    $('#attachment-type-toggle, #attachment_input_wrapper').addClass('hidden');
    $('#attachment_file_wrapper, #attachment_back').removeClass('hidden');
  };
  const showInputWrapper = (e) => {
    e?.preventDefault();
    $('#attachment-type-toggle, #attachment_file_wrapper').addClass('hidden');
    $('#attachment_input_wrapper, #attachment_back').removeClass('hidden');
  };

  $('#id_attachment_file').prop('files')?.length && showFileWrapper();
  $('#id_attachment_input').val() && showInputWrapper();
  $('#attachment_back').on('click', showToggleWrapper);
  $('#toggle_attachment_file').on('click', showFileWrapper);
  $('#toggle_attachment_input').on('click', showInputWrapper);

  // One-off-style buttons.
  $('.more-actions button.oneoff[data-api-url]').click(
    _pd(function () {
      let $button = $(this).prop('disabled', true); // Prevent double-send.
      let apiUrl = $button.data('api-url');
      let data = $button.data('api-data') || null;
      let method = $button.data('api-method') || 'post';
      callReviewersAPI(apiUrl, method, data, function (response) {
        $button.remove();
      });
    }),
  );

  // Toggle-style buttons.
  $('.more-actions button.toggle[data-api-url]').click(
    _pd(function () {
      let $button = $(this).prop('disabled', true); // Prevent double-send.
      let $other_button = $($button.data('toggle-button-selector'));
      let apiUrl = $button.data('api-url');
      let data = $button.data('api-data') || null;
      let method = $button.data('api-method') || 'post';
      callReviewersAPI(apiUrl, method, data, function () {
        $button.prop('disabled', false).parents('li').addClass('hidden').hide();
        $other_button.parents('li').removeClass('hidden').show();
      });
    }),
  );
}

function initBackgroundImagesForTheme() {
  function rollOverInit(e) {
    if (!e.target.complete) return;
    let $target = $(e.target);
    $target.attr('height', e.target.naturalHeight);
    $target.attr('width', e.target.naturalWidth);
    $target.parent().zoomBox();
  }

  function loadBackgroundImages($parent_element) {
    let url = $parent_element.data('backgrounds-url');
    if (!url) return;
    let xhr = new XMLHttpRequest();
    xhr.open('GET', url);
    xhr.responseType = 'json';
    // load the image as a blob so we can treat it as a File
    xhr.onload = function () {
      const jsonResponse = xhr.response,
        loop_len = Object.keys(jsonResponse).length;
      let loop_count = 0;
      $.each(jsonResponse, function (background_filename, background_b64) {
        loop_count++;
        let blob = b64toBlob(background_b64),
          imageUrl = window.URL.createObjectURL(blob);
        let $div_element = $('<div>')
          .addClass('background zoombox')
          .appendTo($parent_element);
        let $img_element = $('<img>')
          .attr('src', imageUrl)
          .attr('width', '1000')
          .attr('height', '200')
          .appendTo($div_element);
        let span_content = document.createTextNode(
          format('Background file {0} of {1} - {2}', [
            loop_count,
            loop_len,
            background_filename,
          ]),
        );
        $('<span>').append(span_content).appendTo($div_element);
        $img_element.on('load', rollOverInit).trigger('load');
      });
    };
    xhr.send();
  }

  loadBackgroundImages($('div.all-backgrounds'));
}

function insertAtCursor(textarea, text) {
  let area = $(textarea)[0],
    scrollPos = area.scrollTop;
  // IE
  if (document.selection) {
    area.focus();
    let rng = document.selection.createRange();
    rng.text = text + rng.text;
    // FF/Safari/Chrome
  } else if (area.selectionStart || area.selectionStart == '0') {
    area.focus();
    let startPos = area.selectionStart;
    area.value =
      area.value.substring(0, startPos) +
      text +
      area.value.substring(startPos, area.value.length);
    area.setSelectionRange(startPos + text.length, startPos + text.length);
    // everything else - append text to end
  } else {
    area.value += text;
  }
  // restore scrollbar location
  area.scrollTop = scrollPos;
}

function initDailyMessage(doc) {
  let $motd = $('.daily-message', doc),
    storage = Storage();
  if ($('#editor-motd', doc).length) {
    // The message on the MOTD page should never be closable, so don't
    // show close button nor attach handlers.
    return;
  }
  $motd.find('.close').show();
  if (storage.get('motd_closed') != $('p', $motd).text()) {
    // You haven't read this spam yet? Here, I have something to show you.
    $motd.show();
  }
  $motd.find('.close').click(function (e) {
    e.stopPropagation();
    storage.set('motd_closed', $('.daily-message p').text());
    $motd.slideUp();
  });
}

function initQueue() {
  let $q = $('#addon-queue[data-url]');
  if (!$q.length) {
    return;
  }

  let url = $q.attr('data-url');
  let addon_ids = $.map($('.addon-row'), function (el) {
    return $(el).attr('data-addon');
  });
  if (!('localStorage' in window && window.localStorage.dont_poll)) {
    (function checkCurrentlyViewing() {
      $.get(url, { addon_ids: addon_ids.join(',') }, function (data) {
        $('#addon-queue .locked').removeClass('locked').prop('title', '');
        $.each(data, function (k, v) {
          $('#addon-' + k)
            .addClass('locked')
            .attr(
              'title',
              format(gettext('{name} was viewing this add-on first.'), {
                name: v,
              }),
            );
        });
        setTimeout(checkCurrentlyViewing, 2000);
      });
    })();
  }

  let pop = $('#popup-notes').hide(),
    loadNotes = function (e) {
      let addon_id = $(e.click_target).closest('tr').attr('data-addon');
      pop.html(gettext('Loading&hellip;'));
      $.get(pop.attr('data-version-url') + addon_id, function (data) {
        pop.html('');
        let empty = true;
        if (data.release_notes) {
          pop.append($('<strong>', { text: gettext('Version Notes') }));
          pop.append(
            $('<div>', { class: 'version-notes', text: data.release_notes }),
          );
          empty = false;
        }
        if (data.approval_notes) {
          pop.append($('<strong>', { text: gettext('Notes for Reviewers') }));
          pop.append(
            $('<div>', { class: 'version-notes', text: data.approval_notes }),
          );
          empty = false;
        }
        if (empty) {
          pop.append($('<em>', { text: gettext('No version notes found') }));
        }
      });
      return true;
    },
    loadReview = function (e) {
      let addon_id = $(e.click_target).closest('tr').attr('data-review-log');
      pop.html(gettext('Loading&hellip;'));
      $.get(pop.attr('data-review-url') + addon_id, function (data) {
        pop.html('');
        let empty = true;
        if (data.reviewtext) {
          pop.append($('<strong>', { text: gettext('Review Text') }));
          pop.append(
            $('<div>', { class: 'version-notes', text: data.reviewtext }),
          );
          empty = false;
        }
        if (empty) {
          pop.append($('<em>', { text: gettext('Review notes found') }));
        }
      });
      return true;
    };

  $('.addon-version-notes a').each(function (i, el) {
    $(pop).popup(el, { pointTo: el, callback: loadNotes, width: 500 });
  });

  $('.addon-review-text a').each(function (i, el) {
    $(pop).popup(el, { pointTo: el, callback: loadReview, width: 500 });
  });
}

function initScrollingSidebar() {
  let $window = $(window),
    $sb = $('#scroll_sidebar'),
    addon_top = $('#addon').offset().top,
    current_state = false;

  function setSticky(state) {
    if (state == current_state) return;
    current_state = state;
    $sb.toggleClass('sticky', state);
  }

  $window.scroll(
    _.throttle(function () {
      setSticky(window.scrollY > addon_top);
    }, 20),
  );
}

function initVersionsADU() {
  function fillVersionsTable(versionAduPairs) {
    versionAduPairs.forEach(([version, adu]) => {
      $(
        format(
          '.version-adu[data-version-string="{0}"] .version-adu-value',
          version,
        ),
      ).text(adu);
    });
    let missingAduText;
    const queryLimit = $('#addon').data('versions-adu-max-results');
    if (versionAduPairs.length === queryLimit) {
      // if we've got max results we may have hit the limit of the query
      const [_, min_adu] = versionAduPairs[queryLimit - 1];
      missingAduText = format('<= {0}', min_adu);
    } else {
      // otherwise these are just 0 ADU versions
      missingAduText = '0';
    }
    $('.version-adu-value:contains("\u2014")').text(missingAduText);
  }

  function fillTopTenBox(versionAduPairs) {
    const review_version_url = $('#addon').data('review-version-url');

    versionAduPairs.slice(0, 10).forEach(([version, adu]) => {
      const versionEntryId = '#version-' + version.replaceAll('.', '_');
      let versionLink;
      if ($(versionEntryId).length) {
        versionLink = format(
          '<a href="{0}">\u2B07&nbsp;{1}</a>',
          versionEntryId,
          version,
        );
      } else {
        versionLink = format(
          '<a href="{0}">\u2794&nbsp;{1}</a>',
          review_version_url.replace('__', version),
          version,
        );
      }
      $('#version-adu-top-ten ol').append(
        format('<li>{0}: {1}</li>', versionLink, adu),
      );
    });
    if (!versionAduPairs.length) {
      $('#version-adu-top-ten div').append(
        'No average daily user values found.',
      );
    }
  }

  function loadVersionsADU() {
    const aduUrl = $('#addon').data('versions-adu-url');
    $.get(aduUrl, function (data) {
      const versionAduPairs = data.adus;
      if (versionAduPairs !== undefined) {
        fillVersionsTable(versionAduPairs);
        fillTopTenBox(versionAduPairs);
      } else {
        $('#version-adu-top-ten div').append(
          'No average daily user values because BigQuery disabled.',
        );
      }
    });
  }
  loadVersionsADU();
}
