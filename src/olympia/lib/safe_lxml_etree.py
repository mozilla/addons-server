from lxml.etree import *  # noqa isort:skip
from lxml.etree import XMLParser as _XMLParser  # isort:skip
from lxml.etree import _ElementTree, _Comment, _Element  # noqa isort:skip

# This should be imported after lxml.etree so that it overrides the
# following attributes.
from defusedxml.lxml import parse, fromstring, XML  # noqa isort:skip
from defusedxml.common import NotSupportedError


class XMLParser(_XMLParser):
    """
    A safer version of XMLParser which deosn't allow entity resolution.
    """

    def __init__(self, *args, **kwargs):
        resolve_entities = kwargs.get('resolve_entities', False)

        if resolve_entities:
            raise NotSupportedError(
                'resolve_entities is forbidden for security reasons.'
            )

        super(XMLParser, self).__init__(*args, **kwargs)
