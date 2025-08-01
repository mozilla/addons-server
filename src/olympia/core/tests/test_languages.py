from ..languages import ALL_LANGUAGES, PROD_LANGUAGES, UNSUPPORTED_LANGUAGES


def test_unsupported_languages():
    assert set(PROD_LANGUAGES).issubset(ALL_LANGUAGES)
    assert set(PROD_LANGUAGES).isdisjoint(UNSUPPORTED_LANGUAGES)
