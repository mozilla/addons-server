from rest_framework import status
from rest_framework.exceptions import APIException
from tastypie.exceptions import TastypieError


class DeserializationError(TastypieError):
    def __init__(self, original=None):
        self.original = original


class AlreadyPurchased(Exception):
    pass


class Conflict(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_detail = 'Conflict detected.'

    def __init__(self, detail=None):
        self.detail = detail or self.default_detail


class NotImplemented(APIException):
    status_code = status.HTTP_501_NOT_IMPLEMENTED
    default_detail = 'API not implemented.'

    def __init__(self, detail=None):
        self.detail = detail or self.default_detail


class ServiceUnavailable(APIException):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    default_detail = 'Service unavailable at this time.'

    def __init__(self, detail=None):
        self.detail = detail or self.default_detail
