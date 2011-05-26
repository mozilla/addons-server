
/* TODO(jbalogh): save from amo2009. */
/**
 * bandwagon: fire a custom refresh event for bandwagon extension
 * @return void
 */
function bandwagonRefreshEvent() {
    if (document.createEvent) {
        var bandwagonSubscriptionsRefreshEvent = document.createEvent("Events");
        bandwagonSubscriptionsRefreshEvent.initEvent("bandwagonRefresh", true, false);
        document.dispatchEvent(bandwagonSubscriptionsRefreshEvent);
    }
}

/* TODO(jbalogh): save from amo2009. */
/* Remove "Go" buttons from <form class="go" */
$(document).ready(function(){
    $('form.go').change(function() { this.submit(); })
        .find('button').hide();
});


// TODO(jbalogh): save from amo2009.
var AMO = {};

// TODO(jbalogh): save from amo2009.
// Hide the beta installer.
$(document).ready(function(){
    $('a[href="#install-beta"]').click(function(e) {
        e.preventDefault();
        $('.install-beta').slideDown('slow').show();
    });
});
