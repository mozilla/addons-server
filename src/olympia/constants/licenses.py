from django.utils.translation import ugettext_lazy as _


# Built-in Licenses
class _LicenseBase(object):
    """Base class for built-in licenses."""

    icons = ''  # CSS classes. See zamboni.css for a list.
    some_rights = True
    on_form = True
    creative_commons = True


class LICENSE_COPYRIGHT(_LicenseBase):
    id = 1
    name = _(u'All Rights Reserved')
    icons = 'copyr'
    some_rights = False
    url = None
    builtin = 11


class LICENSE_CC_BY(_LicenseBase):
    id = 2
    name = _(u'Creative Commons Attribution 3.0')
    url = 'http://creativecommons.org/licenses/by/3.0/'
    icons = 'cc-attrib'
    builtin = 12


class LICENSE_CC_BY_NC(_LicenseBase):
    id = 3
    icons = 'cc-attrib cc-noncom'
    name = _(u'Creative Commons Attribution-NonCommercial 3.0')
    url = 'http://creativecommons.org/licenses/by-nc/3.0/'
    builtin = 13


class LICENSE_CC_BY_NC_ND(_LicenseBase):
    id = 4
    icons = 'cc-attrib cc-noncom cc-noderiv'
    name = _(u'Creative Commons Attribution-NonCommercial-NoDerivs 3.0')
    url = 'http://creativecommons.org/licenses/by-nc-nd/3.0/'
    builtin = 14


class LICENSE_CC_BY_NC_SA(_LicenseBase):
    id = 5
    icons = 'cc-attrib cc-noncom cc-share'
    name = _(u'Creative Commons Attribution-NonCommercial-Share Alike 3.0')
    url = 'http://creativecommons.org/licenses/by-nc-sa/3.0/'
    builtin = 15


class LICENSE_CC_BY_ND(_LicenseBase):
    id = 6
    icons = 'cc-attrib cc-noderiv'
    name = _(u'Creative Commons Attribution-NoDerivs 3.0')
    url = 'http://creativecommons.org/licenses/by-nd/3.0/'
    builtin = 16


class LICENSE_CC_BY_SA(_LicenseBase):
    id = 7
    icons = 'cc-attrib cc-share'
    name = _(u'Creative Commons Attribution-ShareAlike 3.0')
    url = 'http://creativecommons.org/licenses/by-sa/3.0/'
    builtin = 17


class LICENSE_COPYRIGHT_AR(_LicenseBase):
    id = 8
    name = _(u'All Rights Reserved')
    icons = 'copyr'
    some_rights = False
    creative_commons = False
    url = None
    builtin = 18


PERSONA_LICENSES = (
    LICENSE_COPYRIGHT,
    LICENSE_CC_BY,
    LICENSE_CC_BY_NC,
    LICENSE_CC_BY_NC_ND,
    LICENSE_CC_BY_NC_SA,
    LICENSE_CC_BY_ND,
    LICENSE_CC_BY_SA,
)
ALL_LICENSES = PERSONA_LICENSES + tuple([LICENSE_COPYRIGHT_AR])
PERSONA_LICENSES_CHOICES = [(l.id, l) for l in PERSONA_LICENSES]
PERSONA_LICENSES_IDS = dict(PERSONA_LICENSES_CHOICES)
LICENSES_BY_BUILTIN = {l.builtin: l for l in ALL_LICENSES}
