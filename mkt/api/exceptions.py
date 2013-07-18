from tastypie.exceptions import TastypieError


class DeserializationError(TastypieError):
    def __init__(self, original=None):
        self.original = original


class AlreadyPurchased(Exception):
    pass
