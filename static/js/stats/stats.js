import $ from 'jquery';
import _ from 'underscore';
// Import $.modal
import '../zamboni/global';
// import $.csvTable
import './table';
import { normalizeRange } from './dateutils';
import { capabilities } from '../zamboni/capabilities';

export function stats_stats(injectedSessionStorage) {
  let internalSessionStorage = injectedSessionStorage || window.sessionStorage;

  // Modify the URL when the page state changes, if the browser supports
  // pushState.
  if (capabilities.replaceState) {
    $(window).on('changeview', function (e, view) {
      let queryParams = {};
      let range = view.range;

      if (range) {
        if (typeof range == 'string') {
          queryParams.last = range.split(/\s+/)[0];
        }
      }

      queryParams = $.param(queryParams);

      if (queryParams) {
        history.replaceState(view, document.title, '?' + queryParams);
      }
    });
  }

  // Set up initial default view.
  let initView = {
    metric: $('.primary').attr('data-report'),
    range: $('.primary').attr('data-range') || '30 days',
    group: 'day',
  };

  // Set side nav active state.
  (function () {
    let sel = '#side-nav li.' + initView.metric;
    sel += ', #side-nav li[data-report=' + initView.metric + ']';

    $(sel).addClass('active');
  })();

  // Restore any session view information from internalSessionStorage.
  if (
    capabilities.localStorage &&
    internalSessionStorage.getItem('stats_view')
  ) {
    let ssView = JSON.parse(internalSessionStorage.getItem('stats_view'));

    // The stored range is either a string or an object.
    if (ssView.range && typeof ssView.range === 'object') {
      let objRange = ssView.range;
      Object.keys(objRange).forEach(function (key) {
        let val = objRange[key];
        if (typeof val === 'string') {
          objRange[key] = _.escape(val);
        }
      });
      initView.range = objRange;
    } else {
      initView.range = _.escape(ssView.range || initView.range);
    }

    initView.group = _.escape(ssView.group || initView.group);
  }

  // Update internalSessionStorage with our current view state.
  (function () {
    if (!capabilities.localStorage) {
      return;
    }

    let ssView = _.clone(initView);
    $(window).on('changeview', function (e, newView) {
      _.extend(ssView, newView);
      internalSessionStorage.setItem(
        'stats_view',
        JSON.stringify({
          range: ssView.range,
          group: ssView.group,
        }),
      );
    });
  })();

  // Update the "Export as CSV" link when the view changes.
  (function () {
    let view = {},
      baseURL = $('.primary').attr('data-base_url');

    $(window).on('changeview', function (e, newView) {
      _.extend(view, newView);
      let metric = view.metric;

      let range = normalizeRange(view.range);

      // See: https://github.com/mozilla/zamboni/commit/4263102
      if (
        typeof view.range === 'string' ||
        (view.range.custom && typeof range.end === 'object')
      ) {
        range.end = new Date(range.end.getTime() - 24 * 60 * 60 * 1000);
      }

      let url =
        baseURL +
        [metric, 'day', range.start.pretty(''), range.end.pretty('')].join('-');

      $('#export_data_csv').attr('href', url + '.csv');
      $('#export_data_json').attr('href', url + '.json');
    });
  })();

  // set up notes modal.
  $('#stats-note').modal('#stats-note-link', { width: 520 });

  // set up stats exception modal.
  let $exceptionModal = $('#exception-note').modal('', { width: 250 });
  $(window).on('explain-exception', function () {
    $exceptionModal.render();
  });

  $('.csv-table').csvTable();

  // Trigger the initial data load.
  $(window).trigger('changeview', initView);
}
