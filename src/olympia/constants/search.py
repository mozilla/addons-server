# These two dicts are mapping between language codes in zamboni and language
# analyzers in elasticsearch.
#
# Each key value of ANALYZER_MAP is language analyzer supported by
# elasticsearch.  See
# http://www.elasticsearch.org/guide/reference/index-modules/analysis/lang-analyzer.html
#
# Each value of ANALYZER_MAP is a list which is supported by the key analyzer.
# All values are picked from AMO_LANGUAGES in settings.py.
#
# The rows commented out are that the language is not supported by
# elasticsearch yet.  We should update it when elasticsearch supports new
# analyzer for the language.

SEARCH_ANALYZER_MAP = {
    # '': ['af'],    # Afrikaans
    'arabic': ['ar'],
    'bulgarian': ['bg'],
    'catalan': ['ca'],
    'czech': ['cs'],
    'danish': ['da'],
    'german': ['de'],
    'greek': ['el'],
    'english': ['en-us', 'en-ca', 'en-gb'],
    'spanish': ['es'],
    'basque': ['eu'],
    'persian': ['fa'],
    'finnish': ['fi'],
    'french': ['fr'],
    # '': ['ga-ie'], # Gaelic - Ireland
    # '': ['he'],    # Hebrew
    'hungarian': ['hu'],
    'indonesian': ['id'],
    'italian': ['it'],
    'cjk': ['ja', 'ko'],
    # '': ['mn'],    # Mongolian
    'dutch': ['nl'],
    # Polish requires the Elasticsearch plugin:
    # https://github.com/elasticsearch/elasticsearch-analysis-stempel
    # We had issues with that in Marketplace and never enabled it from AMO,
    # so leave it out until we decide to revisit the issue.
    # 'polish': ['pl'],
    'brazilian': ['pt-br'],
    'portuguese': ['pt-pt'],
    'romanian': ['ro'],
    'russian': ['ru'],
    # '': ['sk'],    # Slovak
    # '': ['sl'],    # Slovenian
    # '': ['sq'],    # Albanian
    'swedish': ['sv-se'],
    # '': ['uk'],    # Ukrainian
    # '': ['vi'],    # Vietnamese
    'chinese': ['zh-cn', 'zh-tw'],
}


# This dict is an inverse mapping of ANALYZER_MAP.
SEARCH_LANGUAGE_TO_ANALYZER = {}
for analyzer, languages in SEARCH_ANALYZER_MAP.items():
    for language in languages:
        SEARCH_LANGUAGE_TO_ANALYZER[language] = analyzer

# Which stemmer to use for each language.
#
# Note: We use the keys of this dict for supported stop words, also, which is
# specified as, e.g., '_english_'.
STEMMER_MAP = {
    'arabic': 'arabic',
    'basque': 'basque',
    'brazilian': 'brazilian',
    'bulgarian': 'bulgarian',
    'catalan': 'catalan',
    'czech': 'czech',
    'danish': 'danish',
    'dutch': 'dutch',
    'english': 'minimal_english',
    'finnish': 'light_finish',  # Yes, this is misspelled in ES.
    'french': 'light_french',
    'german': 'light_german',
    'greek': 'greek',
    'hungarian': 'light_hungarian',
    'indonesian': 'indonesian',
    'italian': 'light_italian',
    'portuguese': 'light_portuguese',
    'romanian': 'romanian',
    'russian': 'russian',
    'spanish': 'light_spanish',
    'swedish': 'light_swedish',
}
