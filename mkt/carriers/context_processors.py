from . import get_carrier


def carrier_data(request):
    """
    Context processor that provides CARRIER to all views.
    """
    return {'CARRIER': get_carrier()}
