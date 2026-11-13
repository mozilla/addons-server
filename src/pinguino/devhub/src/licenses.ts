// Mirrors src/olympia/constants/licenses.py.
export interface LicenseChoice {
  slug: string;
  name: string;
  url?: string;
}

export const EXTENSION_LICENSES: LicenseChoice[] = [
  {
    slug: 'MPL-2.0',
    name: 'Mozilla Public License 2.0',
    url: 'https://www.mozilla.org/MPL/2.0/',
  },
  {
    slug: 'Apache-2.0',
    name: 'Apache License 2.0',
    url: 'https://spdx.org/licenses/Apache-2.0.html',
  },
  {
    slug: 'GPL-2.0-only',
    name: 'GNU General Public License v2.0 only',
    url: 'https://spdx.org/licenses/GPL-2.0-only.html',
  },
  {
    slug: 'GPL-3.0-only',
    name: 'GNU General Public License v3.0 only',
    url: 'https://spdx.org/licenses/GPL-3.0-only.html',
  },
  {
    slug: 'LGPL-2.1-only',
    name: 'GNU Lesser General Public License v2.1 only',
    url: 'https://spdx.org/licenses/LGPL-2.1-only.html',
  },
  {
    slug: 'LGPL-3.0-only',
    name: 'GNU Lesser General Public License v3.0 only',
    url: 'https://spdx.org/licenses/LGPL-3.0-only.html',
  },
  {
    slug: 'AGPL-3.0-only',
    name: 'GNU Affero General Public License v3.0 only',
    url: 'https://spdx.org/licenses/AGPL-3.0-only.html',
  },
  {
    slug: 'MIT',
    name: 'MIT License',
    url: 'https://spdx.org/licenses/MIT.html',
  },
  {
    slug: 'ISC',
    name: 'ISC License',
    url: 'https://spdx.org/licenses/ISC.html',
  },
  {
    slug: 'BSD-2-Clause',
    name: 'BSD 2-Clause "Simplified" License',
    url: 'https://spdx.org/licenses/BSD-2-Clause.html',
  },
  {
    slug: 'Unlicense',
    name: 'The Unlicense',
    url: 'https://spdx.org/licenses/Unlicense.html',
  },
  { slug: 'all-rights-reserved', name: 'All Rights Reserved' },
];

export const THEME_LICENSES: LicenseChoice[] = [
  {
    slug: 'CC-BY-4.0',
    name: 'Creative Commons Attribution 4.0',
    url: 'https://creativecommons.org/licenses/by/4.0/',
  },
  {
    slug: 'CC-BY-NC-4.0',
    name: 'Creative Commons Attribution-NonCommercial 4.0',
    url: 'https://creativecommons.org/licenses/by-nc/4.0/',
  },
  {
    slug: 'CC-BY-NC-ND-4.0',
    name: 'Creative Commons Attribution-NonCommercial-NoDerivs 4.0',
    url: 'https://creativecommons.org/licenses/by-nc-nd/4.0/',
  },
  {
    slug: 'CC-BY-NC-SA-4.0',
    name: 'Creative Commons Attribution-NonCommercial-Share Alike 4.0',
    url: 'https://creativecommons.org/licenses/by-nc-sa/4.0/',
  },
  {
    slug: 'CC-BY-ND-4.0',
    name: 'Creative Commons Attribution-NoDerivs 4.0',
    url: 'https://creativecommons.org/licenses/by-nd/4.0/',
  },
  {
    slug: 'CC-BY-SA-4.0',
    name: 'Creative Commons Attribution-ShareAlike 4.0',
    url: 'https://creativecommons.org/licenses/by-sa/4.0/',
  },
  { slug: 'cc-all-rights-reserved', name: 'All Rights Reserved' },
];
