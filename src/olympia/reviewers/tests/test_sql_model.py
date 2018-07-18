# -*- coding: utf-8 -*-
"""Tests for SQL Model.

Currently these tests are coupled tighly with MySQL
"""
from datetime import datetime

from django.db import connection, models
from django.db.models import Q

import pytest

from olympia.amo.tests import BaseTestCase
from olympia.reviewers.sql_model import RawSQLModel


def execute_all(statements):
    with connection.cursor() as cursor:
        for sql in statements:
            if not sql.strip():
                continue
            cursor.execute(sql, [])


class Summary(RawSQLModel):
    category = models.CharField(max_length=255)
    total = models.IntegerField()
    latest_product_date = models.DateTimeField()

    def base_query(self):
        return {
            'select': {
                'category': 'c.name',
                'total': 'count(*)',
                'latest_product_date': 'max(p.created)',
            },
            'from': [
                'sql_model_test_product p',
                'join sql_model_test_product_cat x on x.product_id=p.id',
                'join sql_model_test_cat c on x.cat_id=c.id',
            ],
            'where': [],
            'group_by': 'category',
        }


class ProductDetail(RawSQLModel):
    product = models.CharField(max_length=255)
    category = models.CharField(max_length=255)

    def base_query(self):
        return {
            'select': {'product': 'p.name', 'category': 'c.name'},
            'from': [
                'sql_model_test_product p',
                'join sql_model_test_product_cat x on x.product_id=p.id',
                'join sql_model_test_cat c on x.cat_id=c.id',
            ],
            'where': [],
        }


