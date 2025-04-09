import './stats/csv_keys';
import './stats/helpers';
import './stats/dateutils';
import './stats/manager';
import './stats/controls';
import { stats_overview } from './stats/overview';
import './stats/topchart';
import './stats/chart';
import './stats/table';
import { stats_stats } from './stats/stats';
import { capabilities } from './zamboni/capabilities';

// Initialize the stats module.
stats_stats(window.sessionStorage, capabilities);
stats_overview();
