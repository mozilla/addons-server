from olympia.amo.enum import EnumChoices


class PROMOTED_GROUP_CHOICES(EnumChoices):
    RECOMMENDED = 1, 'Recommended'
    LINE = 4, 'By Firefox'
    SPOTLIGHT = 5, 'Spotlight'
    STRATEGIC = 6, 'Strategic'
    NOTABLE = 7, 'Notable'
    SPONSORED = 8, 'Sponsored'
    VERIFIED = 9, 'Verified'
    PARTNER = 10, 'Partner'
