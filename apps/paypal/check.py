import hashlib
import logging
import uuid

from tower import ugettext as _

import paypal


log = logging.getLogger('z.paypal')


class Check(object):
    """
    Run a series of tests on PayPal for either an addon or a paypal_id.
    The add-on is not required, but we'll do another check or two if the
    add-on is there.
    """

    def __init__(self, addon=None, paypal_id=None):
        # If this state flips to False, it means they need to
        # go to Paypal and re-set up permissions. We'll assume the best.
        self.state = {'permissions': True}
        self.tests = ['id', 'refund']
        for test in self.tests:
            # Three states for pass:
            #   None: haven't tried
            #   False: tried but failed
            #   True: tried and passed
            self.state[test] = {'pass': None, 'errors': []}
        self.addon = addon
        self.paypal_id = paypal_id
        if not self.paypal_id and self.addon:
            self.paypal_id = self.addon.paypal_id

    def all(self):
        self.check_id()
        self.check_refund()

    def failure(self, test, msg):
        self.state[test]['errors'].append(msg)
        self.state[test]['pass'] = False

    def pass_(self, test):
        self.state[test]['pass'] = True

    def check_id(self):
        """Check that the paypal id is good."""
        test_id = 'id'
        if not self.paypal_id:
            self.failure(test_id, _('No PayPal ID provided.'))
            return

        valid, msg = paypal.check_paypal_id(self.paypal_id)
        if not valid:
            self.failure(test_id, _('Please enter a valid email.'))

        else:
            self.pass_(test_id)

    def check_refund(self):
        """Check that we have the refund permission."""
        test_id = 'refund'
        msg = _('You have not setup permissions for us to check this '
                'PayPal account.')
        if not self.addon:
            # If there's no addon there's not even any point checking.
            return

        premium = self.addon.premium
        if not premium:
            self.state['permissions'] = False
            self.failure(test_id, msg)
            return

    def test_paykey(self, data):
        """
        Wraps get_paykey filling none optional data with test data. This
        should never ever be used for real purchases.

        The only things that you can set on this are:
        email: who the money is going to (required)
        amount: the amount of money (required)
        currency: valid paypal currency, defaults to USD (optional)
        """
        data.update({
            'pattern': '',
            'ip': '127.0.0.1',
            'slug': 'foo',
            'uuid': hashlib.md5(str(uuid.uuid4())).hexdigest()
        })
        return paypal.get_paykey(data)

    @property
    def passed(self):
        """Returns a boolean to check that all the attempted tests passed."""
        values = [self.state[k] for k in self.tests]
        passes = [s['pass'] for s in values if s['pass'] is not None]
        if passes:
            return all(passes)
        return False

    @property
    def errors(self):
        errs = []
        for k in self.tests:
            if self.state[k]['pass'] is False:
                for err in self.state[k]['errors']:
                    errs.append(err)
        return errs
