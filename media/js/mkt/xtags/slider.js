(function(window, document, undefined){

  xtag.addEvent(document, 'mouseup:touch', function(e){
    xtag.removeClass(document.body,'x-tag-slider-drag');
    if (selected){
      xtag.removeClass(selected.xtag.knob, 'x-tag-slider-knob-moving');
      xtag.removeEvent(document, 'mousemove:touch', selected.xtag.mouseMoveFn);
    }
    selected = null;
  });

  var selected = null;
  var mouseMove = function(e){
    if (selected) {
      var range = selected.xtag.knob.parentNode;
      var position = Math.round(
          (e.clientX - range.offsetLeft) /
            (range.offsetWidth) * 1000)/10;
      position = position > 100 ? 100 : position < 0 ? 0 : position;

      var translatedValue = (selected.dataset.max - selected.dataset.min) * (position / 100);
      for (var step = 0; step < selected.xtag.stepTable.length-1; step++){
        var stepValue = selected.xtag.stepTable[step],
          variance = selected.dataset.step/2,
          high = Math.min(selected.dataset.max, stepValue+variance),
          low =  Math.max(selected.dataset.min, stepValue-variance);
        if (translatedValue >= low && translatedValue <=  high){
          break;
        }
      }

      var changed = Number(selected.xtag.input.value) != selected.xtag.stepTable[step];
      if (changed){
        selected.xtag.input.value = selected.xtag.stepTable[step];
        xtag.fireEvent(selected,'change', { value: selected.xtag.input.value });

        if (selected.dataset.snap != undefined){
          selected.xtag.knob.style.marginLeft = ((step/(selected.xtag.stepTable.length-1))*100) + '%';
        }
      }
      if (selected.dataset.snap == undefined){
        selected.xtag.knob.style.marginLeft = position + '%';
      }
      window.getSelection().removeAllRanges();
    }
  }

  var initStepTable = function(min, max, step){
    for (var i = Number(this.dataset.min); i <= Number(this.dataset.max); i = i + Number(this.dataset.step)){
      this.xtag.stepTable.push(Number(i));
    }
  }

  xtag.register('x-slider', {
    onCreate: function(){
      var template = '<label>${label}</label><div class="x-slider-container">'+
        '<div class="x-slider-min">${minLabel}</div>' +
        '<div class="x-slider-range"><div tabindex="0" class="x-slider-knob">&nbsp;</div></div>' +
        '<div class="x-slider-max">${maxLabel}</div></div>' +
        '<input name="${name}" type="hidden" value="${startValue}" />';
      template = template.replace('${label}', this.dataset.label || 'Slider')
        .replace('${minLabel}', this.dataset.minLabel || 0)
        .replace('${maxLabel}', this.dataset.maxLabel || 10)
        .replace('${name}', this.dataset.name || this.id || "")
        .replace('${startValue}', this.dataset.startValue || "");
      this.innerHTML = template;
      this.xtag.knob = xtag.query(this, '.x-slider-knob')[0];
      this.xtag.input = xtag.query(this, 'input')[0];
      this.xtag.stepTable = [];
      this.dataset.step = this.dataset.step || 1;
      this.dataset.min = this.dataset.min || 0;
      this.dataset.max = this.dataset.max || 10;
      initStepTable.call(this,
        Number(this.dataset.min),
        Number(this.dataset.max),
        Number(this.dataset.step));
      if (this.dataset.startValue != undefined){
        this.xtag.knob.style.marginLeft = ((Number(this.dataset.startValue)/(Number(this.dataset.max)))*100) + '%';
      }
      this.xtag.mouseMoveFn = null;
    },
    onInsert: function(){
    },
    events:{
      'mousedown:delegate(.x-slider-knob):touch': function(e, elem) {
        selected = elem;
        selected.xtag.mouseMoveFn = xtag.addEvent(document, 'mousemove:touch', mouseMove);
        xtag.addClass(document.body,'x-tag-slider-drag');
        xtag.addClass(selected.xtag.knob, 'x-tag-slider-knob-moving');
      },
      'click:delegate(.x-slider-range)': function(e, elem){
        if (e.target.className == 'x-slider-range'){
          selected = elem;
          mouseMove(e);
          selected = null;
        }
      },
      'keydown:delegate(.x-slider-knob):keypass(37, 39)': function(e, elem){
        var currentValue = Number(elem.xtag.input.value);
        for (var step = 0; step < elem.xtag.stepTable.length-1; step++){
          if (currentValue == elem.xtag.stepTable[step]){
            break;
          }
        }
        step = e.keyCode == 37 ? step - 1 : step + 1;
        if (step >= 0 && step <= elem.xtag.stepTable.length - 1){
          elem.xtag.knob.style.marginLeft = (step/(elem.xtag.stepTable.length-1)*100) + '%';
          elem.xtag.input.value = elem.xtag.stepTable[step];
          xtag.fireEvent(elem,'change', { value: elem.xtag.stepTable[step] });
        }
      }
    },
    setters: {
      'min:attribute(data-min)': function(value){
        initStepTable.call(this,
          Number(value),
          Number(this.dataset.max),
          Number(this.dataset.step));
      },
      'max:attribute(data-max)': function(value){
        initStepTable.call(this,
          Number(this.dataset.min),
          Number(value),
          Number(this.dataset.step));
      },
      'step:attribute(data-step)': function(value){
        initStepTable.call(this,
          Number(this.dataset.min),
          Number(this.dataset.max),
          Number(value));
      },
      'label:attribute(data-label)': function(value){
        var label = xtag.query(this, "label")[0];
        label.innerHTML = value;
      },
      'minLabel:attribute(data-min-label)': function(value){
        var label = xtag.query(this, ".x-slider-min")[0];
        label.innerHTML = value;
      },
      'maxLabel:attribute(data-max-label)': function(value){
        var label = xtag.query(this, ".x-slider-max")[0];
        label.innerHTML = value;
      }
    },
    getters: {
      'value' : function(){
        return Number(this.xtag.input.getAttribute('value'));
      }
    },
    methods: {

    }
  });

})(this, this.document);
