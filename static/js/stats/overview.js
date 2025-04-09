import $ from 'jquery';
import _ from 'underscore';
import Highcharts from 'highcharts';
import './topchart';
import { normalizeRange } from './dateutils';
import { format } from '../lib/format';
import csv_keys from './csv_keys';
import { StatsManager } from './manager';

// This function is called once we have stats data and we get aggregates for
// daily users and weekly downloads.
export const stats_overview_make_handler = function ({ view }) {
  const range = normalizeRange(view.range);

  return function (data) {
    if (data.empty) {
      $('#downloads-in-range, #users-in-range').text(
        gettext('No data available.'),
      );
    } else {
      // make all that data pretty.
      var aggregateRow = data[data.firstIndex].data,
        totalDownloads = Highcharts.numberFormat(aggregateRow.downloads, 0),
        totalUsers = Highcharts.numberFormat(aggregateRow.updates, 0),
        startString = range.start.iso(),
        endString = range.end.iso(),
        downloadFormat,
        userFormat;

      // Trim end date by one day if custom range.
      if (view.range.custom) {
        const msDay = 24 * 60 * 60 * 1000; // One day in milliseconds.
        endString = new Date(range.end.getTime() - msDay).iso();
      }

      if (typeof view.range == 'string') {
        (downloadFormat = csv_keys.aggregateLabel.downloads[0]),
          (userFormat = csv_keys.aggregateLabel.usage[0]);
        $('#downloads-in-range').html(
          format(downloadFormat, totalDownloads, parseInt(view.range, 10)),
        );
        $('#users-in-range').html(
          format(userFormat, totalUsers, parseInt(view.range, 10)),
        );
      } else {
        (downloadFormat = csv_keys.aggregateLabel.downloads[1]),
          (userFormat = csv_keys.aggregateLabel.usage[1]);
        $('#downloads-in-range').html(
          format(downloadFormat, totalDownloads, startString, endString),
        );
        $('#users-in-range').html(
          format(userFormat, totalUsers, startString, endString),
        );
      }
    }
    $('.two-up').removeClass('loading');
  };
};

// `$` is passed by jQuery itself when calling `jQuery(stats_overview)`.
export const stats_overview = function () {
  console.debug('overview:stats_overview:init');
  if ($('.primary').attr('data-report') != 'overview') {
    return;
  }

  // set up topcharts (defined in topchart.js)
  $('.toplist').topChart();

  $(window).on('changeview', function (e, view) {
    console.debug('overview:window:changeview', view);
    $('.two-up').addClass('loading');
  });

  // Save some requests by waiting until the graph data is ready.
  $(window).on('dataready', function (e, data) {
    const view = _.extend({}, data.view, { group: 'all' });

    // Get aggregates for Daily Users and Downloads for the given time range.
    $.when(StatsManager.getDataRange(view)).then(
      stats_overview_make_handler({ view }),
    );
  });
};
