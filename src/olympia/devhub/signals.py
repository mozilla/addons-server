import django.dispatch


logged_out = django.dispatch.Signal(providing_args=['request', 'response'])
submission_done = django.dispatch.Signal()