class TestSQLModel(BaseTestCase):
    @pytest.fixture(autouse=True)
    def setup(self, request):
        sql = """
        create table if not exists sql_model_test_product (
            id int(11) not null auto_increment primary key,
            name varchar(255) not null,
            created datetime not null
        );
        create table if not exists sql_model_test_cat (
            id int(11) not null auto_increment primary key,
            name varchar(255) not null
        );
        create table if not exists sql_model_test_product_cat (
            id int(11) not null auto_increment primary key,
            cat_id int(11) not null references sql_model_test_cat (id),
            product_id int(11) not null references sql_model_test_product (id)
        );
        insert into sql_model_test_product (id, name, created)
               values (1, 'defilbrilator', UTC_TIMESTAMP());
        insert into sql_model_test_cat (id, name)
               values (1, 'safety');
        insert into sql_model_test_product_cat (product_id, cat_id)
               values (1, 1);
        insert into sql_model_test_product (id, name, created)
               values (2, 'life jacket', UTC_TIMESTAMP());
        insert into sql_model_test_product_cat (product_id, cat_id)
               values (2, 1);
        insert into sql_model_test_product (id, name, created)
               values (3, 'snake skin jacket',UTC_TIMESTAMP());
        insert into sql_model_test_cat (id, name)
               values (2, 'apparel');
        insert into sql_model_test_product_cat (product_id, cat_id)
               values (3, 2);
        """.split(
            ';'
        )

        def teardown():
            try:
                sql = """
                drop table if exists sql_model_test_product_cat;
                drop table if exists sql_model_test_cat;
                drop table if exists sql_model_test_product;
                """.split(
                    ';'
                )
                execute_all(sql)
            except Exception:
                pass  # No failing here.

        teardown()

        execute_all(sql)

        request.addfinalizer(teardown)

    def test_all(self):
        assert sorted([s.category for s in Summary.objects.all()]) == (
            ['apparel', 'safety']
        )

    def test_count(self):
        assert Summary.objects.all().count() == 2

    def test_one(self):
        c = Summary.objects.all().order_by('category')[0]
        assert c.category == 'apparel'

    def test_get_by_index(self):
        qs = Summary.objects.all().order_by('category')
        assert qs[0].category == 'apparel'
        assert qs[1].category == 'safety'

    def test_get(self):
        c = Summary.objects.all().having('total =', 1).get()
        assert c.category == 'apparel'

    def test_get_no_object(self):
        with self.assertRaises(Summary.DoesNotExist):
            Summary.objects.all().having('total =', 999).get()

    def test_get_many(self):
        with self.assertRaises(Summary.MultipleObjectsReturned):
            Summary.objects.all().get()

    def test_slice1(self):
        qs = Summary.objects.all()[0:1]
        assert [c.category for c in qs] == ['apparel']

    def test_slice2(self):
        qs = Summary.objects.all()[1:2]
        assert [c.category for c in qs] == ['safety']

    def test_slice3(self):
        qs = Summary.objects.all()[:2]
        assert sorted([c.category for c in qs]) == ['apparel', 'safety']

    def test_slice4(self):
        qs = Summary.objects.all()[0:]
        assert sorted([c.category for c in qs]) == ['apparel', 'safety']

    def test_slice5(self):
        assert ['defilbrilator'] == [
            c.product
            for c in ProductDetail.objects.all().order_by('product')[0:1]
        ]
        assert ['life jacket'] == [
            c.product
            for c in ProductDetail.objects.all().order_by('product')[1:2]
        ]
        assert ['snake skin jacket'] == [
            c.product
            for c in ProductDetail.objects.all().order_by('product')[2:3]
        ]

    def test_negative_slices_not_supported(self):
        with self.assertRaises(IndexError):
            Summary.objects.all()[:-1]

    def test_order_by(self):
        c = Summary.objects.all().order_by('category')[0]
        assert c.category == 'apparel'
        c = Summary.objects.all().order_by('-category')[0]
        assert c.category == 'safety'

    def test_order_by_alias(self):
        c = ProductDetail.objects.all().order_by('product')[0]
        assert c.product == 'defilbrilator'
        c = ProductDetail.objects.all().order_by('-product')[0]
        assert c.product == 'snake skin jacket'

    def test_order_by_injection(self):
        with self.assertRaises(ValueError):
            Summary.objects.order_by('category; drop table foo;')[0]

    def test_filter(self):
        c = Summary.objects.all().filter(category='apparel')[0]
        assert c.category == 'apparel'

    def test_filter_raw_equals(self):
        c = Summary.objects.all().filter_raw('category =', 'apparel')[0]
        assert c.category == 'apparel'

    def test_filter_raw_in(self):
        qs = Summary.objects.all().filter_raw(
            'category IN', ['apparel', 'safety']
        )
        assert [c.category for c in qs] == ['apparel', 'safety']

    def test_filter_raw_non_ascii(self):
        uni = 'フォクすけといっしょ'.decode('utf8')
        qs = (
            Summary.objects.all()
            .filter_raw('category =', uni)
            .filter_raw(Q('category =', uni) | Q('category !=', uni))
        )
        assert [c.category for c in qs] == []

    def test_combining_filters_with_or(self):
        qs = ProductDetail.objects.all().filter(
            Q(product='life jacket') | Q(product='defilbrilator')
        )
        assert sorted([r.product for r in qs]) == [
            'defilbrilator',
            'life jacket',
        ]

    def test_combining_raw_filters_with_or(self):
        qs = ProductDetail.objects.all().filter_raw(
            Q('product =', 'life jacket') | Q('product =', 'defilbrilator')
        )
        assert sorted([r.product for r in qs]) == [
            'defilbrilator',
            'life jacket',
        ]

    def test_nested_raw_filters_with_or(self):
        qs = ProductDetail.objects.all().filter_raw(
            Q('category =', 'apparel', 'product =', 'defilbrilator')
            | Q('product =', 'life jacket')
        )
        assert sorted([r.product for r in qs]) == ['life jacket']

    def test_crazy_nesting(self):
        qs = ProductDetail.objects.all().filter_raw(
            Q(
                'category =',
                'apparel',
                'product =',
                'defilbrilator',
                Q('product =', 'life jacket')
                | Q('product =', 'snake skin jacket'),
                'category =',
                'safety',
            )
        )
        # print qs.as_sql()
        assert sorted([r.product for r in qs]) == ['life jacket']

    def test_having_gte(self):
        c = Summary.objects.all().having('total >=', 2)[0]
        assert c.category == 'safety'

    def test_invalid_raw_filter_spec(self):
        with self.assertRaises(ValueError):
            Summary.objects.all().filter_raw(
                """category = 'apparel'; drop table foo;
                   select * from foo where category = 'apparel'""",
                'apparel',
            )[0]

    def test_filter_field_injection(self):
        f = (
            "c.name = 'apparel'; drop table foo; "
            "select * from sql_model_test_cat where c.name = 'apparel'"
        )
        with self.assertRaises(ValueError):
            c = Summary.objects.all().filter(**{f: 'apparel'})[0]
            assert c.category == 'apparel'

    def test_filter_value_injection(self):
        v = (
            "'apparel'; drop table foo; "
            "select * from sql_model_test_cat where c.name"
        )
        query = Summary.objects.all().filter(**{'c.name': v})
        try:
            query[0]
        except IndexError:
            pass
        # NOTE: this reaches into MySQLdb's cursor :(
        executed = query._cursor.cursor._executed
        assert "c.name = '\\'apparel\\'; drop table foo;" in executed, (
            'Expected query to be escaped: %s' % executed
        )

    def check_type(self, val, types):
        assert isinstance(val, types), 'Unexpected type: %s for %s' % (
            type(val),
            val,
        )

    def test_types(self):
        row = Summary.objects.all().order_by('category')[0]
        self.check_type(row.category, unicode)
        self.check_type(row.total, (int, long))
        self.check_type(row.latest_product_date, datetime)

    def test_values(self):
        row = Summary.objects.all().order_by('category')[0]
        assert row.category == 'apparel'
        assert row.total == 1
        assert row.latest_product_date.timetuple()[0:3] == (
            datetime.utcnow().timetuple()[0:3]
        )
