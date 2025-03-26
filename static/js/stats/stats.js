import _ from 'underscore';

import { capabilities as originalCapabilities } from '../zamboni/capabilities';
import { normalizeRange } from './dateutils';

// Modify the URL when the page state changes, if the browser supports
// pushState.
function updateQueryParams(view) {
  let queryParams = {};

  if (view.range) {
    if (typeof range == 'string') {
      queryParams.last = range.split(/\s+/)[0];
    }
  }

  queryParams = $.param(queryParams);

  if (queryParams) {
    history.replaceState(view, document.title, '?' + queryParams);
  }
}

function updateExportLinks({ metric, range }) {
  const normalizedRange = normalizeRange(range);

  // See: https://github.com/mozilla/zamboni/commit/4263102
  if (
    typeof range === 'string' ||
    (range.custom && typeof normalizedRange.end === 'object')
  ) {
    normalizedRange.end = new Date(
      normalizedRange.end.getTime() - 24 * 60 * 60 * 1000,
    );
  }

  const baseUrl = $('.primary').attr('data-base_url');
  const params = [
    metric,
    'day',
    normalizedRange.start.pretty(''),
    normalizedRange.end.pretty(''),
  ];

  const url = `${baseUrl}${params.join('-')}`;

  $('#export_data_csv').attr('href', url + '.csv');
  $('#export_data_json').attr('href', url + '.json');
}

// `$` is passed by jQuery itself when calling `jQuery(stats_stats)`.
export const stats_stats = (storage = null, capabilities = {}) => {
  // Set up initial default view.
  const view = {
    metric: $('.primary').attr('data-report'),
    range: $('.primary').attr('data-range') || '30 days',
    group: 'day',
  };

  if (capabilities.localStorage && storage) {
    const ssView = JSON.parse(storage.getItem('stats_view'));

    const combinedView = Object.entries({
      ...view,
      ...(ssView || {}),
    }).reduce((acc, [key, val]) => {
      acc[key] = typeof val === 'string' ? _.escape(val) : val;
      return acc;
    }, {});

    view.range = combinedView.range;
    view.group = combinedView.group;
  }

  // Set side nav active state.
  const sel = `#side-nav li.${view.metric}, #side-nav li[data-report=${view.metric}]`;
  $(sel).addClass('active');

  // set up notes modal.
  $('#stats-note').modal('#stats-note-link', { width: 520 });

  // set up stats exception modal.
  const $exceptionModal = $('#exception-note').modal('', { width: 250 });
  $(window).on('explain-exception', function () {
    $exceptionModal.render();
  });

  $('.csv-table').csvTable();

  $(window).on('changeview', (event, view) => {
    if (capabilities.replaceState) {
      updateQueryParams(view);
    }
    updateExportLinks(view);
    if (storage) {
      storage.setItem(
        'stats_view',
        JSON.stringify({
          range: view.range,
          group: view.group,
        }),
      );
    }
  });

  // Trigger the initial data load.
  $(window).trigger('changeview', view);
};

if (typeof module === 'undefined') {
  stats_stats(window.sessionStorage, originalCapabilities);
}
