$(document).ready(function(){

    module('File viewer');

    test('Show leaf', function() {
        var viewer = bind_viewer();
        viewer.show_leaf(['foo']);
        equal($($('#files li a')[1]).hasClass('open'), true);
        equal($($('#files li')[2]).hasClass('hidden'), false);
    });

});
