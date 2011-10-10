(function (){
    "use strict";

    var $rangeSelector = $(".criteria.range ul"),
        $customRangeForm = $("div.custom.criteria");

    $.datepicker.setDefaults({showAnim: ''});
    $("#date-range-start").datepicker();
    $("#date-range-end").datepicker();

    $rangeSelector.click(function(e) {
        var $target = $(e.target).parent();
        var newRange = $target.attr("data-range");

        if (newRange) {
            $rangeSelector.children("li.selected").removeClass("selected");
            $target.addClass("selected");

            if (newRange == "custom") {
                $customRangeForm.removeClass("hidden").slideDown('fast');
            } else {
                $target.trigger('changeview', {range: newRange});
                $customRangeForm.slideUp('fast');
            }
        }
        e.preventDefault();
    });
    $(window).bind('changeview', function(e, newState) {
        function populateCustomRange() {
            var nRange = z.date.normalizeRange(newState.range);
            $("#date-range-start").val(
                z.date.datepicker_format(
                    new Date(nRange.start)
                )
            );
            $("#date-range-end").val(
                z.date.datepicker_format(
                    new Date(nRange.end)
                )
            );
            $rangeSelector.children("li.selected").removeClass("selected");
            $('[data-range="custom"]').addClass("selected");
            $customRangeForm.removeClass("hidden").slideDown('fast');
        }

        if (newState && newState.range) {
            if (!newState.range.custom) {
                var newRange = newState.range,
                    $rangeEl = $('[data-range="' + newRange + '"]');
                if ($rangeEl.length) {
                    $rangeSelector.children("li.selected").removeClass("selected");
                    $rangeEl.addClass("selected");
                    return;
                } else {
                    populateCustomRange();
                }
            } else {
                populateCustomRange();
            }
        }
    });
    $("#date-range-form").submit(function(e) {
        e.preventDefault();
        var start = new Date($("#date-range-start").val()),
            end = new Date($("#date-range-end").val()),
            newRange = {
                custom: true,
                start: z.date.date(start),
                end: z.date.date(end)
            };

        $rangeSelector.trigger('changeview', {range: newRange});
        return false;
    });
})();