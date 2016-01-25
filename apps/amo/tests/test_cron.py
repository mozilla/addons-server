
import amo.tests
from amo.cron import gc
from bandwagon.models import Collection
from devhub.models import ActivityLog
from stats.models import Contribution


class GarbageTest(amo.tests.TestCase):
    fixtures = ['base/addon_59', 'base/garbage']

    def test_garbage_collection(self):
        "This fixture is expired data that should just get cleaned up."
        assert Collection.objects.all().count() == 1
        assert ActivityLog.objects.all().count() == 1
        assert Contribution.objects.all().count() == 1
        gc(test_result=False)
        assert Collection.objects.all().count() == 0
        assert ActivityLog.objects.all().count() == 0
        assert Contribution.objects.all().count() == 0
