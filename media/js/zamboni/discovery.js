$(document).ready(function(){

// How many add-ons they need to have before we start revealing more.
var MIN_ADDONS = 3;

var guids = JSON.parse(location.hash.slice(1));

/* Move Featured Add-ons in place of What Are Add-ons, reveal Recs. */
if (guids.length > MIN_ADDONS) {
    $('#featured-addons').insertBefore('#what-are-addons');
    $('#what-are-addons, #recs').toggle();
}

});
