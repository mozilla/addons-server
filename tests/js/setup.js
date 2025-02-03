import { vi } from 'vitest';
import $ from 'jquery';
import _ from 'lodash';

// Those objects are available globally in the JS source files.
global.$ = global.jQuery = $;
global._ = _;

// This helper is also available globally. We create a naive implementation for
// testing purposes.
vi.stubGlobal('gettext', (str) => str);

// This is a shared lib that is available everywhere on the site.
const { format, template } = await import('../../static/js/lib/format.js');
global.format = format;
global.template = template;

beforeEach(() => {
  // Completely reset modules so that each import is fresh
  vi.resetModules();
  // Revert or clear existing mocks
  vi.resetAllMocks();
  // Clear out DOM
  document.body.innerHTML = '';
});
