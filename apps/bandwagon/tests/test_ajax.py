import test_utils
from nose.tools import eq_
from pyquery import PyQuery as pq

from amo.urlresolvers import reverse
from bandwagon.models import Collection


class AjaxTest(test_utils.TestCase):
    fixtures = ['base/fixtures']

    def test_list_collections(self):
        self.client.login(username='clouserw@gmail.com', password='yermom')
        r = self.client.get(reverse('collections.ajax_list')
                            + '?addon_id=1843',)
        doc = pq(r.content)
        eq_(doc('li.selected').attr('data-id'), '80')

    def test_add_collection(self):
        self.client.login(username='clouserw@gmail.com', password='yermom')
        r = self.client.post(reverse('collections.ajax_add'),
                             {'addon_id': 3615, 'id': 80}, follow=True)
        doc = pq(r.content)
        eq_(doc('li.selected').attr('data-id'), '80')

    def test_remove_collection(self):
        self.client.login(username='clouserw@gmail.com', password='yermom')
        r = self.client.post(reverse('collections.ajax_remove'),
                             {'addon_id': 1843, 'id': 80}, follow=True)
        doc = pq(r.content)
        eq_(len(doc('li.selected')), 0)

    def test_new_collection(self):
        num_collections = Collection.objects.all().count()
        self.client.login(username='clouserw@gmail.com', password='yermom')
        r = self.client.post(reverse('collections.ajax_new'),
                {'addon_id': 3615,
                 'name': 'foo',
                 'slug': 'auniqueone',
                 'description': 'yermom',
                 'listed': True},
                follow=True)
        doc = pq(r.content)
        eq_(len(doc('li.selected')), 1, "The new collection is not selected.")
        eq_(Collection.objects.all().count(), num_collections + 1)

    def test_add_other_collection(self):
        "403 when you try to add to a collection that isn't yours."
        c = Collection()
        c.save()

        self.client.login(username='clouserw@gmail.com', password='yermom')
        r = self.client.post(reverse('collections.ajax_add'),
                             {'addon_id': 3615, 'id': c.id}, follow=True)
        eq_(r.status_code, 403)

    def test_remove_other_collection(self):
        "403 when you try to add to a collection that isn't yours."
        c = Collection()
        c.save()

        self.client.login(username='clouserw@gmail.com', password='yermom')
        r = self.client.post(reverse('collections.ajax_remove'),
                             {'addon_id': 3615, 'id': c.id}, follow=True)
        eq_(r.status_code, 403)
