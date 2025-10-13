export default {
  downloads: {
    count: gettext('Downloads'),
  },
  usage: {
    count: gettext('Daily Users'),
  },
  overview: {
    downloads: gettext('Downloads'),
    updates: gettext('Daily Users'),
  },
  apps: {
    '{ec8030f7-c20a-464f-9b0e-13a3a9e97384}': gettext('Firefox'),
    '{86c18b42-e466-45a9-ae7a-9b95ba6f5640}': gettext('Mozilla'),
    '{3550f703-e582-4d05-9a08-453d09bdfdc6}': gettext('Thunderbird'),
    '{718e30fb-e89b-41dd-9da7-e25a45638b28}': gettext('Sunbird'),
    '{92650c4d-4b8e-4d2a-b7eb-24ecf4f6b63a}': gettext('SeaMonkey'),
    '{a23983c0-fd0e-11dc-95ff-0800200c9a66}': gettext('Fennec'),
    '{aa3c5121-dab2-40e2-81ca-7ea25febc110}': gettext('Android'),
  },
  chartTitle: {
    overview: [
      // L10n: {0} is an integer.
      gettext('Downloads and Daily Users, last {0} days'),
      // L10n: both {0} and {1} are dates in YYYY-MM-DD format.
      gettext('Downloads and Daily Users from {0} to {1}'),
    ],
    downloads: [
      // L10n: {0} is an integer.
      gettext('Downloads, last {0} days'),
      // L10n: both {0} and {1} are dates in YYYY-MM-DD format.
      gettext('Downloads from {0} to {1}'),
    ],
    usage: [
      // L10n: {0} is an integer.
      gettext('Daily Users, last {0} days'),
      // L10n: both {0} and {1} are dates in YYYY-MM-DD format.
      gettext('Daily Users from {0} to {1}'),
    ],
    apps: [
      // L10n: {0} is an integer.
      gettext('Applications, last {0} days'),
      // L10n: both {0} and {1} are dates in YYYY-MM-DD format.
      gettext('Applications from {0} to {1}'),
    ],
    countries: [
      // L10n: {0} is an integer.
      gettext('Countries, last {0} days'),
      // L10n: both {0} and {1} are dates in YYYY-MM-DD format.
      gettext('Countries from {0} to {1}'),
    ],
    os: [
      // L10n: {0} is an integer.
      gettext('Platforms, last {0} days'),
      // L10n: both {0} and {1} are dates in YYYY-MM-DD format.
      gettext('Platforms from {0} to {1}'),
    ],
    locales: [
      // L10n: {0} is an integer.
      gettext('Languages, last {0} days'),
      // L10n: both {0} and {1} are dates in YYYY-MM-DD format.
      gettext('Languages from {0} to {1}'),
    ],
    versions: [
      // L10n: {0} is an integer.
      gettext('Add-on Versions, last {0} days'),
      // L10n: both {0} and {1} are dates in YYYY-MM-DD format.
      gettext('Add-on Versions from {0} to {1}'),
    ],
    sources: [
      // L10n: {0} is an integer.
      gettext('Download Sources, last {0} days'),
      // L10n: both {0} and {1} are dates in YYYY-MM-DD format.
      gettext('Download Sources from {0} to {1}'),
    ],
    mediums: [
      // L10n: {0} is an integer.
      gettext('Download Mediums, last {0} days'),
      // L10n: both {0} and {1} are dates in YYYY-MM-DD format.
      gettext('Download Mediums from {0} to {1}'),
    ],
    contents: [
      // L10n: {0} is an integer.
      gettext('Download Contents, last {0} days'),
      // L10n: both {0} and {1} are dates in YYYY-MM-DD format.
      gettext('Download Contents from {0} to {1}'),
    ],
    campaigns: [
      // L10n: {0} is an integer.
      gettext('Download Campaigns, last {0} days'),
      // L10n: both {0} and {1} are dates in YYYY-MM-DD format.
      gettext('Download Campaigns from {0} to {1}'),
    ],
  },
  aggregateLabel: {
    downloads: [
      // L10n: {0} and {1} are integers.
      gettext('<b>{0}</b> in last {1} days'),
      // L10n: {0} is an integer and {1} and {2} are dates in YYYY-MM-DD format.
      gettext('<b>{0}</b> from {1} to {2}'),
    ],
    usage: [
      // L10n: {0} and {1} are integers.
      gettext('<b>{0}</b> average in last {1} days'),
      // L10n: {0} is an integer and {1} and {2} are dates in YYYY-MM-DD format.
      gettext('<b>{0}</b> from {1} to {2}'),
    ],
  },
};
