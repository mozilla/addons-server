from urllib.parse import urlsplit, urlunsplit

# for src\olympia\addons\migrations\0037_auto_20220321_1545.py

CONTRIBUTION_CHANGES = {
    'buymeacoffee.com': 'www.buymeacoffee.com',
    'www.donate.mozilla.org':  'donate.mozilla.org',
    'www.flattr.com': 'flattr.com',
    'www.github.com': 'github.com',
    'www.ko-fi.com': 'ko-fi.com',
    'www.liberapay.com': 'liberapay.com',
    'id.liberapay.com': 'liberapay.com',
    'micropayment.de': 'www.micropayment.de',
    'www.opencollective.com': 'opencollective.com',
    'patreon.com': 'www.patreon.com',
    'paypal.com': 'www.paypal.com',
    'paypal.me': 'www.paypal.com',
}

BROKEN_URLS = (
    'https://www.fdfgd@paypal.me',
    'https://gist.github.com/miry/2a7635beaa7078e0d7af',
    'https://thezenithpoint.co.uk@donate.mozilla.org',
    'https://bunny.github.com',
)


def fix_contributions_url(url):
    if url in BROKEN_URLS:
        return ''
    try:
        split_url = urlsplit(url)
        if split_url.scheme != 'https':
            split_url = split_url._replace(scheme='https')
        if (hostname := split_url.hostname) in CONTRIBUTION_CHANGES:
            split_url = split_url._replace(
                netloc=split_url.netloc.replace(
                    hostname, CONTRIBUTION_CHANGES[hostname]
                )
            )
    except ValueError:
        return url
    return urlunsplit(split_url)
