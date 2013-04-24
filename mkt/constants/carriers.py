# -*- coding: utf-8 -*-


class CARRIER(object):
    pass


class UNKNOWN_CARRIER(CARRIER):
    # Used as a dummy.
    id = 0
    name = ''
    slug = 'carrierless'


class TELEFONICA(CARRIER):
    id = 1
    name = u'Telefónica'
    slug = 'telefonica'


class AMERICA_MOVIL(CARRIER):
    id = 2
    name = u'América Móvil'
    slug = 'america_movil'


class CHINA_UNICOM(CARRIER):
    id = 3
    name = u'China Unicom'
    slug = 'china_unicom'


class DEUTCHE_TELEKOM(CARRIER):
    id = 4
    name = u'Deutsche Telekom'
    slug = 'deutsche_telekom'


class ETISALAT(CARRIER):
    id = 5
    name = u'Etisalat'
    slug = 'etisalat'


class HUTCHINSON_THREE_GROUP(CARRIER):
    id = 6
    name = u'Hutchinson Three Group'
    slug = 'hutchinson_three_group'


class KDDI(CARRIER):
    id = 7
    name = u'KDDI'
    slug = 'kddi'


class KT(CARRIER):
    id = 8
    name = u'KT'
    slug = 'kt'


class MEGAFON(CARRIER):
    id = 9
    name = u'MegaFon'
    slug = 'megafon'


class QTEL(CARRIER):
    id = 10
    name = u'Qtel'
    slug = 'qtel'


class SINGTEL(CARRIER):
    id = 11
    name = u'SingTel'
    slug = 'singtel'


class SMART(CARRIER):
    id = 12
    name = u'Smart'
    slug = 'smart'


class SPRINT(CARRIER):
    id = 13
    name = u'Sprint'
    slug = 'sprint'


class TELECOM_ITALIA_GROUP(CARRIER):
    id = 14
    name = u'Telecom Italia Group'
    slug = 'telecom_italia_group'


class TELENOR(CARRIER):
    id = 15
    name = u'Telenor'
    slug = 'telenor'


class TMN(CARRIER):
    id = 16
    name = u'TMN'
    slug = 'tmn'


class VIMPELCOM(CARRIER):
    id = 17
    name = u'VimpelCom'
    slug = 'vimpelcom'


CARRIER_MAP = dict((c.slug, c) for name, c in locals().items() if
                   type(c) is type and c != CARRIER and issubclass(c, CARRIER))
CARRIERS = CARRIER_MAP.values()

CARRIER_IDS = frozenset([c.id for c in CARRIERS])
CARRIER_SLUGS = frozenset([c.slug for c in CARRIERS])
CARRIER_CHOICES = [(c.id, c) for c in CARRIERS]
