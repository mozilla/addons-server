from django import test

from nose.tools import eq_

from users.utils import EmailResetCode


class TestEmailResetCode(test.TestCase):

    def test_parse(self):
        id = 1
        mail = 'nobody@mozilla.org'
        code = EmailResetCode.create(id, mail)

        code, hash = code.split('/')

        r_id, r_mail = EmailResetCode.parse(code, hash)
        eq_(id, r_id)
        eq_(mail, r_mail)

        # A bad token or hash raises ValueError
        self.assertRaises(ValueError, EmailResetCode.parse, code, hash[:-5])
        self.assertRaises(ValueError, EmailResetCode.parse, code[5:], hash)
