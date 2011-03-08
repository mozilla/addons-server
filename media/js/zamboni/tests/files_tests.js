$(document).ready(function(){

module('File viewer');

test('Show leaf', function() {
    $($('#file-viewer li a')[1]).trigger('click');
    equal($($('#file-viewer li a')[1]).hasClass('open'), true);
    equal($($('#file-viewer li a')[2]).hasClass('hidden'), false);
});

);
