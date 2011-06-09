(function(){
    "use strict";

    // Add sphinx-like links to headings with ids.
    $(function(){
        var html = '<a class="headerlink" href="#{0}">&para;</a>';
        $(':-moz-any(h1,h2,h3,h4,h5,h6)[id]').each(function() {
          console.log(format(html, $(this).attr('id')));
          $(this).append(format(html, $(this).attr('id')));
        });
    });
})()
