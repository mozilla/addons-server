(function(){

  var transform = xtag.prefix.js + 'Transform',
    getState = function(el){
      var selected = xtag.query(el, 'x-slides > x-slide[selected="true"]')[0] || 0;
      return [selected ? xtag.query(el, 'x-slides > x-slide').indexOf(selected) : selected, el.firstElementChild.children.length - 1];
    },
    slide = function(el, index){
      var slides = xtag.toArray(el.firstElementChild.children);
      slides.forEach(function(slide){ slide.removeAttribute('selected'); });
      slides[index || 0].setAttribute('selected', true);
      el.firstElementChild.style[transform] = 'translate'+ (el.getAttribute('data-orientation') || 'x') + '(' + (index || 0) * (-100 / slides.length) + '%)';
    },
    init = function(toSelected){
      var slides = this.firstElementChild;
      if (!slides || !slides.children.length || slides.tagName.toLowerCase() != 'x-slides') return;

      var children = xtag.toArray(slides.children),
        size = 100 / (children.length || 1),
        orient = this.getAttribute('data-orientation') || 'x',
        style = orient == 'x' ? ['width', 'height'] : ['height', 'width'];

      xtag.skipTransition(slides, function(){
        slides.style[style[1]] =  '100%';
        slides.style[style[0]] = children.length * 100 + '%';
        slides.style[transform] = 'translate' + orient + '(0%)';
        children.forEach(function(slide){
          slide.style[style[0]] = size + '%';
          slide.style[style[1]] = '100%';
        });
      });

      if (toSelected) {
        var selected = slides.querySelector('[selected="true"]');
        if (selected) slide(this, children.indexOf(selected) || 0);
      }
    };

  xtag.register('x-slidebox', {
    onInsert: init,
    events:{
      'transitionend': function(e){
        if (e.target == this) xtag.fireEvent(this, 'slideend');
      }
    },
    setters: {
      'data-orientation': function(value){
        this.setAttribute('data-orientation', value.toLowerCase());
        init.call(this, true);
      },
    },
    methods: {
      slideTo: function(index){
        slide(this, index);
      },
      slideNext: function(){
        var shift = getState(this);
          shift[0]++;
        slide(this, shift[0] > shift[1] ? 0 : shift[0]);
      },
      slidePrevious: function(){
        var shift = getState(this);
          shift[0]--;
        slide(this, shift[0] < 0 ? shift[1] : shift[0]);
      }
    }
  });

  xtag.register('x-slide', {
    onInsert: function(){
      var ancestor = this.parentNode.parentNode;
      if (ancestor.tagName.toLowerCase() == 'x-slidebox') init.call(ancestor, true);
    }
  });

})();
