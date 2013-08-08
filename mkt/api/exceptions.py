from rest_framework import status
from rest_framework.exceptions import APIException
from tastypie.exceptions import TastypieError


class DeserializationError(TastypieError):
    def __init__(self, original=None):
        self.original = original


class AlreadyPurchased(Exception):
    pass


class NotImplemented(APIException):
    status_code = status.HTTP_501_NOT_IMPLEMENTED
    default_detail = 'API not implemented.'

    def __init__(self, detail=None):
        self.detail = detail or self.default_detail
