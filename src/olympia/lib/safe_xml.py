"""
Monkey patch and defuse all stdlib xml packages and lxml.
"""
import sys


patched_modules = (
    'lxml',
    'ElementTree',
    'minidom',
    'pulldom',
    'rdflib',
    'sax',
    'expatbuilder',
    'expatreader',
    'xmlrpc',
)

if any(module in sys.modules for module in patched_modules):
    existing_modules = [
        (module, module in sys.modules) for module in patched_modules
    ]
    raise ImportError(
        'this monkey patch was not applied early enough. {0}'.format(
            existing_modules
        )
    )

from defusedxml import defuse_stdlib  # noqa isort:skip

defuse_stdlib()

import lxml  # noqa isort:skip
import lxml.etree  # noqa isort:skip
from rdflib.plugins.parsers import rdfxml  # noqa isort:skip
from xml.sax.handler import (
    feature_external_ges,
    feature_external_pes,
)  # noqa isort:skip

from olympia.lib import safe_lxml_etree  # noqa isort:skip


lxml.etree = safe_lxml_etree


_rdfxml_create_parser = rdfxml.create_parser


def create_rdf_parser_without_externals(target, store):
    """
    Create an RDF parser that does not support general entity expansion,
    remote or local.

    See https://bugzilla.mozilla.org/show_bug.cgi?id=1306954
    """
    parser = _rdfxml_create_parser(target, store)
    parser.setFeature(feature_external_ges, 0)
    parser.setFeature(feature_external_pes, 0)
    return parser


rdfxml.create_parser = create_rdf_parser_without_externals
