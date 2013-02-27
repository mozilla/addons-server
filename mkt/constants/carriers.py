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
    name = 'Telefónica'
    slug = 'telefonica'


class AMERICA_MOVIL(CARRIER):
    id = 2
    name = 'América Móvil'
    slug = 'america_movil'


class CHINA_UNICOM(CARRIER):
    id = 3
    name = 'China Unicom'
    slug = 'china_unicom'


class DEUTCHE_TELEKOM(CARRIER):
    id = 4
    name = 'Deutsche Telekom'
    slug = 'deutsche_telekom'


class ETISALAT(CARRIER):
    id = 5
    name = 'Etisalat'
    slug = 'etisalat'


class HUTCHINSON_THREE_GROUP(CARRIER):
    id = 6
    name = 'Hutchinson Three Group'
    slug = 'hutchinson_three_group'


class KDDI(CARRIER):
    id = 7
    name = 'KDDI'
    slug = 'kddi'


class KT(CARRIER):
    id = 8
    name = 'KT'
    slug = 'kt'


class MEGAFON(CARRIER):
    id = 9
    name = 'MegaFon'
    slug = 'megafon'


class QTEL(CARRIER):
    id = 10
    name = 'Qtel'
    slug = 'qtel'


class SINGTEL(CARRIER):
    id = 11
    name = 'SingTel'
    slug = 'singtel'


class SMART(CARRIER):
    id = 12
    name = 'Smart'
    slug = 'smart'


class SPRINT(CARRIER):
    id = 13
    name = 'Sprint'
    slug = 'sprint'


class TELECOM_ITALIA_GROUP(CARRIER):
    id = 14
    name = 'Telecom Italia Group'
    slug = 'telecom_italia_group'


class TELENOR(CARRIER):
    id = 15
    name = 'Telenor'
    slug = 'telenor'


class TMN(CARRIER):
    id = 16
    name = 'TMN'
    slug = 'tmn'


class VIMPELCOM(CARRIER):
    id = 17
    name = 'VimpelCom'
    slug = 'vimpelcom'


CARRIERS = filter(
    lambda c: isinstance(c, CARRIER) and type(c) is not CARRIER, locals())
CARRIER_IDS = frozenset([c.id for c in CARRIERS])
