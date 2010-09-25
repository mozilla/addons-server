"""
A monkeypatch for ``django.dispatch`` to send signals safely.

Usage::

    >>> import safe_signals
    >>> safe_signals.start_the_machine()

``django.dispatch.Signal.send`` is replaced with a safer function that catches
and logs errors.  It's like ``Signal.send_robust`` but with logging.

"""
import logging

from django.dispatch.dispatcher import Signal, _make_id

log = logging.getLogger('signals')


def safe_send(self, sender, **named):
    responses = []
    if not self.receivers:
        return responses

    # Call each receiver with whatever arguments it can accept.
    # Return a list of tuple pairs [(receiver, response), ... ].
    for receiver in self._live_receivers(_make_id(sender)):
        try:
            response = receiver(signal=self, sender=sender, **named)
        except Exception, err:
            log.error('Error calling signal', exc_info=True)
            responses.append((receiver, err))
        else:
            responses.append((receiver, response))
    return responses


safe_send.__doc__ = Signal.send_robust.__doc__
unsafe_send = Signal.send


def start_the_machine():
    # Monkeypatch!
    Signal.send = safe_send
    Signal.send_robust = safe_send
