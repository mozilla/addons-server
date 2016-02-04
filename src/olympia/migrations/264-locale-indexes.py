# from django.conf import settings

# import elasticutils

# from addons.search import setup_mapping

# def columns():
#     es = elasticutils.get_es()
#     index = settings.ES_INDEXES['default']
#     return es.get_mapping('addons', index)['addons']['properties'].keys()


# def run():
#     if 'name_finnish' not in columns():
#         print 'ok'
#         setup_mapping()
#     else:
#         print 'skippint'
#     assert 'name_finnish' in columns()
