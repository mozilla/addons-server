(function(){

  var head = document.getElementsByTagName('head')[0],
    nodeInserted = function(element, query){
      if (query && element.childNodes.length) xtag.query(element, xtag.tagList).forEach(function(element){ nodeInserted(element) });
      xtag.extendElement(element, true);
      if (element.parentNode) xtag.getOptions(element).onInsert.call(element);
    },
    prefix = (function() {
      var styles = window.getComputedStyle(document.documentElement, ''),
        pre = (Array.prototype.slice.call(styles).join('').match(/moz|webkit|ms/)||(styles.OLink===''&&['o']))[0],
        dom = ('WebKit|Moz|MS|O').match(new RegExp('(' + pre + ')', 'i'))[1];
      return {
        dom: dom,
        lowercase: pre,
        css: '-' + pre + '-',
        js: pre[0].toUpperCase() + pre.substr(1)
      };
    })(),
    mergeOne = function(source, key, current){
      switch (xtag.typeOf(current)){
        case 'object':
          if (xtag.typeOf(source[key]) == 'object') xtag.merge(source[key], current);
          else source[key] = xtag.clone(current);
        break;
        case 'array': source[key] = xtag.toArray(current); break;
        default: source[key] = current;
      }
      return source;
    },
    keypseudo = {
      listener: function(pseudo, fn, args){
        if (!!~pseudo.value.match(/(\d+)/g).indexOf(String(event.keyCode)) == (pseudo.name == 'keypass')){
          args.splice(args.length, 0, this);
          fn.apply(this, args);
        }
      }
    },
    touchMap = {
      mouseenter: 'touchenter',
      mouseleave: 'touchleave',
      mousedown: 'touchstart',
      mousemove: 'touchmove',
      mouseup: 'touchend',
      click: 'touchend'
    };

  xtag = {
    tags: {},
    tagList: [],
    callbacks: {},
    prefix: prefix,
    anchor: document.createElement('a'),
    mutation: window.MutationObserver || window.WebKitMutationObserver || window.MozMutationObserver,
    tagOptions: {
      content: '',
      mixins: [],
      events: {},
      methods: {},
      getters: {},
      setters: {},
      onCreate: function(){},
      onInsert: function(){}
    },
    eventMap: {
      animationstart: ['animationstart', 'oAnimationStart', 'MSAnimationStart', 'webkitAnimationStart'],
      transitionend: ['transitionend', 'oTransitionEnd', 'MSTransitionEnd', 'webkitTransitionEnd'],
      tap: [ 'ontouchend' in document ? 'touchend' : 'mouseup']
    },
    pseudos: {
      delegate: {
        listener: function(pseudo, fn, args){
          var target = xtag.query(this, pseudo.value).filter(function(node){
            return node == args[0].target || node.contains ? node.contains(args[0].target) : false;
          })[0];
          args.splice(args.length, 0, this);
          return target ? fn.apply(target, args) : false;
        }
      },
      preventable: {
        listener: function(pseudo, fn, args){
          if (!args[0].defaultPrevented) fn.apply(this, args);
        }
      },
      attribute: {
        onAdd: function(pseudo){
          this.xtag.attributeSetters = this.xtag.attributeSetters || {};
          this.xtag.attributeSetters[pseudo.value] = pseudo.key.split(':')[0];
        },
        listener: function(pseudo, fn, args){
          fn.call(this, args[0]);
          this.setAttribute(pseudo.value, args[0], true);
        }
      },
      touch: {
        onAdd: function(pseudo, fn){
          this.addEventListener(touchMap[pseudo.key.split(':')[0]], fn, false);
        },
        listener: function(pseudo, fn, args){
          if (fn.touched && args[0].type.match('mouse')) fn.touched = false;
          else {
            if (args[0].type.match('touch')) fn.touched = true;
            args.splice(args.length, 0, this);
            fn.apply(this, args);
          }
        },
        onRemove: function(pseudo, fn){
          this.removeEventListener(touchMap[pseudo.key.split(':')[0]], fn);
        }
      },
      keystop: keypseudo,
      keypass: keypseudo
    },
    mixins: {
      request: {
        onInsert: function(){
          this.src = this.getAttribute('src');
        },
        getters: {
          dataready: function(){
            return this.xtag.dataready;
          }
        },
        setters: {
          src: function(src){
            if (src){
              this.setAttribute('src', src);
              xtag.request(this, { url: src, method: 'GET' });
            }
          },
          dataready: function(fn){
            this.xtag.dataready = fn;
            if (this.xtag.request && this.xtag.request.readyState == 4) fn.call(this, this.xtag.request);
          }
        }
      }
    },

    typeOf: function(obj) {
      return ({}).toString.call(obj).match(/\s([a-zA-Z]+)/)[1].toLowerCase();
    },

    toArray: function(obj){
      var sliced = Array.prototype.slice.call(obj, 0);
      return sliced.hasOwnProperty ? sliced : [obj];
    },

    hasClass: function(element, className){
      return !!~element.className.split(' ').indexOf(className);
    },

    addClass: function(element, className){
      if (!xtag.hasClass(element, className)){
        var name = element.className;
        element.className = name[name.length-1] == ' ' || name.length == 0 ?
          name + className : name + " " + className;
      }
      return element;
    },

    removeClass: function(element, className){
      element.className = element.className.replace(className,'');
      return element;
    },

    toggleClass: function(element, className){
      return !xtag.hasClass(element, className) ? xtag.addClass(element,className) : xtag.removeClass(element, className);
    },

    query: function(element, selector){
      return xtag.toArray(element.querySelectorAll(selector));
    },

    queryChildren: function(element, selector){
      var result = null,
        id = 'x-' + new Date().getTime(),
        attr = '[xtag-temp-id="' + id + '"] > ',
        selector = attr + (selector + '').replace(',', ',' + attr, 'g');
      element.setAttribute('xtag-temp-id', id);
      result = element.parentNode.querySelectorAll(selector);
      element.removeAttribute('xtag-temp-id');
      return xtag.toArray(result);
    },

    defineProperty: function(element, property, accessor, value){
      return document.documentElement.__defineGetter__ ? function(element, property, accessor, value){
        element['__define' + accessor[0].toUpperCase() + 'etter__'](property, value);
      } : function(element, property, accessor, value){
        var obj = { configurable: true };
        obj[accessor] = value;
        Object.defineProperty(element, property, obj);
      };
    }(),

    clone: function(obj) {
      var F = function(){};
      F.prototype = obj;
      return new F();
    },

    merge: function(source, k, v){
      if (xtag.typeOf(k) == 'string') return mergeOne(source, k, v);
      for (var i = 1, l = arguments.length; i < l; i++){
        var object = arguments[i];
        for (var key in object) mergeOne(source, key, object[key]);
      }
      return source;
    },

    wrap: function(original, fn){
      return function(){
        var args = xtag.toArray(arguments);
        original.apply(this, args);
        fn.apply(this, args);
      }
    },

    skipTransition: function(element, fn, bind){
      var duration = prefix.js + 'TransitionDuration';
      element.style[duration] = '0.001s';
      fn.call(bind);
      xtag.addEvent(element, 'transitionend', function(){
        element.style[duration] = '';
      });
    },

    tagCheck: function(element){
      return element.tagName ? xtag.tags[element.tagName.toLowerCase()] : false;
    },

    getOptions: function(element){
      return xtag.tagCheck(element) || xtag.tagOptions;
    },

    register: function(tag, options){
      xtag.tagList.push(tag);
      xtag.tags[tag] = xtag.merge({ tagName: tag }, xtag.tagOptions, xtag.applyMixins(options));
      if (xtag.domready) xtag.query(document, tag).forEach(nodeInserted);
    },

    extendElement: function(element, insert){
      if (!element.xtag){
        element.xtag = {};
        var options = xtag.getOptions(element);
        for (var z in options.methods) xtag.bindMethods(element, z, options.methods[z]);
        for (var z in options.setters) xtag.applyAccessor(element, z, 'set', options.setters[z]);
        for (var z in options.getters) xtag.applyAccessor(element, z, 'get', options.getters[z]);
        xtag.addEvents(element, options.events, options.eventMap);
        if (options.content) element.innerHTML = options.content;
        options.onCreate.call(element);
      }
    },

    bindMethods: function(element, key, method){
      element.xtag[key] = function(){ return method.apply(element, xtag.toArray(arguments)) };
    },

    applyMixins: function(options){
      if (options.mixins) options.mixins.forEach(function(name){
        var mixin = xtag.mixins[name];
        for (var z in mixin) {
          switch (xtag.typeOf(mixin[z])){
            case 'function': options[z] = options[z] ? xtag.wrap(options[z], mixin[z]) : mixin[z];
              break;
            case 'object': options[z] = xtag.merge({}, mixin[z], options[z]);
              break;
            default: options[z] = mixin[z];
          }
        }
      });
      return options;
    },

    applyAccessor: function(element, key, accessor, fn){
      xtag.defineProperty(element, key.split(':')[0], accessor, xtag.applyPseudos(element, key, fn));
    },

    applyPseudos: function(element, key, fn){
      var action = fn, onAdd = {};
      if (key.match(':')){
        key.replace(/:(\w*)(?:\(([^\)]*)\))?/g, function(match, name, value){
          var lastPseudo = action,
            pseudo = xtag.pseudos[name],
            split = {
              key: key,
              name: name,
              value: value
            };
          if (pseudo.onAdd) onAdd[name] = split;
          action = function(){
            return pseudo.listener.apply(element, [split, fn, xtag.toArray(arguments)]);
          }
        });
        for (var z in onAdd) xtag.pseudos[z].onAdd.call(element, onAdd[z], action);
      }
      return action;
    },

    removePseudos: function(element, key, fn){

      if (key.match(':')){
        key.replace(/:(\w*)(?:\(([^\)]*)\))?/g, function(match, name, value){
          var lastPseudo = action,
            pseudo = xtag.pseudos[name],
            split = {
              key: key,
              name: name,
              value: value
            };
          if (pseudo.onRemove) pseudo.onRemove.call(element, split, fn);

        });

      }
    },

    request: function(element, options){
      xtag.clearRequest(element);
      var last = element.xtag.request || {};
        element.xtag.request = options;
      var request = element.xtag.request,
        callbackKey = element.getAttribute('data-callback-key') || 'callback' + '=xtag.callbacks.';
      if (xtag.fireEvent(element, 'beforerequest') === false) return false;
      if (last.url && !options.update && last.url.replace(new RegExp('\&?\(' + callbackKey + 'x[0-9]+)'), '') == element.xtag.request.url){
        element.xtag.request = last;
        return false;
      }
      element.setAttribute('src', element.xtag.request.url);
      xtag.anchor.href = options.url;
      if (xtag.anchor.hostname == window.location.hostname) {
        request = xtag.merge(new XMLHttpRequest(), request);
        request.onreadystatechange = function(){
          element.setAttribute('data-readystate', request.readyState);
          if (request.readyState == 4 && request.status < 400) xtag.requestCallback(element, request);
        };
        ['error', 'abort', 'load'].forEach(function(type){
          request['on' + type] = function(event){
            event.request = request;
            xtag.fireEvent(element, type, event);
          }
        });
        request.open(request.method , request.url, true);
        request.setRequestHeader('Content-Type', 'application/x-www-form-urlencoded');
        request.send();
      }
      else {
        var callbackID = request.callbackID = 'x' + new Date().getTime();
        element.setAttribute('data-readystate', request.readyState = 0);
        xtag.callbacks[callbackID] = function(data){
          request.status = 200;
          request.readyState = 4;
          request.responseText = data;
          xtag.requestCallback(element, request);
          delete xtag.callbacks[callbackID];
          xtag.clearRequest(element);
        }
        request.script = document.createElement('script');
        request.script.type = 'text/javascript';
        request.script.src = options.url = options.url + (~options.url.indexOf('?') ? '&' : '?') + callbackKey + callbackID;
        request.script.onerror = function(error){
          element.setAttribute('data-readystate', request.readyState = 4);
          element.setAttribute('data-requeststatus', request.status = 400);
          xtag.fireEvent(element, 'error', error);
        }
        head.appendChild(request.script);
      }
      element.xtag.request = request;
    },

    requestCallback: function(element, request){
      if (request != element.xtag.request) return xtag;
      element.setAttribute('data-readystate', request.readyState);
      element.setAttribute('data-requeststatus', request.status);
      xtag.fireEvent(element, 'dataready', { request: request });
      if (element.dataready) element.dataready.call(element, request);
    },

    clearRequest: function(element){
      var request = element.xtag.request;
      if (!request) return xtag;
      if (request.script && ~xtag.toArray(head.children).indexOf(request.script)) {
        head.removeChild(request.script);
      }
      else if (request.abort) request.abort();
    },

    addEvent: function(element, type, fn, map){
      var eventKey = type.split(':')[0],
        eventMap = (map || xtag.eventMap || {})[eventKey] || [eventKey];
      var wrapped = xtag.applyPseudos(element, type, fn);
      eventMap.forEach(function(name){
        element.addEventListener(name, wrapped, !!~['focus', 'blur'].indexOf(name));
      });
      return wrapped;
    },

    addEvents: function(element, events, map){
      for (var z in events) xtag.addEvent(element, z, events[z], map);
    },

    removeEvent: function(element, type, fn){
      var eventKey = type.split(':')[0],
        eventMap = (xtag.eventMap || {})[eventKey] || [eventKey];
      eventMap.forEach(function(name){
        element.removeEventListener(name, fn);
      });
    },

    fireEvent: function(element, type, data){
      var event = document.createEvent('Event');
      event.initEvent(type, true, true);
      element.dispatchEvent(xtag.merge(event, data));
    },

    observe: function(element, fn){
      if (xtag.mutation){
        var mutation = new xtag.mutation(function(mutations) {
          var added = [];
          mutations.forEach(function(record){
            var nodes = record.addedNodes, length = nodes.length;
            for (i = 0; i < length && added.indexOf(nodes[i]) == -1; i++){
              added.push(nodes[i]);
              fn(nodes[i], true);
            }
          });
        });
        mutation.observe(element, {
          subtree: true,
          childList: true,
          attributes: !true,
          characterData: false
        });
      }
      else element.addEventListener('DOMNodeInserted', function(event){
        fn(event.target);
      }, false);
    }
  };

  var setAttribute = HTMLElement.prototype.setAttribute;
  HTMLElement.prototype.setAttribute = function(attr, value, setter){
    if (!setter && this.xtag && this.xtag.attributeSetters) this[this.xtag.attributeSetters[attr]] = value;
    setAttribute.call(this, attr, value);
  };

  var createElement = document.createElement;
  document.createElement = function(tag){
    var element = createElement.call(this, tag);
    if (xtag.tagCheck(element)) xtag.extendElement(element);
    return element;
  };

  document.addEventListener('DOMContentLoaded', function(event){
    xtag.observe(document.documentElement, nodeInserted);
    if (xtag.tagList[0]) xtag.query(document, xtag.tagList).forEach(function(element){
      nodeInserted(element);
    });
    xtag.domready = true;
    xtag.fireEvent(document, 'DOMComponentsLoaded');
  }, false);

})();
