$(function() {
    // Main page
    if($('#editors_main').length) {
        initEditorsMain();
    }
});

function initEditorsMain() {
    var $motd = $('#editors_main .daily-message');
    try {
        if('localStorage' in window && window['localStorage'] !== null) {
            if(window.localStorage['motd_closed'] == $('p', $motd).text()) {
                $motd.hide();
            }
            $motd.find('.close').click(close_motd);
            $motd.find('.close').show();
        }
    } catch(e){}

    function close_motd(e) {
        e.stopPropagation();
        try {
            if('localStorage' in window && window['localStorage'] !== null) {
                window.localStorage['motd_closed'] = $('#editors_main .daily-message p').text();
            }
            $motd.slideUp();
        } catch(e){}
    }
}
