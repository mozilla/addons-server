(function() {
// protect globals

$(document).ready(function() {
    "use strict";

    if ($('#perf-results').length) {
        initPerf();
    }
});

function initPerf() {
    "use strict";

    var $perfResults = $('#perf-results'),
        $rows = $perfResults.find('tbody tr').clone(),
        platforms = JSON.parse($perfResults.attr('data-platforms')),
        results = [],
        THRESHOLD = $perfResults.attr('data-threshold');

    // We only show 10 at the beginning and toggle the rest here.
    $('#perf-more a').click(function(e) {
        e.preventDefault();
        $('#perf-more').remove();
        $perfResults.addClass('show-more');
    });

    // Add All to the platforms map.
    platforms[gettext('All')] = 0;

    // Gather all the os-specific data.
    $perfResults.find('tbody tr').each(function(i, e) {
        var p = $(this).attr('data-platforms')
        results.push(p ? JSON.parse(p) : {});
    });

    if ($('#show').length == 0) {
        return;
    }

    // Switch to js strings so we have consistent gettext.
    switchNumbers(gettext('All'));

    $('#show').delegate('a', 'click', function(e) {
        e.preventDefault();
        switchNumbers($.trim($(this).text()));
    });

    // Change numbers and bar graphs to the selected platform data.
    function switchNumbers(selected) {
        var platform = platforms[selected],
            numbers = _.map(results, function(e, i) { return [e[platform] || 0, i]; }),
            $newTbody = $('<tbody>');
        numbers.sort(function(a, b){ return b[0] - a[0]; });
        var worst = numbers[0][0];
        $.each(numbers, function(i, e) {
            var num = e[0], index = e[1];
            if (num > THRESHOLD) {
                var $row = $rows.eq(index).clone();
                $row.find('.slower b').text(num + '%');
                $row.find('.bar').css('width', num / worst * 100 + '%');
                $row.find('.rank b').text(i + 1);
                $row.appendTo($newTbody);
            }
        });
        $perfResults.find('tbody').replaceWith($newTbody);
        showPlatforms(selected);
    }

    // Redisplay the list of names to select the current platform.
    function showPlatforms(selected) {
        var _names = _.keys(platforms);
        _names.sort()
        var names = $.map(_names, function(e) {
            var name = e == selected ? '<b>' + e + '</b>' : e;
            return format('<a href="#">{0}</a>', name);
        });
        $('#show span').html(names.join(', '));
    }
}

})();
