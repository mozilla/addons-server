const dateMock = require('jest-date-mock');

describe(__filename, () => {
  const defaultBaseUrl = 'http://example.org/';

  // This should be global to all stats files.
  beforeEach(() => {
    // Mock mandatory jQuery plugins.
    $.prototype.modal = jest.fn();
    $.prototype.csvTable = jest.fn();
    $.prototype.datepicker = () => ({ datepicker: jest.fn() });
    $.datepicker = { setDefaults: jest.fn() };

    global.z = {
      SessionStorage: jest.fn(),
      Storage: jest.fn(),
      capabilities: {},
    };

    global._pd = (func) => {
      return function (e) {
        e.preventDefault();
        func.apply(this, arguments);
      };
    };
  });

  afterEach(() => {
    dateMock.clear();
  });

  describe('stats/stats.js', () => {
    const report = 'apps';

    let stats_stats;

    beforeEach(() => {
      stats_stats =
        require('../../../static/js/zamboni/stats-all.js').stats_stats;
    });

    describe('export links', () => {
      const createMinimalHTML = ({
        baseUrl = defaultBaseUrl,
        range = '',
        report = 'some-report',
      }) => {
        return `
<div
  class="primary"
  data-report="${report}"
  data-base_url="${baseUrl}"
  data-range="${range}"
>
  <a href="" id="export_data_csv">export csv</a>
  <a href="" id="export_data_json">export json</a>
</div>`;
      };

      beforeEach(() => {
        const date = new Date(2019, 10 - 1, 14);
        dateMock.advanceTo(date);
      });

      it('constructs the export URLs for the last 7 days', () => {
        const report = 'apps';
        document.body.innerHTML = createMinimalHTML({
          range: 'last 7 days',
          report,
        });

        stats_stats(global.$);

        expect($('#export_data_csv').attr('href')).toEqual(
          `${defaultBaseUrl}${report}-day-20191007-20191013.csv`,
        );
        expect($('#export_data_json').attr('href')).toEqual(
          `${defaultBaseUrl}${report}-day-20191007-20191013.json`,
        );
      });

      it('constructs the export URLs for the last 30 days by default', () => {
        const report = 'apps';
        document.body.innerHTML = createMinimalHTML({ range: '', report });

        stats_stats(global.$);

        expect($('#export_data_csv').attr('href')).toEqual(
          `${defaultBaseUrl}${report}-day-20190914-20191013.csv`,
        );
        expect($('#export_data_json').attr('href')).toEqual(
          `${defaultBaseUrl}${report}-day-20190914-20191013.json`,
        );
      });

      it('constructs the export URLs for a custom range', () => {
        const report = 'countries';
        document.body.innerHTML = createMinimalHTML({ report });
        // Custom range is persisted in session storage.
        global.z.capabilities.localStorage = true;
        const statsView = {
          group: 'day',
          range: {
            custom: true,
            start: Date.UTC(2019, 11 - 1, 15),
            // When loading the page, 1 day is added to the `range.end` date so
            // we have to substract it when creating the export links.
            end: Date.UTC(2019, 11 - 1, 25 + 1),
          },
        };
        const fakeSessionStorage = {
          getItem: () => JSON.stringify(statsView),
          setItem: jest.fn(),
        };

        stats_stats(global.$, fakeSessionStorage);

        expect($('#export_data_csv').attr('href')).toEqual(
          `${defaultBaseUrl}${report}-day-20191115-20191125.csv`,
        );
        expect($('#export_data_json').attr('href')).toEqual(
          `${defaultBaseUrl}${report}-day-20191115-20191125.json`,
        );
      });
    });
  });

  describe('stats/overview.js', () => {
    let stats_overview_make_handler;

    beforeEach(() => {
      const stats_all = require('../../../static/js/zamboni/stats-all.js');

      stats_overview_make_handler = stats_all.stats_overview_make_handler;
    });

    describe('"in-range" dates', () => {
      const createMinimalHTML = () => {
        return `
<div class="primary" data-report="overview">
  <div id="downloads-in-range"></div>
  <div id="users-in-range"></div>
</div>`;
      };

      beforeEach(() => {
        document.body.innerHTML = createMinimalHTML();
      });

      it('handles empty data', () => {
        const view = {
          group: 'all',
          metric: 'overview',
          range: '30 days',
        };

        const data = { empty: true };

        stats_overview_make_handler({ view })(data);

        expect($('#downloads-in-range').text()).toEqual('No data available.');
        expect($('#users-in-range').text()).toEqual('No data available.');
      });

      it('displays the correct information for a predefined range', () => {
        const view = {
          group: 'all',
          metric: 'overview',
          range: '7 days',
        };
        const downloads = 12;
        const users = 456;
        const data = {
          empty: false,
          firstIndex: '2020-09-01',
          '2020-09-01': {
            data: {
              downloads,
              updates: users, // not sure why it's named `updates` here...
            },
          },
        };

        stats_overview_make_handler({ view })(data);

        expect($('#downloads-in-range').text()).toEqual(
          `${downloads} in last 7 days`,
        );
        expect($('#users-in-range').text()).toEqual(
          `${users} average in last 7 days`,
        );
      });

      it('displays the correct dates for a custom range', () => {
        const view = {
          group: 'all',
          metric: 'overview',
          range: {
            custom: true,
            start: Date.UTC(2019, 11 - 1, 15),
            // When loading the page, 1 day is added to the `range.end` date so
            // we have to substract it later in overview code...
            end: Date.UTC(2019, 11 - 1, 25 + 1),
          },
        };
        const downloads = 12;
        const users = 456;
        const data = {
          empty: false,
          firstIndex: '2020-09-01',
          '2020-09-01': {
            data: {
              downloads,
              updates: users, // not sure why it's named `updates` here...
            },
          },
        };

        stats_overview_make_handler({ view })(data);

        expect($('#downloads-in-range').text()).toEqual(
          `${downloads} from 2019-11-15 to 2019-11-25`,
        );
        expect($('#users-in-range').text()).toEqual(
          `${users} from 2019-11-15 to 2019-11-25`,
        );
      });
    });
  });
});
