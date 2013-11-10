from ordereddict import OrderedDict

from tower import ugettext_lazy as _lazy


# WARNING: When adding a new rating descriptor here also include a migration.
#
# These are used to dynamically generate the field list for the
# RatingDescriptors django model in mkt.webapps.models.
RATING_DESCS = OrderedDict([
    # ngoke can read Porchugeeze.
    ('CLASSIND_VIOLENCE', {
        'name': _lazy('Violence'),
    }),
    ('CLASSIND_VIOLENCE_EXTREME', {
        'name': _lazy('Extreme Violence'),
    }),
    ('CLASSIND_NUDITY', {
        'name': _lazy('Nudity'),
    }),
    ('CLASSIND_SEX_CONTENT', {
        # L10n: `Sex` as in sexual, not as in gender.
        'name': _lazy('Sex'),
    }),
    ('CLASSIND_SEX_EXPLICIT', {
        'name': _lazy('Explicit Sex'),
    }),
    ('CLASSIND_DRUGS', {
        'name': _lazy('Drugs'),
    }),
    ('CLASSIND_DRUGS_LEGAL', {
        'name': _lazy('Legal Drugs'),
    }),
    ('CLASSIND_DRUGS_ILLEGAL', {
        'name': _lazy('Illegal Drugs'),
    }),
    ('CLASSIND_LANG', {
        # L10n: `Language` as in foul language.
        'name': _lazy('Language'),
    }),
    ('CLASSIND_CRIMINAL_ACTS', {
        'name': _lazy('Criminal Acts'),
    }),
    ('CLASSIND_SHOCKING', {
        'name': _lazy('Shocking Content'),
    }),
    ('CLASSIND_NO_DESCS', {
        'name': _lazy('No Descriptors'),
    }),
    ('ESRB_ALCOHOL', {
        'name': _lazy('Alcohol Reference'),
    }),
    ('ESRB_BLOOD', {
        'name': _lazy('Blood'),
    }),
    ('ESRB_BLOOD_GORE', {
        'name': _lazy('Blood and Gore'),
    }),
    ('ESRB_CRUDE_HUMOR', {
        'name': _lazy('Crude Humor'),
    }),
    ('ESRB_DRUG_REF', {
        'name': _lazy('Drug Reference'),
    }),
    ('ESRB_FANTASY_VIOLENCE', {
        'name': _lazy('Fantasy Violence'),
    }),
    ('ESRB_INTENSE_VIOLENCE', {
        'name': _lazy('Intense Violence'),
    }),
    ('ESRB_LANG', {
        # L10n: `Language` as in foul language.
        'name': _lazy('Language'),
    }),
    ('ESRB_MILD_BLOOD', {
        'name': _lazy('Mild Blood'),
    }),
    ('ESRB_MILD_FANTASY_VIOLENCE', {
        'name': _lazy('Mild Fantasy Violence'),
    }),
    ('ESRB_MILD_LANG', {
        'name': _lazy('Mild Language'),
    }),
    ('ESRB_MILD_VIOLENCE', {
        'name': _lazy('Mild Violence'),
    }),
    ('ESRB_NUDITY', {
        'name': _lazy('Nudity'),
    }),
    ('ESRB_PARTIAL_NUDITY', {
        'name': _lazy('Partial Nudity'),
    }),
    ('ESRB_REAL_GAMBLING', {
        'name': _lazy('Gambling'),
    }),
    ('ESRB_SEX_CONTENT', {
        'name': _lazy('Sexual Content'),
    }),
    ('ESRB_SEX_THEMES', {
        'name': _lazy('Sexual Themes'),
    }),
    ('ESRB_SIM_GAMBLING', {
        'name': _lazy('Simulated Gambling'),
    }),
    ('ESRB_STRONG_LANG', {
        'name': _lazy('Strong Language'),
    }),
    ('ESRB_STRONG_SEX_CONTENT', {
        'name': _lazy('Strong Sexual Content'),
    }),
    ('ESRB_SUGGESTIVE', {
        'name': _lazy('Suggestive Themes'),
    }),
    ('ESRB_TOBACCO_REF', {
        'name': _lazy('Tobacco Reference'),
    }),
    ('ESRB_ALCOHOL_USE', {
        'name': _lazy('Use of Alcohol'),
    }),
    ('ESRB_DRUG_USE', {
        'name': _lazy('Use of Drugs'),
    }),
    ('ESRB_TOBACCO_USE', {
        'name': _lazy('Use of Tobacco'),
    }),
    ('ESRB_VIOLENCE', {
        'name': _lazy('Violence'),
    }),
    ('ESRB_VIOLENCE_REF', {
        'name': _lazy('Violence References'),
    }),
    ('ESRB_NO_DESCS', {
        'name': _lazy('No Descriptors'),
    }),
    ('ESRB_COMIC_MISCHIEF', {
        'name': _lazy('Comic Mischief'),
    }),
    ('ESRB_ALCOHOL_TOBACCO_REF', {
        'name': _lazy('Alcohol and Tobacco Reference'),
    }),
    ('ESRB_DRUG_ALCOHOL_REF', {
        'name': _lazy('Drug and Alcohol Reference'),
    }),
    ('ESRB_ALCOHOL_TOBACCO_USE', {
        'name': _lazy('Use of Alcohol and Tobacco'),
    }),
    ('ESRB_DRUG_ALCOHOL_USE', {
        'name': _lazy('Use of Drug and Alcohol'),
    }),
    ('ESRB_DRUG_TOBACCO_REF', {
        'name': _lazy('Drug and Tobacco Reference'),
    }),
    ('ESRB_DRUG_ALCOHOL_TOBACCO_REF', {
        'name': _lazy('Drug, Alcohol, and Tobacco Reference'),
    }),
    ('ESRB_DRUG_TOBACCO_USE', {
        'name': _lazy('Use of Drug and Tobacco'),
    }),
    ('ESRB_DRUG_ALCOHOL_TOBACCO_USE', {
        'name': _lazy('Use of Drug, Alcohol, and Tobacco'),
    }),
    ('ESRB_SCARY', {
        'name': _lazy('Scary Themes'),
    }),
    ('ESRB_HATE_SPEECH', {
        'name': _lazy('Hate Speech'),
    }),
    ('ESRB_CRIME', {
        'name': _lazy('Crime'),
    }),
    ('ESRB_CRIME_INSTRUCT', {
        'name': _lazy('Criminal Instruction'),
    }),
    ('PEGI_VIOLENCE', {
        'name': _lazy('Violence'),
    }),
    ('PEGI_LANG', {
        # L10n: `Language` as in foul language.
        'name': _lazy('Language'),
    }),
    ('PEGI_SCARY', {
        'name': _lazy('Fear'),
    }),
    ('PEGI_SEX_CONTENT', {
        # L10n: `Sex` as in sexual, not as in gender.
        'name': _lazy('Sex'),
    }),
    ('PEGI_DRUGS', {
        'name': _lazy('Drugs'),
    }),
    ('PEGI_DISCRIMINATION', {
        'name': _lazy('Discrimination'),
    }),
    ('PEGI_GAMBLING', {
        'name': _lazy('Gambling'),
    }),
    ('PEGI_ONLINE', {
        'name': _lazy('Online'),
    }),
    ('PEGI_NO_DESCS', {
        'name': _lazy('No Descriptors'),
    }),
    # Generic ratings same as ESRB, except less drugs/alcohol/tobacco.
    ('GENERIC_ALCOHOL_REF', {
        'name': _lazy('Alcohol Reference'),
    }),
    ('GENERIC_BLOOD', {
        'name': _lazy('Blood'),
    }),
    ('GENERIC_BLOOD_GORE', {
        'name': _lazy('Blood and Gore'),
    }),
    ('GENERIC_CRUDE_HUMOR', {
        'name': _lazy('Crude Humor'),
    }),
    ('GENERIC_DRUG_REF', {
        'name': _lazy('Drug Reference'),
    }),
    ('GENERIC_FANTASY_VIOLENCE', {
        'name': _lazy('Fantasy Violence'),
    }),
    ('GENERIC_INTENSE_VIOLENCE', {
        'name': _lazy('Intense Violence'),
    }),
    ('GENERIC_LANG', {
        # L10n: `Language` as in foul language.
        'name': _lazy('Language'),
    }),
    ('GENERIC_MILD_BLOOD', {
        'name': _lazy('Mild Blood'),
    }),
    ('GENERIC_MILD_FANTASY_VIOLENCE', {
        'name': _lazy('Mild Fantasy Violence'),
    }),
    ('GENERIC_MILD_LANG', {
        'name': _lazy('Mild Language'),
    }),
    ('GENERIC_MILD_VIOLENCE', {
        'name': _lazy('Mild Violence'),
    }),
    ('GENERIC_NUDITY', {
        'name': _lazy('Nudity'),
    }),
    ('GENERIC_PARTIAL_NUDITY', {
        'name': _lazy('Partial Nudity'),
    }),
    ('GENERIC_REAL_GAMBLING', {
        'name': _lazy('Gambling'),
    }),
    ('GENERIC_SEX_CONTENT', {
        'name': _lazy('Sexual Content'),
    }),
    ('GENERIC_SEX_THEMES', {
        'name': _lazy('Sexual Themes'),
    }),
    ('GENERIC_SIM_GAMBLING', {
        'name': _lazy('Simulated Gambling'),
    }),
    ('GENERIC_STRONG_LANG', {
        'name': _lazy('Strong Language'),
    }),
    ('GENERIC_STRONG_SEX_CONTENT', {
        'name': _lazy('Strong Sexual Content'),
    }),
    ('GENERIC_SUGGESTIVE', {
        'name': _lazy('Suggestive Themes'),
    }),
    ('USK_NO_DESCS', {
        'name': _lazy('No Descriptors'),
    }),
    ('USK_SCARY', {
        'name': _lazy('Frightening Content'),
    }),
    ('USK_SEX_CONTENT', {
        'name': _lazy('Sexual Content'),
    }),
    ('USK_LANG', {
        # L10n: `Language` as in foul language.
        'name': _lazy('Language'),
    }),
    ('USK_DISCRIMINATION', {
        'name': _lazy('Discrimination'),
    }),
    ('USK_DRUGS', {
        'name': _lazy('Drugs'),
    }),
    ('USK_VIOLENCE', {
        'name': _lazy('Violence'),
    }),
])
