$(document).ready(function(){

module('format');

test('String Formatting', function() {
    equals(format("{0}{1}", ['a', 'b']), "ab");
    equals(format("{0}{1}", 'a', 'b'), "ab");
    equals(format("{x}{y}", {x: 'a', y: 'b'}), "ab");
});


module('escape_');

test('Entity Escaping', function() {
    function check(s, expected) {
        equal(escape_(s), expected);
    }
    check(undefined, undefined);
    check('', '');
    check("&&<<>>''\"\"", "&amp;&amp;&lt;&lt;&gt;&gt;&#39;&#39;&#34;&#34;");
    check("<script>alert('\"xss\"')</script>&&",
          "&lt;script&gt;alert(&#39;&#34;xss&#34;&#39;)&lt;/script&gt;&amp;&amp;");
});

});
