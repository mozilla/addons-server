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
    url = 'https://www.mozilla.org/MPL/2.0/'
    builtin = 1
    slug = 'MPL-2.0'


class LICENSE_APACHE2(_LicenseBase):
    name = _('Apache License 2.0')
    url = 'https://spdx.org/licenses/Apache-2.0.html'
    builtin = 2
    slug = 'Apache-2.0'


class LICENSE_GPL2(_LicenseBase):
    name = _('GNU General Public License v2.0 only')
    url = 'https://spdx.org/licenses/GPL-2.0-only.html'
    builtin = 3
    slug = 'GPL-2.0-only'


class LICENSE_GPL3(_LicenseBase):
    name = _('GNU General Public License v3.0 only')
    url = 'https://spdx.org/licenses/GPL-3.0-only.html'
    builtin = 4
    slug = 'GPL-3.0-only'


class LICENSE_LGPL2(_LicenseBase):
    name = _('GNU Lesser General Public License v2.1 only')
    url = 'https://spdx.org/licenses/LGPL-2.1-only.html'
    builtin = 5
    slug = 'LGPL-2.1-only'


class LICENSE_LGPL3(_LicenseBase):
    name = _('GNU Lesser General Public License v3.0 only')
    url = 'https://spdx.org/licenses/LGPL-3.0-only.html'
    builtin = 6
    slug = 'LGPL-3.0-only'


class LICENSE_AGPL3(_LicenseBase):
    name = _('GNU Affero General Public License v3.0 only')
    url = 'https://spdx.org/licenses/AGPL-3.0-only.html'
    builtin = 7
    slug = 'AGPL-3.0-only'


class LICENSE_MIT(_LicenseBase):
    name = _('MIT License')
    url = 'https://spdx.org/licenses/MIT.html'
    builtin = 8
    slug = 'MIT'


class LICENSE_ISC(_LicenseBase):
    name = _('ISC License')
    url = 'https://spdx.org/licenses/ISC.html'
    builtin = 9
    slug = 'ISC'


class LICENSE_BSD(_LicenseBase):
    name = _('BSD 2-Clause "Simplified" License')
    url = 'https://spdx.org/licenses/BSD-2-Clause.html'
    builtin = 10
    slug = 'BSD-2-Clause'


class LICENSE_MPL1(_LicenseBase):
    name = _('Mozilla Public License 1.1')
    url = 'https://www.mozilla.org/MPL/MPL-1.1.html'
    builtin = 11
    slug = 'MPL-1.1'
    on_form = False  # obsolete and unavailable for selection


class LICENSE_CC_COPYRIGHT(_LicenseBase):
    name = _('All Rights Reserved')
    icons = 'copyr'
    url = None
    builtin = 12
    creative_commons = True
    slug = 'cc-all-rights-reserved'


class LICENSE_CC_BY30(_LicenseBase):
    name = _('Creative Commons Attribution 3.0')
    icons = 'cc-attrib'
    url = 'https://creativecommons.org/licenses/by/3.0/'
    builtin = 13
    creative_commons = True
    slug = 'CC-BY-3.0'
    on_form = False


class LICENSE_CC_BY_NC30(_LicenseBase):
    name = _('Creative Commons Attribution-NonCommercial 3.0')
    icons = 'cc-attrib cc-noncom'
    url = 'https://creativecommons.org/licenses/by-nc/3.0/'
    builtin = 14
    creative_commons = True
    slug = 'CC-BY-NC-3.0'
    on_form = False


class LICENSE_CC_BY_NC_ND30(_LicenseBase):
    name = _('Creative Commons Attribution-NonCommercial-NoDerivs 3.0')
    icons = 'cc-attrib cc-noncom cc-noderiv'
    url = 'https://creativecommons.org/licenses/by-nc-nd/3.0/'
    builtin = 15
    creative_commons = True
    slug = 'CC-BY-NC-ND-3.0'
    on_form = False


class LICENSE_CC_BY_NC_SA30(_LicenseBase):
    name = _('Creative Commons Attribution-NonCommercial-Share Alike 3.0')
    icons = 'cc-attrib cc-noncom cc-share'
    url = 'https://creativecommons.org/licenses/by-nc-sa/3.0/'
    builtin = 16
    creative_commons = True
    slug = 'CC-BY-NC-SA-3.0'
    on_form = False


