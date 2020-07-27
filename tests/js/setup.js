require('jest-date-mock');

// Those objects are available globally in the JS source files.
global.$ = global.jQuery = require('jquery');
global._ = require('lodash');

// This helper is also available globally. We create a naive implementation for
// testing purposes.
global.gettext = (str) => str;
