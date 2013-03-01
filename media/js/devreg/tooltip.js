jQuery.fn.tooltip = function(tip_el) {
    var $tip = $(tip_el),
        $msg = $('span', $tip),
        $targets = this,
        timeout = false,
        $tgt, $title, delay;

    function setTip() {
        if (!$tgt) return;
        var pos = $tgt.offset(),
            title = $title.attr('title'),
            html = $title.attr('data-tooltip-html');

        delay = $title.is('[data-delay]') ? $title.attr('data-delay') : 300;

        if (!html && title.indexOf('::') > 0) {
            var title_split = title.split('::');
            $msg.text("");
            $msg.append($("<strong>", {'text': title_split[0].trim()}));
            $msg.append($("<span>", {'text': title_split[1].trim()}));
        } else {
            $msg[html ? 'html' : 'text'](title);
        }

        $title.attr('data-oldtitle', title).attr('title', '');

        var tw  = $tip.outerWidth(false) / 2,
            th  = $tip.outerHeight(false),
            toX = pos.left + $tgt.innerWidth() / 2 - tw - 1,
            toY = pos.top - $tgt.innerHeight() - th - 2;

        timeout = setTimeout(function () {
            $tip.css({
                left:   toX + "px",
                top:    toY + "px"
            }).show();
        }, delay);
    }

    $(document.body).bind("tooltip_change", setTip);

    $targets.on('mouseover', function() {
        $tgt = $(this);
        if ($tgt.hasClass("formerror")) $tip.addClass("error");
        $title = $tgt.attr('title') ? $tgt : $("[title]", $tgt).first();
        if ($title.length) {
            setTip();
        }
    }).on('mouseout', function() {
        clearTimeout(timeout);
        $tip.hide().removeClass("error");
        if ($title && $title.length) {
            $tgt = $(this);
            $title.attr('title', $title.attr('data-oldtitle'))
                  .attr('data-oldtitle', '');
        }
    });
};

// Setting up site tooltips.
$(document).ready(function() {
    $(".tooltip").tooltip("#tooltip");
});
