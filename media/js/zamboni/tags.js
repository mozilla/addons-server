function addTag() {

    var tagVal = $("#newTag").val();
    var addonid = $('#tagForm input[name="addonid"]').val();

    if($.trim(tagVal)=='' || $.trim(addonid)==''){
        return;
    }
    var post_data = $('#tagForm').serialize()+"&ajax=1";
    var add_ajax_url = $('#tagForm').attr('action');
    $.post(add_ajax_url, post_data, function(data) {
        $("#tagbox").html(data);
        $(".addtagform form")[0].reset();
        $("#tags .addon-tags").removeClass("nojs");
    });
};

 // PHP-compatible urlencode() for Javascript from http://us.php.net/manual/en/function.urlencode.php#85903
 function urlencode(s) {
  s = encodeURIComponent(s);
  return s.replace(/~/g,'%7E').replace(/%20/g,'+');
 };

function remTag(form_data){
    var remove_ajax_url = $('form#tags').attr('action');
    $.post(remove_ajax_url, form_data, function(data){
        $("#tagbox").html(data);
        $(".addtagform form")[0].reset();
        $("#tags .addon-tags").removeClass("nojs");
    });
};

$(document).ready(function(){
    //remove nojs classname so that css will hide the x's
    $("#tags .addon-tags").removeClass("nojs");
    //hide add tag form if you have js
    $(".addtagform ").addClass("hidden");

    $("#addtagbutton").click(function(e){
        addTag();
        e.preventDefault();
        e.stopPropagation();
    });

    $("form#tags .removetag").live("click",function(e){
        if (e.button != 0) return true; // no right-click
        var form = $("form#tags");
        form.find(":input[name='ajax']").val("1");

        var tagid = $(this).val();
        var form_data = form.serialize() + "&tagid=" + tagid;
        remTag(form_data);
        e.preventDefault();
        e.stopPropagation();
    });

    $("#addatag").click(function(e){
        $(".addtagform")
            .removeClass("hidden")
            .attr("style","display:block;");
        $('#newTag').focus();
        e.preventDefault();
        e.stopPropagation();
    });

    $("#newTag").live("keypress",function(e){
        if($.trim($(this).val()) != '' &&  e.keyCode == 13) {
            $("#addtagbutton").click();
            e.preventDefault();
            e.stopPropagation();
        }

    });
})
