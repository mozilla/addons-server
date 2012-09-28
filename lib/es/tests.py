import mock
from nose.tools import eq_

import amo.tests

import context
import decorators
from hold import _locals, process, reset, add


class ESHold(amo.tests.TestCase):

    def setUp(self):
        reset()
        self.callback = mock.Mock()
        self.callback.__name__ = 'foo'

    def test_add(self):
        add(self.callback, 1)
        eq_(len(_locals.tasks), 1)
        add(self.callback, 1)
        eq_(len(_locals.tasks), 1)
        add(self.callback, 2)
        eq_(len(_locals.tasks), 2)

        callback = mock.Mock()
        callback.__name__ = 'bar'
        add(callback, 2)
        eq_(len(_locals.tasks), 3)

    def test_reset(self):
        add(self.callback, 1)
        eq_(len(_locals.tasks), 1)
        reset()
        eq_(len(_locals.tasks), 0)

    def test_process(self):
        add(self.callback, 1)
        process()
        assert self.callback.called

    def test_process_groups(self):
        add(self.callback, 1)
        add(self.callback, 4)
        process()
        eq_(set(self.callback.call_args[0][0]), set([1, 4]))

    def test_context(self):
        with context.send():
            add(self.callback, 1)
        assert self.callback.called

    def test_decorators(self):
        @decorators.send
        def foo():
            add(self.callback, 1)
        foo()
        assert self.callback.called
