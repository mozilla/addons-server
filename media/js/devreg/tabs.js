(function() {
    // Creates devhubby tabs on elements with class="tabbable".
    /* The DOM structure expected is:
       <node class="tabbable">
         <node class="tab active">
           <h2><a href="#">Tab A</a></h2>
         </node>
         <node class="tab">
           <h2><a href="#">Tab B</a></h2>
         </node>
       </node>
    */
    $('.tabbable').each(function() {
        var $this = $(this);
        $this.find('.active h2').addClass('active');

        var $headers = $this.find('.tab h2'),
            numTabs = $headers.length;

        if (numTabs < 2) {
            return;
        }

        $headers.detach();

        var w = Math.floor(100 / numTabs),
            $hgroup = $('<hgroup></hgroup>');

        $headers.css({'width': w + '%'});
        $hgroup.append($headers);
        $this.prepend($hgroup);

        $hgroup.find('a').each(function(i, e) {
            $(this).on('click.switchtab', function(evt) {
                var $myParent = $(evt.target).parent();
                if ($myParent.hasClass('active')) {
                    evt.preventDefault();
                    return;
                } else {
                    $hgroup.find('h2').removeClass('active');
                    $myParent.addClass('active');
                }
                $this.find('.tab').removeClass('active');
                $this.find('.tab:eq(' + i + ')').addClass('active');
                evt.preventDefault();
            });
        });

        $this.addClass('initialized').trigger('tabs-setup');
    });
})();
