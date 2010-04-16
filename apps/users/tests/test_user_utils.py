from django import test

from nose.tools import eq_

from users.utils import EmailResetCode


class TestEmailResetCode(test.TestCase):

    def test_parse(self):
        id = 1
        mail = 'nobody@mozilla.org'
        token, hash = EmailResetCode.create(id, mail)

        r_id, r_mail = EmailResetCode.parse(token, hash)
        eq_(id, r_id)
        eq_(mail, r_mail)

        # A bad token or hash raises ValueError
        self.assertRaises(ValueError, EmailResetCode.parse, token, hash[:-5])
        self.assertRaises(ValueError, EmailResetCode.parse, token[5:], hash)
