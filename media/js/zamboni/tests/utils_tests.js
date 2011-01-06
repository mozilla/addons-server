$(document).ready(function(){

module('format');

test('String Formatting', function() {
    equals(format("{0}{1}", ['a', 'b']), "ab");
    equals(format("{0}{1}", 'a', 'b'), "ab");
    equals(format("{x}{y}", {x: 'a', y: 'b'}), "ab");
});

});