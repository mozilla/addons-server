from mkt.api.exceptions import custom_exception_handler

from nose.tools import raises
from rest_framework.response import Response
from test_utils import TestCase


class TestExceptionHandler(TestCase):

    def test_response(self):
        try:
            1/0
        except Exception as exc:
            assert isinstance(custom_exception_handler(exc), Response)

    @raises(ZeroDivisionError)
    def test_raised(self):
        with self.settings(DEBUG_PROPAGATE_EXCEPTIONS=True):
            try:
                1/0
            except Exception as exc:
                custom_exception_handler(exc)
