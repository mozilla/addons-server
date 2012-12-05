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
            var $tab_label = $(this);
            var $tab = $tab_label.parent();
            $tab_label.on('click.switchtab', _pd(function(evt) {
                if ($tab.hasClass('active') || $tab_label.hasClass('disabled')) {
                    return;
                } else {
                    $hgroup.find('h2').removeClass('active');
                    $tab.addClass('active');
                }
                $this.find('.tab').removeClass('active');
                $this.find('.tab:eq(' + i + ')').addClass('active');

                $this.trigger('tabs-changed', $tab[0]);
            }));
        });

        $this.addClass('initialized').trigger('tabs-setup');
    });
})();
