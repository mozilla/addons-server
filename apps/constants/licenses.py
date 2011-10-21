from lib.licenses import license_text
from tower import ugettext_lazy as _


# Built-in Licenses
class _LicenseBase(object):
    """Base class for built-in licenses."""
    shortname = None
    icons = None     # CSS classes. See zamboni.css for a list.
    linktext = None  # Link text distinct from full license name.
    on_form = True

    @classmethod
    def text(cls):
        return cls.shortname and license_text(cls.shortname) or None


class LICENSE_COPYRIGHT(_LicenseBase):
    id = 7
    name = _(u'All Rights Reserved')
    url = None
    shortname = None
    icons = ('copyr',)
    on_form = False


class LICENSE_CC_BY_NC_SA(_LicenseBase):
    id = 8
    name = _(u'Creative Commons Attribution-NonCommercial-Share Alike 3.0')
    linktext = _(u'Some rights reserved')
    url = 'http://creativecommons.org/licenses/by-nc-sa/3.0/'
    shortname = None
    icons = ('cc-attrib', 'cc-noncom', 'cc-share')
    on_form = False


# TODO(cvan): Need migrations for these licenses.
class LICENSE_CC_BY(_LicenseBase):
    id = 9
    name = _(u'Creative Commons Attribution 3.0')
    linktext = _(u'Some rights reserved')
    url = 'http://creativecommons.org/licenses/by/3.0/'
    shortname = None
    icons = ('cc-attrib',)
    on_form = False


class LICENSE_CC_BY_NC(_LicenseBase):
    id = 10
    name = _(u'Creative Commons Attribution-NonCommercial 3.0')
    linktext = _(u'Some rights reserved')
    url = 'http://creativecommons.org/licenses/by-nc/3.0/'
    shortname = None
    icons = ('cc-attrib', 'cc-noncom')
    on_form = False


class LICENSE_CC_BY_NC_ND(_LicenseBase):
    id = 11
    name = _(u'Creative Commons Attribution-NonCommercial-NoDerivs 3.0')
    linktext = _(u'Some rights reserved')
    url = 'http://creativecommons.org/licenses/by-nc-nd/3.0/'
    shortname = None
    icons = ('cc-attrib', 'cc-noncom', 'cc-noderiv')
    on_form = False


class LICENSE_CC_BY_ND(_LicenseBase):
    id = 12
    name = _(u'Creative Commons Attribution-NoDerivs 3.0')
    linktext = _(u'Some rights reserved')
    url = 'http://creativecommons.org/licenses/by-nd/3.0/'
    shortname = None
    icons = ('cc-attrib', 'cc-noderiv')
    on_form = False


class LICENSE_CC_BY_SA(_LicenseBase):
    id = 13
    name = _(u'Creative Commons Attribution-ShareAlike 3.0')
    linktext = _(u'Some rights reserved')
    url = 'http://creativecommons.org/licenses/by-sa/3.0/'
    shortname = None
    icons = ('cc-attrib', 'cc-share')
    on_form = False


PERSONA_LICENSES = (LICENSE_CC_BY, LICENSE_CC_BY_NC,
                    LICENSE_CC_BY_NC_ND, LICENSE_CC_BY_NC_SA, LICENSE_CC_BY_ND,
                    LICENSE_CC_BY_SA)

PERSONA_LICENSES = (LICENSE_COPYRIGHT,) + PERSONA_LICENSES
PERSONA_LICENSES_IDS = [(l.id, l) for l in PERSONA_LICENSES]