class LICENSE_CC_BY_ND30(_LicenseBase):
    name = _('Creative Commons Attribution-NoDerivs 3.0')
    icons = 'cc-attrib cc-noderiv'
    url = 'https://creativecommons.org/licenses/by-nd/3.0/'
    builtin = 17
    creative_commons = True
    slug = 'CC-BY-ND-3.0'
    on_form = False


class LICENSE_CC_BY_SA30(_LicenseBase):
    name = _('Creative Commons Attribution-ShareAlike 3.0')
    icons = 'cc-attrib cc-share'
    url = 'https://creativecommons.org/licenses/by-sa/3.0/'
    builtin = 18
    creative_commons = True
    slug = 'CC-BY-SA-3.0'
    on_form = False


class LICENSE_CC_BY40(_LicenseBase):
    name = _('Creative Commons Attribution 4.0')
    icons = 'cc-attrib'
    url = 'https://creativecommons.org/licenses/by/4.0/'
    builtin = 19
    creative_commons = True
    slug = 'CC-BY-4.0'
    on_form = True


class LICENSE_CC_BY_NC40(_LicenseBase):
    name = _('Creative Commons Attribution-NonCommercial 4.0')
    icons = 'cc-attrib cc-noncom'
    url = 'https://creativecommons.org/licenses/by-nc/4.0/'
    builtin = 20
    creative_commons = True
    slug = 'CC-BY-NC-4.0'
    on_form = True


class LICENSE_CC_BY_NC_ND40(_LicenseBase):
    name = _('Creative Commons Attribution-NonCommercial-NoDerivs 4.0')
    icons = 'cc-attrib cc-noncom cc-noderiv'
    url = 'https://creativecommons.org/licenses/by-nc-nd/4.0/'
    builtin = 21
    creative_commons = True
    slug = 'CC-BY-NC-ND-4.0'
    on_form = True


class LICENSE_CC_BY_NC_SA40(_LicenseBase):
    name = _('Creative Commons Attribution-NonCommercial-Share Alike 4.0')
    icons = 'cc-attrib cc-noncom cc-share'
    url = 'https://creativecommons.org/licenses/by-nc-sa/4.0/'
    builtin = 22
    creative_commons = True
    slug = 'CC-BY-NC-SA-4.0'
    on_form = True


class LICENSE_CC_BY_ND40(_LicenseBase):
    name = _('Creative Commons Attribution-NoDerivs 4.0')
    icons = 'cc-attrib cc-noderiv'
    url = 'https://creativecommons.org/licenses/by-nd/4.0/'
    builtin = 23
    creative_commons = True
    slug = 'CC-BY-ND-4.0'
    on_form = True


class LICENSE_CC_BY_SA40(_LicenseBase):
    name = _('Creative Commons Attribution-ShareAlike 4.0')
    icons = 'cc-attrib cc-share'
    url = 'https://creativecommons.org/licenses/by-sa/4.0/'
    builtin = 24
    creative_commons = True
    slug = 'CC-BY-SA-4.0'
    on_form = True


class LICENSE_UNLICENSE(_LicenseBase):
    name = _('The Unlicense')
    url = 'https://spdx.org/licenses/Unlicense.html'
    builtin = 25
    slug = 'Unlicense'


class LICENSE_COPYRIGHT_AR(_LicenseBase):
    name = _('All Rights Reserved')
    icons = 'copyr'
    url = None
    builtin = 26
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
    LICENSE_CC_BY30,
    LICENSE_CC_BY_NC30,
    LICENSE_CC_BY_NC_ND30,
    LICENSE_CC_BY_NC_SA30,
    LICENSE_CC_BY_ND30,
    LICENSE_CC_BY_SA30,
    LICENSE_CC_BY40,
    LICENSE_CC_BY_NC40,
    LICENSE_CC_BY_NC_ND40,
    LICENSE_CC_BY_NC_SA40,
    LICENSE_CC_BY_ND40,
    LICENSE_CC_BY_SA40,
    LICENSE_COPYRIGHT_AR,
    LICENSE_APACHE2,
    LICENSE_AGPL3,
    LICENSE_ISC,
    LICENSE_UNLICENSE,
)
LICENSES_BY_BUILTIN = {license.builtin: license for license in ALL_LICENSES}
CC_LICENSES = {
    license.builtin: license for license in ALL_LICENSES if license.creative_commons
}
LICENSES_BY_SLUG = {license.slug: license for license in ALL_LICENSES if license.slug}
FORM_LICENSES = {
    license.builtin: license for license in ALL_LICENSES if license.on_form
}
