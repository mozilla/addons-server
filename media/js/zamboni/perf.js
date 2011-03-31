$(document).ready(function() {
    "use strict";

    var $perfResults = $('#perf-results'),
        platforms = JSON.parse($perfResults.attr('data-platforms')),
        results = [];

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
            numbers = $.map(results, function(e) { return e[platform] || 0; }),
            worst = Math.max.apply(null, numbers);
        $perfResults.find('tbody tr').each(function(i, e) {
            var $this = $(this),
                num = results[i][platform] || 0;
            $this.find('.slower b').text(num === 0 ? gettext('N/A') : num + '%');
            $this.find('.bar').css('width', num / worst * 100 + '%');
        });
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
});
