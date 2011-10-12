(function (){
    "use strict";

    var $rangeSelector = $(".criteria.range ul"),
        $customRangeForm = $("div.custom.criteria"),
        $groupSelector = $(".criteria.group ul");

    $.datepicker.setDefaults({showAnim: ''});
    var $customModal = $("#custom-criteria").modal("#custom-date-range", { width: 520, hideme: false });
    var $startPicker = $("#start-date-picker").datepicker({
        maxDate: 0,
        onSelect: function(dateText) {
            $("#date-range-start").val(dateText);
        }
    });
    var $endPicker = $("#end-date-picker").datepicker({
        maxDate: 0,
        onSelect: function(dateText) {
            $("#date-range-end").val(dateText);
        }
    });

    $rangeSelector.click(function(e) {
        var $target = $(e.target).parent();
        var newRange = $target.attr("data-range");
        if (newRange && newRange != "custom") {
            $target.trigger('changeview', {range: newRange});
        }
        e.preventDefault();
    });

    $groupSelector.delegate('a', 'click', function(e) {
        var $target = $(this).parent(),
            newGroup = $target.attr("data-group");

        $(this).trigger('changeview', { group: newGroup });
        e.preventDefault();
    });

    // set controls when `changeview` is detected.
    $(window).bind('changeview', function(e, newState) {
        if (!newState) return;
        function populateCustomRange() {
            var nRange = z.date.normalizeRange(newState.range),
                startStr = z.date.datepicker_format(new Date(nRange.start)),
                endStr = z.date.datepicker_format(new Date(nRange.end));
            $("#date-range-start").val(startStr);
            $startPicker.datepicker("setDate", startStr);
            $("#date-range-end").val(endStr);
            $endPicker.datepicker("setDate", endStr);
        }
        if (newState.range) {
            if (!newState.range.custom) {
                var newRange = newState.range,
                    $rangeEl = $('li[data-range="' + newRange + '"]');
                if ($rangeEl.length) {
                    $rangeSelector.children("li.selected").removeClass("selected");
                    $rangeEl.addClass("selected");
                } else {
                    $rangeSelector.children("li.selected").removeClass("selected");
                    $('li[data-range="custom"]').addClass("selected");
                }
            } else {
                $rangeSelector.children("li.selected").removeClass("selected");
                $('[data-range="custom"]').addClass("selected");
            }
            populateCustomRange();
        }
        if (newState.group) {
            $groupSelector.children('.selected').removeClass('selected');
            $('li[data-group="' + newState.group + '"]').addClass('selected');
        }
    });
    
    $("#date-range-form").submit(_pd(function(e) {
        var start = new Date($("#date-range-start").val()),
            end = new Date($("#date-range-end").val()),
            newRange = {
                custom: true,
                start: z.date.date(start),
                end: z.date.date(end)
            };
        $rangeSelector.trigger('changeview', {range: newRange});
        $customModal.trigger('close');
    }));
})();