(function (){
    "use strict";

    var $rangeSelector = $(".criteria.range ul"),
        $customRangeForm = $("div.custom.criteria"),
        $groupSelector = $(".criteria.group ul"),
        minDate = Date.iso($('.primary').attr('data-min-date')),
        msDay = 24 * 60 * 60 * 1000; // One day in milliseconds.

    $.datepicker.setDefaults({showAnim: ''});
    var $customModal = $("#custom-criteria").modal("#custom-date-range",
                                                   { width: 520,
                                                     hideme: true});
    var $startPicker = $("#start-date-picker").datepicker({
        maxDate: 0,
        minDate: minDate,
        dateFormat: 'yy-mm-dd',
        onSelect: function(dateText) {
            $("#date-range-start").val(dateText);
        }
    });
    var $endPicker = $("#end-date-picker").datepicker({
        maxDate: 0,
        minDate: minDate,
        dateFormat: 'yy-mm-dd',
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

    $groupSelector.on('click', 'a', function(e) {
        var $target = $(this).parent(),
            newGroup = $target.attr("data-group");

        $(this).trigger('changeview', { group: newGroup });
        e.preventDefault();
    });

    // set controls when `changeview` is detected.
    $(window).on('changeview', function(e, newState) {
        if (!newState) return;
        function populateCustomRange() {
            var nRange = normalizeRange(newState.range),
                startStr = nRange.start.iso(),
                endStr = nRange.end.iso();

            // Trim nRange.end by one day if custom range.
            if (newState.range.custom) {
                nRange.end = new Date(nRange.end.getTime() - msDay);
                endStr = nRange.end.iso();
            }

            $("#date-range-start").val(startStr);
            $startPicker.datepicker("setDate", startStr);
            $("#date-range-end").val(endStr);
            $endPicker.datepicker("setDate", endStr);
        }
        if (newState.range) {
            if (!newState.range.custom) {
                var newRange = newState.range,
                    $rangeEl = $('li[data-range="' + _.escape(newRange) + '"]');
                if ($rangeEl.length) {
                    $rangeSelector.children("li.selected")
                                  .removeClass("selected");
                    $rangeEl.addClass("selected");
                } else {
                    $rangeSelector.children("li.selected")
                                  .removeClass("selected");
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

    $("#chart-zoomout").click(_pd);

    $("#date-range-form").submit(_pd(function(e) {
        var start = Date.iso($("#date-range-start").val()),
            end = Date.iso($("#date-range-end").val()),
            newRange = {
                custom: true,
                start: Date.iso(start),
                end: Date.iso(end)
            };
        $rangeSelector.trigger('changeview', {range: newRange});
        $customModal.hider();
    }));
})();
