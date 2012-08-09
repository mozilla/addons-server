(function(){

  xtag.register('x-listview', {
    onCreate: function(){
      this.yPos = 0;
      this.mouseDown = false;
    },
    events:{
      'mousemove': function(e){
        if (this.mouseDown) {
          this.scrollTop = (this.yPos - e.clientY);
        }
      },
      'mousedown': function(e) {
        this.yPos = this.scrollTop + e.clientY;
        this.mouseDown = true;
      },
      'mouseup': function(e){
        this.mouseDown = false;
        this.yPos = 0;
      },
    },
    methods:{
      getSelected: function(){
        return xtag.query(this, 'x-listitem[selected]');
      }
    }
  });


  xtag.register('x-listitem', {
    onInsert: function(){
      xtag.fireEvent(this,"nodeinserted");
      this.setAttribute('tabindex',0);
    },
    events:{
      'mousedown': function(e) {
        var self = this;
        setTimeout(function(){
          var p = self.parentNode;
          while(p && p.nodeName != 'X-LISTVIEW' && p.nodeName != 'BODY'){
            p = p.parentNode;
          }
          if (p && p.nodeName == 'X-LISTVIEW' && !p.mouseDown){
            var none = self.attributes['selected'] ?
              self.removeAttribute('selected') :
              self.setAttribute('selected', null);
            xtag.fireEvent(self, "itemselected");
          }

        }, 150);
      }
    }
  });

})();
