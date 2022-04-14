# These two dicts are mapping between language codes in addons-server and
# language analyzers in elasticsearch.
#
# The keys are elasticsearch language analyzers while each value is a list of
# language codes supported by AMO.
#
# The lines commented out are that the language is not supported by
# elasticsearch yet.  We should update it when elasticsearch supports new
# analyzer for the language.
#
# http://www.elasticsearch.org/guide/reference/index-modules/analysis/lang-analyzer.html

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
