(function() {
    z.page.on('click', 'a.collapse', function() {
        var $this = $(this);
        $this.toggleClass('expanded');
        $this.siblings('.collapse').toggleClass('show');
    });
})();
