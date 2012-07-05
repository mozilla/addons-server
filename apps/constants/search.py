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
#    '':          ['af'],    # Afrikaans
    'arabic':     ['ar'],
    'bulgarian':  ['bg'],
    'catalan':    ['ca'],
    'czech':      ['cs'],
    'danish':     ['da'],
    'german':     ['de'],
    'greek':      ['el'],
    'english':    ['en-us'],
    'spanish':    ['es'],
    'basque':     ['eu'],
    'persian':    ['fa'],
    'finnish':    ['fi'],
    'french':     ['fr'],
#    '':          ['ga-ie'], # Gaelic - Ireland
#    '':          ['he'],    # Hebrew
    'hungarian':  ['hu'],
    'indonesian': ['id'],
    'italian':    ['it'],
    'cjk':        ['ja', 'ko'],
#    '':          ['mn'],    # Mongolian
    'dutch':      ['nl'],
#    '':          ['pl'],    # Polish
    'brazilian':  ['pt-br'],
    'portuguese': ['pt-pt'],
    'romanian':   ['ro'],
    'russian':    ['ru'],
#    '':          ['sk'],    # Slovak
#    '':          ['sl'],    # Slovenian
#    '':          ['sq'],    # Albanian
    'swedish':    ['sv-se'],
#    '':          ['uk'],    # Ukrainian
#    '':          ['vi'],    # Vietnamese
    'chinese':    ['zh-cn', 'zh-tw'],
}


# This dict is an inverse mapping of ANALYZER_MAP.
SEARCH_LANGUAGE_TO_ANALYZER = {}
for analyzer, languages in SEARCH_ANALYZER_MAP.items():
    for language in languages:
        SEARCH_LANGUAGE_TO_ANALYZER[language] = analyzer
