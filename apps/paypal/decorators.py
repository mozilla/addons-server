import jingo
import paypal


def handle_paypal_error(fn):
    """Wraps the view so that if a paypal error occurs, you show
       a more menaningful error message. May or may not make sense for
       all views, so providing as a decorator."""
    def wrapper(request, *args, **kw):
        try:
            return fn(request, *args, **kw)
        except paypal.PaypalError:
            # This is specific handling for the submission step.
            dest = request.GET.get('dest')
            return jingo.render(request, 'site/500_paypal.html',
                                {'submission': dest == 'submission',
                                 'addon': kw.get('addon', None)},
                                status=500)
    return wrapper
