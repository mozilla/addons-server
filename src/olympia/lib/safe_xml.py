"""
Monkey patch and defuse all stdlib xml packages and lxml.
"""
import sys


patched_modules = (
    'lxml',
    'ElementTree',
    'minidom',
    'pulldom',
    'sax',
    'expatbuilder',
    'expatreader',
    'xmlrpc',
)

if any(module in sys.modules for module in patched_modules):
    existing_modules = [(module, module in sys.modules) for module in patched_modules]
    raise ImportError(
        f'this monkey patch was not applied early enough. {existing_modules}'
    )

from defusedxml import defuse_stdlib  # noqa

defuse_stdlib()

import lxml  # noqa
import lxml.etree  # noqa
from xml.sax.handler import (  # noqa
    feature_external_ges,
    feature_external_pes,
)


from olympia.lib import safe_lxml_etree  # noqa


lxml.etree = safe_lxml_etree
