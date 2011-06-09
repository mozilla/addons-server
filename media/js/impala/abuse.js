$(function() {
    var abuse = $("fieldset.abuse");
    if (abuse.find("legend a").length) {
        abuse.find("ol").hide();
        abuse.find("legend a").click(function() {
            abuse.find("ol").slideToggle("fast");
            return false;
        });
        abuse.find("button[type=reset]").click(function() {
            abuse.find("ol").slideToggle("fast");
        });
    }
});