from django.conf import settings


def is_gate_active(request, name):
    """Check if a specific gate is active for the current API version.
    Note that `request` has to be a :class:`~rest_framework.request.Request`
    object that has `version` attached.
    We're not examining Django request objects.
    """
    gates = settings.DRF_API_GATES.get(getattr(request, 'version', None), None)
    if not gates:
        return False

    return name in gates
