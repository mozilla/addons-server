// Things global to the site should go here, such as re-usable helper
// functions and common ui components.


// Tooltip display. If you give an element a class of 'tooltip', it will
// display a tooltip on hover. The contents of the tip will be the element's
// title attriubute OR the first title attribute in its children. titles are
// swapped out by the code so the native title doesn't display. If the title of
// the element is changed while the tooltip is displayed, you can update the
// tooltip by with the following:
//      $el.trigger("tooltip_change");
jQuery.fn.tooltip = function(tip_el) {
    var $tip = $(tip_el),
        $msg = $('span', $tip),
        $targets = this,
        $tgt, $title;

    function setTip() {
        var pos = $tgt.offset();

        $msg.text($title.attr("title"));
        $title.attr('data-oldtitle', $title.attr('title')).attr('title', '');

        var tw  = $tip.outerWidth() / 2,
            th  = $tip.outerHeight() - 8,
            toX = pos.left + $tgt.innerWidth() / 2 - tw,
            toY = pos.top - $tgt.innerHeight() - th - 1;

        $tip.css({
            left:   toX + "px",
            top:    toY + "px"
        }).show();
    }
    
    $(document.body).bind("tooltip_change", setTip);
    $targets.live("mouseover", function (e) {
        $tgt = $(this);
        $title = $tgt.attr('title') ? $tgt : $("[title]", $tgt).first();
        setTip();

    }).live("mouseout", function (e) {
        $tip.hide();
        $tgt = $(this);
        $title.attr('title', $title.attr('data-oldtitle'))
              .attr('data-oldtitle', '');
    });
};

// Setting up site tooltips.
$(document).ready(function() {
    $(".tooltip").tooltip("#tooltip");
})