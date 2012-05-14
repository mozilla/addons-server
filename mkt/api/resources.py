from piston.resource import Resource
from piston.utils import rc


class MarketplaceResource(Resource):

    def error_handler(self, *args, **kwargs):
        """
        A wrapper around the builtin error handler so that errors are
        actually returned using the builtin rc handler, just like the rest
        rather than some custom code.
        """
        try:
            return (super(MarketplaceResource, self)
                        .error_handler(*args, **kwargs))
        except:
            return rc.INTERNAL_ERROR
