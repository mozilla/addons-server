$(document).ready(function(){


module('something', {
    setup: function() {
        $("#qunit-fixture").append('<div><ul><li>one</li></ul></div>');
    }
});


test("a basic test example", function() {
    ok( true, "this test is fine" );
    var value = "hello";
    equals($('#qunit-fixture div ul li').text(), 'one');
});


});
