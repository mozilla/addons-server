module('Serializers');


test('getVars', function() {
    function check(s, excl, expected) {
        tests.equalObjects(z.getVars(s, excl), expected);
    }
    check('', false, {});
    check('?', false, {});
    check('?a', true, {});
    check('?a', false, {'a': undefined});
    check('?==a', true, {});
    check('?==a', false, {});
    check('?a=apple&a=apricot', false, {'a': 'apricot'});
    check('?a=apple&b=banana&c=carrot', false,
          {'a': 'apple', 'b': 'banana', 'c': 'carrot'});
    check('?a?a=apple', false, {'a?a': 'apple'});
    check('?a=apple&b?c=banana', false, {'a': 'apple', 'b?c': 'banana'});
    check('?a=b=c&d=e', false, {'a': 'b', 'd': 'e'});
    check('?<script>alert("xss")</script>="a"', false,
          {'&lt;script&gt;alert(&#34;xss&#34;)&lt;/script&gt;': '&#34;a&#34;'});
    check('?"a"=<script>alert("xss")</script>', false,
          {'&#34;a&#34;': '&lt;script&gt;alert(&#34;xss&#34;)&lt;/script&gt;'});
});


test('JSON.parseNonNull', function() {
    function check(s, expected) {
        tests.equalObjects(JSON.parseNonNull(s), JSON.parse(expected));
    }
    check('[]', '[]');
    check('{}', '{}');
    check('{"x": "xxx", "y": "yyy"}',
          '{"x": "xxx", "y": "yyy"}');
    check('{"x": "null", "y": null}',
          '{"x": "null", "y": ""}');
    check('[{"x": "null", "y": null}, {"x": "null", "y": null}]',
          '[{"x": "null", "y": ""}, {"x": "null", "y": ""}]');
    check('[{"w": {"x": null, "y": {"z": null}}}]',
          '[{"w": {"x": "", "y": {"z": ""}}}]');
});
