(function (jQuery, window) {
  'use strict';

  // `$` is passed by jQuery itself when calling `jQuery(stats_stats)`.
  var stats_stats = function ($, injectedSessionStorage) {
    var internalSessionStorage =
      injectedSessionStorage || window.sessionStorage;

    // Modify the URL when the page state changes, if the browser supports
    // pushState.
    if (z.capabilities.replaceState) {
      $(window).on('changeview', function (e, view) {
        var queryParams = {};
        var range = view.range;

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
    var initView = {
      metric: $('.primary').attr('data-report'),
      range: $('.primary').attr('data-range') || '30 days',
      group: 'day',
    };

    // Set side nav active state.
    (function () {
      var sel = '#side-nav li.' + initView.metric;
      sel += ', #side-nav li[data-report=' + initView.metric + ']';

      $(sel).addClass('active');
    })();

    // Restore any session view information from internalSessionStorage.
    if (
      z.capabilities.localStorage &&
      internalSessionStorage.getItem('stats_view')
    ) {
      var ssView = JSON.parse(internalSessionStorage.getItem('stats_view'));

      // The stored range is either a string or an object.
      if (ssView.range && typeof ssView.range === 'object') {
        var objRange = ssView.range;
        Object.keys(objRange).forEach(function (key) {
          var val = objRange[key];
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
      if (!z.capabilities.localStorage) {
        return;
      }

      var ssView = _.clone(initView);
      $(window).on('changeview', function (e, newView) {
        _.extend(ssView, newView);
        internalSessionStorage.setItem(
          'stats_view',
          JSON.stringify({
            range: ssView.range,
            group: ssView.group,
          })
        );
      });
    })();

    // Update the "Export as CSV" link when the view changes.
    (function () {
      var view = {},
        baseURL = $('.primary').attr('data-base_url');

      $(window).on('changeview', function (e, newView) {
        _.extend(view, newView);
        var metric = view.metric;

        var range = normalizeRange(view.range);

        // See: https://github.com/mozilla/zamboni/commit/4263102
        if (
          typeof view.range === 'string' ||
          (view.range.custom && typeof range.end === 'object')
        ) {
          range.end = new Date(range.end.getTime() - 24 * 60 * 60 * 1000);
        }

        var url =
          baseURL +
          [metric, 'day', range.start.pretty(''), range.end.pretty('')].join(
            '-'
          );

        $('#export_data_csv').attr('href', url + '.csv');
        $('#export_data_json').attr('href', url + '.json');
      });
    })();

    // set up notes modal.
    $('#stats-note').modal('#stats-note-link', { width: 520 });

    // set up stats exception modal.
    var $exceptionModal = $('#exception-note').modal('', { width: 250 });
    $(window).on('explain-exception', function () {
      $exceptionModal.render();
    });

    $('.csv-table').csvTable();

    // Trigger the initial data load.
    $(window).trigger('changeview', initView);
  };

  if (typeof module !== 'undefined' && typeof module.exports !== 'undefined') {
    module.exports.stats_stats = stats_stats;
  } else {
    jQuery(stats_stats);
  }
})(jQuery, window);
