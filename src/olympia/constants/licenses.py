from django.utils.translation import gettext_lazy as _


# Built-in Licenses
class _LicenseBase:
    """Base class for built-in licenses."""

    icons = ''  # CSS classes. See zamboni.css for a list.
    on_form = True
    creative_commons = False
    # slugs should be taken from https://spdx.org/licenses/


class LICENSE_MPL2(_LicenseBase):
    name = _('Mozilla Public License 2.0')
    url = 'http://www.mozilla.org/MPL/2.0/'
    builtin = 1
    slug = 'MPL-2.0'


class LICENSE_GPL2(_LicenseBase):
    name = _('GNU General Public License v2.0')
    url = 'http://www.gnu.org/licenses/gpl-2.0.html'
    builtin = 2
    slug = 'GPL-2.0-or-later'


class LICENSE_GPL3(_LicenseBase):
    name = _('GNU General Public License v3.0')
    url = 'http://www.gnu.org/licenses/gpl-3.0.html'
    builtin = 3
    slug = 'GPL-3.0-or-later'


class LICENSE_LGPL2(_LicenseBase):
    name = _('GNU Library General Public License v2.1')
    url = 'http://www.gnu.org/licenses/lgpl-2.1.html'
    builtin = 4
    slug = 'LGPL-2.1-or-later'


class LICENSE_LGPL3(_LicenseBase):
    name = _('GNU Library General Public License v3.0')
    url = 'http://www.gnu.org/licenses/lgpl-3.0.html'
    builtin = 5
    slug = 'LGPL-3.0-or-later'


class LICENSE_MIT(_LicenseBase):
    name = _('The MIT License')
    url = 'http://www.opensource.org/licenses/mit-license.php'
    builtin = 6
    slug = 'MIT'


class LICENSE_BSD(_LicenseBase):
    name = _('The BSD License')
    url = 'http://www.opensource.org/licenses/bsd-license.php'
    builtin = 7
    slug = 'BSD-2-Clause'


# builtin 8, 9 aren't used in any current versions, and aren't available for selection.


class LICENSE_MPL1(_LicenseBase):
    name = _('Mozilla Public License 1.1')
    url = 'http://www.mozilla.org/MPL/MPL-1.1.html'
    builtin = 10
    slug = 'MPL-1.1'
    on_form = False  # obsolete and unavailable for selection


class LICENSE_CC_COPYRIGHT(_LicenseBase):
    name = _('All Rights Reserved')
    icons = 'copyr'
    url = None
    builtin = 11
    creative_commons = True
    slug = 'cc-all-rights-reserved'


class LICENSE_CC_BY(_LicenseBase):
    name = _('Creative Commons Attribution 3.0')
    icons = 'cc-attrib'
    url = 'http://creativecommons.org/licenses/by/3.0/'
    builtin = 12
    creative_commons = True
    slug = 'CC-BY-3.0'


class LICENSE_CC_BY_NC(_LicenseBase):
    name = _('Creative Commons Attribution-NonCommercial 3.0')
    icons = 'cc-attrib cc-noncom'
    url = 'http://creativecommons.org/licenses/by-nc/3.0/'
    builtin = 13
    creative_commons = True
    slug = 'CC-BY-NC-3.0'


class LICENSE_CC_BY_NC_ND(_LicenseBase):
    name = _('Creative Commons Attribution-NonCommercial-NoDerivs 3.0')
    icons = 'cc-attrib cc-noncom cc-noderiv'
    url = 'http://creativecommons.org/licenses/by-nc-nd/3.0/'
    builtin = 14
    creative_commons = True
    slug = 'CC-BY-NC-ND-3.0'


class LICENSE_CC_BY_NC_SA(_LicenseBase):
    name = _('Creative Commons Attribution-NonCommercial-Share Alike 3.0')
    icons = 'cc-attrib cc-noncom cc-share'
    url = 'http://creativecommons.org/licenses/by-nc-sa/3.0/'
    builtin = 15
    creative_commons = True
    slug = 'CC-BY-NC-SA-3.0'


class LICENSE_CC_BY_ND(_LicenseBase):
    name = _('Creative Commons Attribution-NoDerivs 3.0')
    icons = 'cc-attrib cc-noderiv'
    url = 'http://creativecommons.org/licenses/by-nd/3.0/'
    builtin = 16
    creative_commons = True
    slug = 'CC-BY-ND-3.0'


class LICENSE_CC_BY_SA(_LicenseBase):
    name = _('Creative Commons Attribution-ShareAlike 3.0')
    icons = 'cc-attrib cc-share'
    url = 'http://creativecommons.org/licenses/by-sa/3.0/'
    builtin = 17
    creative_commons = True
    slug = 'CC-BY-SA-3.0'


class LICENSE_COPYRIGHT_AR(_LicenseBase):
    name = _('All Rights Reserved')
    icons = 'copyr'
    url = None
    builtin = 18
    slug = 'all-rights-reserved'


ALL_LICENSES = (
    LICENSE_MPL1,
    LICENSE_MPL2,
    LICENSE_GPL2,
    LICENSE_GPL3,
    LICENSE_LGPL2,
    LICENSE_LGPL3,
    LICENSE_MIT,
    LICENSE_BSD,
    LICENSE_CC_COPYRIGHT,
    LICENSE_CC_BY,
    LICENSE_CC_BY_NC,
    LICENSE_CC_BY_NC_ND,
    LICENSE_CC_BY_NC_SA,
    LICENSE_CC_BY_ND,
    LICENSE_CC_BY_SA,
    LICENSE_COPYRIGHT_AR,
)
LICENSES_BY_BUILTIN = {license.builtin: license for license in ALL_LICENSES}
CC_LICENSES = {
    license.builtin: license for license in ALL_LICENSES if license.creative_commons
}
LICENSES_BY_SLUG = {license.slug: license for license in ALL_LICENSES if license.slug}
