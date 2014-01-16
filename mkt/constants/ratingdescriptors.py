from tower import ugettext_lazy as _lazy


# WARNING: When adding a new rating descriptor here also include a migration.
#          All descriptor keys must be prefixed by the rating body (e.g. USK_).
#
# These are used to dynamically generate the field list for the
# RatingDescriptors Django model in mkt.webapps.models.
RATING_DESCS = {
    'CLASSIND_CRIMINAL_ACTS': {'name': _lazy('Criminal Acts')},
    'CLASSIND_DRUGS': {'name': _lazy('Drugs')},
    'CLASSIND_DRUGS_ILLEGAL': {'name': _lazy('Illegal Drugs')},
    'CLASSIND_DRUGS_LEGAL': {'name': _lazy('Legal Drugs')},
    # L10n: `Language` as in foul language.
    'CLASSIND_LANG': {'name': _lazy('Inappropriate Language')},
    'CLASSIND_NO_DESCS': {'name': _lazy('No Descriptors')},
    'CLASSIND_NUDITY': {'name': _lazy('Nudity')},
    # L10n: `Sex` as in sexual, not as in gender.
    'CLASSIND_SEX': {'name': _lazy('Sex')},
    'CLASSIND_SEX_CONTENT': {'name': _lazy('Sexual Content')},
    'CLASSIND_SEX_EXPLICIT': {'name': _lazy('Explicit Sex')},
    'CLASSIND_SHOCKING': {'name': _lazy('Impacting Content')},
    'CLASSIND_VIOLENCE': {'name': _lazy('Violence')},
    'CLASSIND_VIOLENCE_EXTREME': {'name': _lazy('Extreme Violence')},

    'ESRB_ALCOHOL_REF': {'name': _lazy('Alcohol Reference')},
    'ESRB_ALCOHOL_TOBACCO_REF': {'name': _lazy('Alcohol and Tobacco Reference')},
    'ESRB_ALCOHOL_TOBACCO_USE': {'name': _lazy('Use of Alcohol and Tobacco')},
    'ESRB_ALCOHOL_USE': {'name': _lazy('Use of Alcohol')},
    'ESRB_BLOOD': {'name': _lazy('Blood')},
    'ESRB_BLOOD_GORE': {'name': _lazy('Blood and Gore')},
    'ESRB_COMIC_MISCHIEF': {'name': _lazy('Comic Mischief')},
    'ESRB_CRIME': {'name': _lazy('Crime')},
    'ESRB_CRIME_INSTRUCT': {'name': _lazy('Criminal Instruction')},
    'ESRB_CRUDE_HUMOR': {'name': _lazy('Crude Humor')},
    'ESRB_DRUG_ALCOHOL_REF': {'name': _lazy('Drug and Alcohol Reference')},
    'ESRB_DRUG_ALCOHOL_TOBACCO_REF': {'name': _lazy('Drug, Alcohol, and Tobacco Reference')},
    'ESRB_DRUG_ALCOHOL_TOBACCO_USE': {'name': _lazy('Use of Drug, Alcohol, and Tobacco')},
    'ESRB_DRUG_ALCOHOL_USE': {'name': _lazy('Use of Drug and Alcohol')},
    'ESRB_DRUG_REF': {'name': _lazy('Drug Reference')},
    'ESRB_DRUG_TOBACCO_REF': {'name': _lazy('Drug and Tobacco Reference')},
    'ESRB_DRUG_TOBACCO_USE': {'name': _lazy('Use of Drug and Tobacco')},
    'ESRB_DRUG_USE': {'name': _lazy('Use of Drugs')},
    'ESRB_FANTASY_VIOLENCE': {'name': _lazy('Fantasy Violence')},
    'ESRB_HATE_SPEECH': {'name': _lazy('Hate Speech')},
    'ESRB_INTENSE_VIOLENCE': {'name': _lazy('Intense Violence')},
    # L10n: `Language` as in foul language.
    'ESRB_LANG': {'name': _lazy('Language')},
    'ESRB_MILD_BLOOD': {'name': _lazy('Mild Blood')},
    'ESRB_MILD_FANTASY_VIOLENCE': {'name': _lazy('Mild Fantasy Violence')},
    'ESRB_MILD_LANG': {'name': _lazy('Mild Language')},
    'ESRB_MILD_VIOLENCE': {'name': _lazy('Mild Violence')},
    'ESRB_NO_DESCS': {'name': _lazy('No Descriptors')},
    'ESRB_NUDITY': {'name': _lazy('Nudity')},
    'ESRB_PARTIAL_NUDITY': {'name': _lazy('Partial Nudity')},
    'ESRB_REAL_GAMBLING': {'name': _lazy('Real Gambling')},
    'ESRB_SCARY': {'name': _lazy('Scary Themes')},
    'ESRB_SEX_CONTENT': {'name': _lazy('Sexual Content')},
    'ESRB_SEX_THEMES': {'name': _lazy('Sexual Themes')},
    'ESRB_SIM_GAMBLING': {'name': _lazy('Simulated Gambling')},
    'ESRB_STRONG_LANG': {'name': _lazy('Strong Language')},
    'ESRB_STRONG_SEX_CONTENT': {'name': _lazy('Strong Sexual Content')},
    'ESRB_SUGGESTIVE': {'name': _lazy('Suggestive Themes')},
    'ESRB_TOBACCO_REF': {'name': _lazy('Tobacco Reference')},
    'ESRB_TOBACCO_USE': {'name': _lazy('Use of Tobacco')},
    'ESRB_VIOLENCE': {'name': _lazy('Violence')},
    'ESRB_VIOLENCE_REF': {'name': _lazy('Violence References')},

    'GENERIC_DISCRIMINATION': {'name': _lazy('Discrimination')},
    'GENERIC_DRUGS': {'name': _lazy('Drugs')},
    'GENERIC_GAMBLING': {'name': _lazy('Gambling')},
    # L10n: `Language` as in foul language.
    'GENERIC_LANG': {'name': _lazy('Language')},
    'GENERIC_NO_DESCS': {'name': _lazy('No Descriptors')},
    'GENERIC_ONLINE': {'name': _lazy('Online')},
    'GENERIC_SCARY': {'name': _lazy('Fear')},
    # L10n: `Sex` as in sexual, not as in gender.
    'GENERIC_SEX_CONTENT': {'name': _lazy('Sex')},
    'GENERIC_VIOLENCE': {'name': _lazy('Violence')},

    'PEGI_DISCRIMINATION': {'name': _lazy('Discrimination')},
    'PEGI_DRUGS': {'name': _lazy('Drugs')},
    'PEGI_GAMBLING': {'name': _lazy('Gambling')},
    # L10n: `Language` as in foul language.
    'PEGI_LANG': {'name': _lazy('Language')},
    'PEGI_NO_DESCS': {'name': _lazy('No Descriptors')},
    'PEGI_ONLINE': {'name': _lazy('Online')},
    'PEGI_SCARY': {'name': _lazy('Fear')},
    # L10n: `Sex` as in sexual, not as in gender.
    'PEGI_SEX_CONTENT': {'name': _lazy('Sex')},
    'PEGI_VIOLENCE': {'name': _lazy('Violence')},

    # PEGI's version of interactive elements.
    'PEGI_USERS_INTERACT': {'name': _lazy('Social Interaction Functionality')},
    'PEGI_SHARES_INFO': {'name': _lazy('Personal Data Sharing')},
    'PEGI_DIGITAL_PURCHASES': {'name': _lazy('In-app Purchase Option')},
    'PEGI_SHARES_LOCATION': {'name': _lazy('Location Data Sharing')},

    'USK_DISCRIMINATION': {'name': _lazy('Discrimination')},
    'USK_DRUGS': {'name': _lazy('Drugs')},
    # L10n: `Language` as in foul language.
    'USK_LANG': {'name': _lazy('Explicit Language')},
    'USK_NO_DESCS': {'name': _lazy('No Descriptors')},
    'USK_SCARY': {'name': _lazy('Frightening Content')},
    'USK_SEX_CONTENT': {'name': _lazy('Sexual Content')},
    'USK_VIOLENCE': {'name': _lazy('Violence')},
}
