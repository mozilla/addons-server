$(function() {
    $(window).bind("orientationchange", function(e) {
        $("details").htruncate({textEl: ".desc"});
    });
    $("details").htruncate({textEl: ".desc"});

    $('form.go').change(function() { this.submit(); })
        .find('button').hide();

    $('span.emaillink').each(function() {
        $(this).find('.i').remove();
        var em = $(this).text().split('').reverse().join('');
        $(this).prev('a').attr('href', 'mailto:' + em);
    });

    $("#sort-menu").delegate("select", "change", function() {
        $el = $(this).find("option[selected]");
        if ($el.attr("data-url")) {
            window.location = $el.attr("data-url");
        }
    });

    $(".tabs").each(function() {
        var $strip=$(this);
            $managed = $("#"+$strip.attr("data-manages")),
            isManaged = $managed.length,
            isSlider = isManaged && $managed.hasClass("slider"),
            current = $strip.find(".selected a").attr("href");
        if (isManaged) {
            if (isSlider)
                $managed.css("height", $managed.find(current).outerHeight() + "px");
        } else {
            $managed = $(document.body);
        }
        $strip.delegate("a", "click", function(e) {
            e.preventDefault();
            var $tgt = $(this),
                href = $tgt.attr("href"),
                $pane = $managed.find(href);
            if (current != href && $pane.length && $pane.is(".tab-pane")) {
                current = href;
                $managed.find(".tab-pane").removeClass("selected");
                $pane.addClass("selected");
                $strip.find("li").removeClass("selected");
                $tgt.parent().addClass("selected");
                $tgt.blur();
                if (isManaged && isSlider && $pane.index() >= 0) {
                    $managed.css({
                        "left": ($pane.index() * -100) + "%",
                        height: $pane.outerHeight() + "px"
                    });
                }
            }
        });
    });
    
});

$(".moz-menu .tab a").click(_pd(function() {
    $(".moz-menu").toggleClass("expand");
    this.blur();
}));

$("#sort-menu .label").click(_pd(function() {
    $("#sort-menu").toggleClass("expand");
    this.blur();
}));

function _pd(func) {
    return function(e) {
        e.preventDefault();
        func.apply(this, arguments);
    };
}
