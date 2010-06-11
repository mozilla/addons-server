"""
A script for generating siege files with a bunch of URL variations.
"""
import itertools
import re
import sys

part_re = re.compile(r'\{([-\w]+)\}')

AMO_LANGUAGES = (
    'af', 'ar', 'ca', 'cs', 'da', 'de', 'el', 'en-US', 'es-ES', 'eu',
    'fa', 'fi', 'fr', 'ga-IE', 'he', 'hu', 'id', 'it', 'ja', 'ko',
    'mn', 'nl', 'pl', 'pt-BR', 'pt-PT', 'ro', 'ru', 'sk', 'sq', 'sr',
    'sv-SE', 'uk', 'vi', 'zh-CN', 'zh-TW',
)

config = {
    'base': [],
    'locale': AMO_LANGUAGES,
    'app': ['firefox'],

    'extension-slug': [''] + """
        alerts-and-updates appearance bookmarks download-management
        feeds-news-blogging language-support photos-music-videos
        privacy-security social-communication tabs toolbars web-development
        other""".split(),

    'theme-slug': [''] + """
        animals compact large miscellaneous modern nature os-integration retro
        sports""".split(),
    'theme-sort': 'name updated created downloads rating'.split(),

    'page': '1 2'.split(),
    'exp': 'on off'.split(),

    'personas-slug': [''] + """
        abstract causes fashion firefox foxkeh holiday music nature other
        scenery seasonal solid sports websites""".split(),
    'personas-sort': """up-and-coming created popular rating""".split()
}

root = '{base}/{locale}/{app}'

templates = t = {
    'root': '/',
    'extensions': '/extensions/{extension-slug}/',
    'language-tools': '/language-tools',
    'themes': '/themes/{theme-slug}?sort={theme-sort}&page={page}',
    'personas': '/personas/{personas-slug}',
}
t['themes-unreviewed'] = t['themes'] + '&unreviewed={exp}'
t['personas-sort'] = t['personas'] + '?sort={personas-sort}'
t['extensions-sort'] = t['extensions'] + '?sort={theme-sort}'
t['extensions-featured'] = t['extensions'] + 'featured'


for key, value in templates.items():
    templates[key] = root + value


def combos(s, parts):
    def _rec(s, parts, kw):
        key, rest = parts[0], parts[1:]
        rv = []
        for opt in config[key]:
            kw[key] = opt
            if not rest:
                rv.append(s.format(**kw))
            else:
                rv.extend(_rec(s, rest, kw))
        return rv
    return _rec(s, parts, {})


def gen(choices=templates):
    rv = []
    for template in choices:
        parts = part_re.findall(template)
        rv.extend(combos(template, parts))
    return rv


def main():
    args = sys.argv
    try:
        base, choices = sys.argv[1], args[2:] or templates.keys()
    except IndexError:
        print 'Usage: python siege.py <BASE> [%s]' % (', '.join(templates))
        print '\nBASE should be something like "http://localhost:8000/z".'
        print 'The remaining arguments are names of url templates.'
        sys.exit(1)

    config['base'] = [base.rstrip('/')]
    print '\n'.join(gen(templates[k] for k in choices))


if __name__ == '__main__':
    main()
