"""
Turn :src:`file.py` into a link to `file.py` in your online source browser.

Requires src_base_url to be set in conf.py.
"""
from urllib.parse import urljoin

from docutils import nodes


def setup(app):
    app.add_config_value('src_base_url', None, 'html')
    app.add_role('src', src_role)


def src_role(name, rawtext, text, lineno, inliner, options=None, content=None):
    if options is None:
        options = {}
    if content is None:
        content = []
    base_url = inliner.document.settings.env.config.src_base_url
    if base_url is None:
        msg = inliner.reporter.error('src_base_url is not set', line=lineno)
        prb = inliner.problematic(rawtext, rawtext, msg)
        return [prb], [msg]

    ref = urljoin(base_url, text)
    rn = nodes.reference(rawtext, text, refuri=ref)
    return [rn], []
