// WebTrends SmartSource Data Collector Tag v10.2.1
// Copyright (c) 2012 Webtrends Inc.  All rights reserved.
// Tag Builder Version: 4.0.170.0
// Created: 4/16/2012 11:32:32 PM
(function (_window, _document, _navigator, _location) {
	if (_window.Webtrends) {
		return;
	}
	//TODO port to lite.
	function extendArray(in_array) {
		if (in_array) {
			if (!in_array.forEach) in_array.forEach = function (D, E) {
				var C = E || window;
				for (var B = 0, A = this.length; B < A; ++B) {
					D.call(C, this[B], B, this)
				}
			};
			if (!in_array.filter) in_array.filter = function (E, F) {
				var D = F || window;
				var A = [];
				for (var C = 0, B = this.length; C < B; ++C) {
					if (!E.call(D, this[C], C, this)) {
						continue
					}
					A.push(this[C])
				}
				return A
			};
			if (!in_array.indexOf) in_array.indexOf = function (B, C) {
				var C = C || 0;
				for (var A = 0; A < this.length; ++A) {
					if (this[A] === B) {
						return A
					}
				}
				return -1
			}
		}
		return in_array;
	}
	var Webtrends = {
		dcss: {},
		plugins: {},
		dcssIdx: 0,
		gWtId: {},
		addEventListener: _window.addEventListener ?
		function (el, eType, fn) {
			el.addEventListener && el.addEventListener(eType, fn, false);
		} : //or if IE use attachEvent
		function (el, eType, fn) {
			el.attachEvent && el.attachEvent("on" + eType, fn, false);
		},
		events: {},
		version: "10.2.1",
		qryparams: {},
		hasLoaded: false,
		dcsdelay: 25,//ms to delay for setTimeout on MultiTrack and other async operations
		init: function () {
			if (_location.search) {
				Webtrends.qryparams = Webtrends.getQryParams(_location.search);
			}
			if (_window['webtrendsAsyncInit'] && !_window['webtrendsAsyncInit']['hasRun']) {
				_window['webtrendsAsyncInit']();
				_window['webtrendsAsyncInit']['hasRun'] = true;
			}
			Webtrends.addEventListener(_window, 'load', function (e) {
				Webtrends.hasLoaded = true;
			});
		},
		isFn: function (what) {
			return Object.prototype.toString.call(what) === "[object Function]";
		},
		/*
		 * Useful when you want to convert key value pair objects {foo:"boo", goo:"foo"} to arrays like so [{foo:"boo}, {goo:"foo"}]
		 *	so you can use the array filter, foreach, indexOf methods...
		 */
		objectToKVPArray: function (object) {
			var tmp = [];
			for (var key in object) {
				if (object.hasOwnProperty(key) && object[key] != "" && object[key] != undefined && (typeof object[key] != "function")) tmp.push({
					'k': key,
					'v': object[key]
				});
			}
			return tmp;
		},
		extend: function (target, source, overwrite) {
			for (key in source) {
				if (overwrite || typeof target[key] === 'undefined') {
					target[key] = source[key];
				}
			}
			return target;
		},
		/**
		 * Finds a Selector engine.   OR, you can set it explicitly before
		 * calling Webtrends.init();
		 *
		 * This selector engine is only needed if you are using addSelectors()
		 *
		 * For Example:
		 *  Webtrends.find = function(sel){ return window.Sizzle(sel); };
		 *
		 *  Webtrends.find = window.Sizzle;
		 */
		find: function (sel) {
			if (!Webtrends.selectorEngine) {
				Webtrends.selectorEngine = Webtrends.findSelector();
			}
			return Webtrends.selectorEngine(sel);
		},
		findSelector: function () {
			var tmp = /MSIE (\d+)/.exec(_navigator.userAgent);
			var ie = (tmp) ? tmp[1] : 99;
			if (_document.querySelectorAll && _document.body && ie > 8) {
				var body = _document.body;
				return function (sel) {
					return body.querySelectorAll(sel)
				}
			}
			if (_window.jQuery) {
				return _window.jQuery.find;
			}
			if (_window.Sizzle) {
				return _window.Sizzle;
			}
			if (_window.YAHOO && YAHOO.util && YAHOO.util.Selector) {
				return YAHOO.util.Selector.query;
			}
			if ('qwery' in _window) { // not fully css3
				return qwery;
			}
			if (_window.YUI) {
				YUI().use('node', function (Y) {
					return Y.all;
				})
			}
			if (_document.querySelectorAll) {
				var body = _document.body;
				if (body) {
					return function (sel) {
						return body.querySelectorAll(sel)
					}
				} else {
					return function (sel) {
						return [];
					}
				};
			}
			return function (NoopSelEngine) {
				return [];
			};
		},
		getQryParams: function (query) {
			var keyValuePairs = query.split(/[&?]/g);
			var params = {};
			try {
				for (var i = 0, n = keyValuePairs.length; i < n; ++i) {
					var m = keyValuePairs[i].match(/^([^=]+)(?:=([\s\S]*))?/);
					if (m && m[1]) {
						var key = decodeURIComponent(m[1]);
						if (params[key]) {
							params[key] = [params[key]];
							params[key].push(decodeURIComponent(m[2]));
						} else {
							params[key] = decodeURIComponent(m[2]);
						}
					}
				}
			} catch (e) {
				this.errors.push(e);
				this.errorlogger(e);
			};
			return params;
		},
		loadJS: function (src, isasync, theCallback) {
			if (arguments.length < 2) isasync = true;
			s = _document.createElement("script");
			s.type = "text/javascript";
			s.async = isasync;
			s.src = src;
			s2 = _document.getElementsByTagName("script")[0];
			s2.parentNode.insertBefore(s, s2);
		},
		elemOfEvent: function (evt, tag) {
			var e = evt.target || evt.srcElement;
			while (e && e.tagName && (e.tagName.toLowerCase() != tag.toLowerCase())) {
				e = e.parentElement || e.parentNode;
			}
			return e;
		},
		dcsEncode: function (S) {
			return (typeof (encodeURIComponent) == "function") ? encodeURIComponent(S) : escape(S);
		},
		multiTrack: function () {
			for (var dcsid_i in Webtrends.dcss) {
				var dcs = Webtrends.dcss[dcsid_i];
				dcs.dcsMultiTrack(arguments[0]);
			}
			return false;
		},
		addTransform: function (f, event, dcs) {
			if (!event) event = 'collect';
			if(dcs) {
				Webtrends.bindEvent('transform.' + event, f, dcs);
			}else{
				Webtrends.bindEvent('transform.' + event, f);
			}

			return this;
		},
		/* Add an event:  event name (str) and callback fn
		 *  the fn can have an attribute of fn.onetime (true|false)
		 * if true, it will be removed after usage once
		 */
		bindEvent: function (event, fn, dcs) {
			if(!event || !fn || event == "" || !Webtrends.isFn(fn))
				return;
			//create this event lazily so its not fired for everyone.
			if (event === "wtmouseup" && !Webtrends.onMouseupBound) {
				Webtrends.addEventListener(_document, "mouseup", function (e) {
					if (!e) e = window.event;
					Webtrends.broadcastEvent(event, {'event': e});
				});
				Webtrends.onMouseupBound = true;
			}

			if (!Webtrends.events[event]) {
				Webtrends.events[event] = {};
			}

			function addToDcsQueue(dcs, fn){
				if(!Webtrends.events[event][dcs.dcssID]){
					Webtrends.events[event][dcs.dcssID] = extendArray([]);
				}
				Webtrends.events[event][dcs.dcssID].push(fn);
			}

			if(dcs) {
				addToDcsQueue(dcs, fn);
			}else{
				for(dcsid in Webtrends.dcss){
					addToDcsQueue(Webtrends.dcss[dcsid], fn);
				}
			}
		},
		broadcastEvent: function (event,  o) {
			for (dcsid in Webtrends.dcss) {
				Webtrends.fireEvent(event, Webtrends.dcss[dcsid], o);
			}
		},
		_callFn: function (dcs, fn, dispose, o){
			if (typeof fn === "function") {
				if (fn['onetime']) {
					dispose.push(fn);
					return true;
				} else {
					fn(dcs, o);
					return false;
				}
			}
		},
		fireEvent: function (event, dcs, o) {
			var dispose = extendArray([]);
			if (Webtrends.events[event] && Webtrends.events[event][dcs.dcssID]) {
				var callArray = Webtrends.events[event][dcs.dcssID];
				if(!callArray.length)return;
				for (var i = callArray.length-1; i >= 0 ; i--) {
					var fn = callArray[i];
					if(Webtrends._callFn(dcs, fn, dispose, o))
						callArray.pop();
				}
			}
			// you will hit a recursive loop if you do these above
			dispose.forEach(function (fn) {
				fn(dcs, o);
			});
		},
		registerPlugin: function (plugin, callback) {
			var hasDcsOwner = false;
			for (dcsid in Webtrends.dcss) {
				var dcs = Webtrends.dcss[dcsid];
				if (plugin in dcs.plugins) {
					hasDcsOwner = true;
					dcs.registerPlugin(plugin, callback);
				}
			}
			if (!hasDcsOwner) callback({
				noOwner: true
			});
		},
		dcsDebug: function () {
			for (dcsid in Webtrends.dcss) {
				Webtrends.dcss[dcsid].dcsDebug();
			}
		}
	};
	//Alias, used to get Closure Compiler to shorten the ref.
	var _fireEvent = Webtrends.fireEvent;
	var _bindEvent = Webtrends.bindEvent;

	/* *************************************************************************
	 *  The dcs object are the individual tag objects.  Each object has it's own
	 *  config, which includes it's own dcsid, and/or domain (aka the collection server).
	 *  Created more than one of these will allow you to dual tag the site.
	 ****************************************************************************/
	Webtrends.dcs = function () {
		var dcs = this;
		this.exre = (function () {
			return (_window.RegExp ? new RegExp("dcs(uri)|(ref)|(aut)|(met)|(sta)|(sip)|(pro)|(byt)|(dat)|(p3p)|(cfg)|(redirect)|(cip)", "i") : "");
		})();
		this.re = {};
		//Fields exported for Closure Compiler
		this.plugins=this['plugins']={};
		this.WT=this['WT']={};
		this.DCS=this['DCS']={};
		this.DCSext=this['DCSext']={};
		this.dcssID=this['dcssID']= "dcsobj_" + Webtrends.dcssIdx++;//unique id for this tag
		this.images=this['images']=[];
        this.errors=this['errors']=[];

		//non-exported fields
		this.cookieExpiration= {};
		this.images=[];
		this.navigationtag=[];
		this._selectors=[];
		this._onsitedoms=[];
		this._downloadtypes=[];
		this.adclickparam="";
		this.FPCsessionOnly=false;
		this.plugInWaitCount=0;
		this.gWtAccountRollup="";
		this.gTempWtId="";
		this.onMouseupBound=false;
		return this;
	};
	Webtrends.dcs.prototype = {
		init: function (config) {
			this.config = config;
			var self = this;
			function sd(prop, def) {
				return config.hasOwnProperty(prop) ? config[prop] : def
			}
			this.errorlogger = sd('errorlogger', function (log) {});
			//Fields with =this[x]= are exported for Closure Compiler
			this.dcsid = this['dcsid'] = config['dcsid'];
			this.queue = this['queue'] = sd('queue', []);
			this.domain = this['domain'] = sd('domain', "statse.webtrendslive.com");
			this.timezone = this['timezone'] = sd('timezone', -8);
			this.fpcdom = sd('fpcdom', "");
			this.enabled = this['enabled'] = sd('enabled', true);
			this.i18n = this['i18n'] = sd('i18n', true);
			this.re = (function () {
				return (_window.RegExp ? (self.i18n ? {
					"%25": /\%/g,
					"%26": /\&/g,
					"%23": /\#/g
				} : {
					"%09": /\t/g,
					"%20": / /g,
					"%23": /\#/g,
					"%26": /\&/g,
					"%2B": /\+/g,
					"%3F": /\?/g,
					"%5C": /\\/g,
					"%22": /\"/g,
					"%7F": /\x7F/g,
					"%A0": /\xA0/g
				}) : "");
			})();
			this.fpc = this['fpc'] = sd('fpc', "WT_FPC");
			this.disablecookie = sd('disablecookie', false);
			if (config['metanames']) {
				var mt = config['metanames'].toLowerCase();
				this.metanames = extendArray(mt.split(","));
			}
			this.vtid = this['vtid'] = sd('vtid', undefined);
			this.paidsearchparams = sd('paidsearchparams', "gclid");
			this.splitvalue = this['splitvalue'] = sd('splitvalue', "");
			Webtrends.dcsdelay = config['dcsdelay'] || Webtrends.dcsdelay;
			this.delayAll = this['delayAll'] = sd('delayAll', false);
			this.preserve = this['preserve'] = sd('preserve', true);
			this.navigationtag = extendArray(sd('navigationtag', "div,table").toLowerCase().split(","));
			this._onsitedoms = sd('onsitedoms', "");
			if (!Webtrends.isFn(this._onsitedoms.test)) {
				this._onsitedoms = extendArray(this._onsitedoms.toLowerCase().split(","));
				this._onsitedoms.forEach(function (elm, idx, arr) {
					arr[idx] = elm.replace(/^\s*/, "").replace(/\s*$/, "");
				});
			}
			this._downloadtypes = extendArray(sd('downloadtypes', "xls,doc,pdf,txt,csv,zip,docx,xlsx,rar,gzip").toLowerCase().split(","));
			this._downloadtypes.forEach(function (elm, idx, arr) {
				arr[idx] = elm.replace(/^\s*/, "").replace(/\s*$/, "");
			});
			if (sd('adimpressions', false)) this.adclickparam = sd('adsparam', "WT.ac");
			this.cookieExp = this['cookieExp'] = sd('cookieexpires', 63113851500);
			if (this.cookieExp != 0) {
				this.cookieExp = (this.cookieExp < 63113851500) ? this.cookieExp : 63113851500;
				this.cookieExpiration = new Date(this.getTime() + this.cookieExp); // default is 63113851500 (1.99 years)
				this.FPCsessionOnly = false;
			} else {
				this.FPCsessionOnly = true;
			}
			//check if we turn on automatic event tracking
			//merge in legacy page events array.
 			extendArray(sd('pageEvents',[])).forEach(function (a) {
				config[a.toLowerCase()]=true;
				this._NoopDontCompileMeOut = true;//To prevent ClosureCompiler form compiling out.
			});
			if (sd('offsite', false)) this.addOffsiteTracking();
			if (sd('download', false)) this.addDownloadTracking();
			if (sd('anchor', false)) this.addAnchorTracking();
			if (sd('javascript', false)) this.addJavaScriptTracking();
			if (sd('rightclick', false)) this.addRightClickTracking();
			// if the object has a privateFlag, it's a second tag, so skip this call.
			if (!sd('privateFlag', false))
				Webtrends.dcss[this.dcssID] = this;
			this.plugins = config['plugins'] || {};
			this._processPlugins();
			// kick off wtid.js request, if needed and not private.
			if(!Webtrends.gWtId[this.domain])
				Webtrends.gWtId[this.domain]="";
			if (!sd('privateFlag', false))
				this.dcsGetId(this.dcssID);
			this.checkReady();
			return this;
		},
		_processPlugins: function(){
			/* Load plugins.  examples of plugins =
		 	plugins:{PluginName:{src:"/scripts/test.plugin.js"}} //Holds tracking up but timesout after 10 seconds.
			plugins:{PluginName:{src:"/scripts/test.plugin.js", timeout:500}} //Holds tracking up but timesout after 500ms.
			plugins:{PluginName:{src:"/scripts/test.plugin.js", async:true}} //Doesn't hold up tracking at all. */
			for (var plugin in this.plugins) {
				var plug = this.plugins[plugin];
				if (!Webtrends.plugins[plugin]) {
					Webtrends.plugins[plugin] = plug;
					var src = plug['src'];
					if(Webtrends.isFn(src)) //plugins can be loaded from a src file or via a function.
						_window.setTimeout(
							function(src_in){ return function(){ src_in(); }; }(src)//closure the src function.
						, 1);
					else
						Webtrends.loadJS(src, false);
				}
				if (!plug.async) {
					/* not all plugins need to hold up the first collection event.
					async=true means collection can continue without waiting for
					this plugin */
					var self = this;
					plug.loaded = false;
					this.plugInWaitCount++;
					if(plug.timeout)
						_window.setTimeout(function (plug_in) {
							return function(){
								if (plug_in.loaded) return;
								plug_in.timedout = true;
								self.plugInWaitCount--;
								self.checkReady();
						}}(plug), plug.timeout);
				}
			}
		},
		dcsGetIdCallback: function (a) {
			if (typeof (a) != "undefined") {
				if(!Webtrends.gWtId[this.domain] && a['gTempWtId'])//Only set gWtId once.
					Webtrends.gWtId[this.domain] = a['gTempWtId'];
				this.gTempWtId = a['gTempWtId'];
				if(!Webtrends.gWtId[this.domain] && a['gWtId'])//Only set gWtId once.
					Webtrends.gWtId[this.domain] = a['gWtId'];
				this.gWtAccountRollup = a['gWtAccountRollup'];
			}
			this.plugInWaitCount--;
			this.checkReady();
		},
		/*
		 *  If not First Party Cookie (FPC) then do a JSONP call to wtid.js to load the ID.
		 *  returns true: if we already have a FPC
		 *          false: if we need needed to call wtid.js
		 */
		dcsGetId: function (dcssID) {
			if ((_document.cookie.indexOf(this.fpc + "=") == -1) && (_document.cookie.indexOf("WTLOPTOUT=") == -1) && !this.disablecookie) {
				// no current id
				if (this.enabled) {
					var src = "//" + this.domain + "/" + this.dcsid + "/wtid.js?callback=Webtrends.dcss." + dcssID + ".dcsGetIdCallback";
					Webtrends.loadJS(src, true);
					this.plugInWaitCount++;
				}
				return false;
			}
			return true;
		},
		registerPlugin: function (plugin, callback) {
			var plug = this.plugins[plugin];
			if(plug){
				if( Webtrends.isFn(callback) ){
					if(!this.isReady())
						_bindEvent('onready',
							function(callback_in, self, plug_in){
								var cb = function(){callback_in(self, plug_in);};
								cb["onetime"] = true;
								return cb;
							}(callback,this,plug)//closure the callback
						, this);
					else
						callback(this, plug);
				}
				plug.loaded = true;
				if (!plug.async && !plug.timedout) /* not all plugins need to hold up the first collection event */
					this.plugInWaitCount--;
			}
			this.checkReady();
		},
		/* returns true if the tag is ready; meaning all plugins have loaded and we have a vid.*/
		isReady: function () {
			return (this.plugInWaitCount <= 0);
		},
		/* ***********************
		 * Checks to see if all plugins have been loaded before calling setReady
		 */
		checkReady: function () {
			if (this.plugInWaitCount <= 0)
				this.setReady();
		},
		/*
		/* ***********************
		* it flushs the commands(aka hits) queued up in the individual tag's queue.
		* Flushing them just calls the tag's doAction method.
		*
		* It then calls redirectqueue which replaces the tag's command array's push method with
		* doAction, so no more commands get queued up.
		*/
		setReady: function () {
			if(this._readySet)
				return;
			_fireEvent('onready', this);
			this.flushqueue();
			this.redirectqueue();
			this._readySet = true;
		},
		/* ***********************
		 * Takes each cmd objects and passes it to doAction and then removes the cmd from the array(queue).
		 * the cmd object has to members {action:"FunctionNameToCall", message:"AnObjectToPassAsAnArgument"}
		 */
		flushqueue: function () {
			for (var i = 0; i < this.queue.length; i++) {
				this.doAction(this.queue[i]);
			}
            this.queue=[];
		},
		/* ***********************
		 * Takes the queue(which is basically an array that "had" actions queued up in it) and replaces it's
		 * push method with a new one, that calls doAction directly.
		 *
		 * It's expected that you called flushqueue before calling redirectqueue
		 */
		redirectqueue: function () {
			var dcs = this;
			this.queue.push = function (cmd) {
				dcs.doAction(cmd);
			};
		},
		addTransform: function (f, event){
			Webtrends.addTransform(f,event,this);
		},
		/* ***********************
		 *   Uses native queryselector, jQuery, Sizzle, YUI Selector engines
		 *   to selectively find and attach events for multiTrack
		 */
		addSelector: function (selector, o_in) {
			var dcs = this;
			selector = selector.toLowerCase();
			//This is a basic and empty multitrack object, that should have every key.
			var o_base = {
				'domEvent': 'click',
				'callback': undefined,
				'argsa': [],
				'args': {},
				'delayTime': undefined,
				'transform': undefined,
				'filter': undefined,
				'finish': undefined
			};
			var o_args = Webtrends.extend(o_base, o_in, true);//merge base and in
			_bindEvent("wtmouseup", function (dcs_ignore, o_evt) { /*  ignore dcs_in.  Instead we will do a closure around the creator's dcs object */
				dcs.addSelectorReal(dcs, selector, Webtrends.extend(o_evt, o_args, true)); //merge the event object the input multitrack object.
			}, dcs);
			return this;
		},
		sendSelectorTrack: function (dcs, o, srcElm, type) {
			o['element'] = srcElm;
			if (type === "form" || type === "input" || type === 'button') {
				o['domEvent'] = 'submit';
			}
			dcs._multiTrack(o);
		},
		addSelectorReal: function (dcs, selector, o) {
			var find = Webtrends['find'];
			if (find && o['event']) {
				var srcElm = Webtrends.elemOfEvent(o["event"], "A");
				var type = srcElm.tagName ? srcElm.tagName.toLowerCase() : ""; /*in the case of a simple selector don't bother looping through them all*/
				if (selector === 'a' && type === 'a') return this.sendSelectorTrack(dcs, o, srcElm, type);
				var els = find(selector),
					els2 = [];
				if (!els || !srcElm) return; // nothing found
				if (els && els.length) {
					for (var i = 0; i < els.length; i++) {
						if (els[i] === srcElm) {
							this.sendSelectorTrack(dcs, o, srcElm, type)
							break;
						}
					}
				}
			}
		},
		/*
		 * This function takes the name of the store and returns an object which has
		 * the key value pairs from that store.
		 */
		dcsGetCookie: function (name, object) {
			var element = extendArray(_document.cookie.split("; ")).filter(function (el) {
				return el.indexOf(name + '=') != -1;
			})[0];
			if (!element || element.length < name.length + 1) return false;
			var crumbs = element.split(name + '=')[1].split(':');
			extendArray(crumbs).forEach(function (a) {
				var b = a.split('=');
				object[b[0]] = b[1]; //map key to value
			});
			return true;
		},
		dcsSaveCookie: function (storename, object, cookieMetaData) {
			var data = [];
			var kvpArr = Webtrends.objectToKVPArray(object);
			extendArray(kvpArr).forEach(function (el) {
				data.push(el['k'] + "=" + el['v']);
			});
			data = data.sort().join(":"); //Sort because our legacy tags require 'id' to be first and they may read this cookie too.
			_document.cookie = storename + "=" + data + cookieMetaData;
		},
		dcsIsFpcSet: function (name, id, lv, ss) {
			var c = {};
			if (this.dcsGetCookie(name, c)) return ((id == c["id"] && lv == c["lv"] && ss == c["ss"]) ? 0 : 3);
			return 2;
		},
		/*
		 * This function can be used by external javascript, if they want
		 * to read our internal cookie object.  Changes made to returned object
		 * don't persist.
		 * Returns an object with all the cookie crumbs as keys.
		 * For Example:
		 * dcs.dcsGetFPC()["ss"] //is the session id
		 */
		dcsGetFPC:function () {
			var obj = {};
			this.dcsGetCookie(this.fpc, obj);
			return obj;
		},
		dcsFPC: function () {
			if (_document.cookie.indexOf("WTLOPTOUT=") != -1) {
				return;
			}
			var WT = this.WT;
			var name = this.fpc;
			var dCur = new Date();
			var adj = (dCur.getTimezoneOffset() * 60000) + (this.timezone * 3600000);
			dCur.setTime(dCur.getTime() + adj);
			var dSes = new Date(dCur.getTime());
			WT["co_f"] = WT["vtid"] = WT["vtvs"] = WT["vt_f"] = WT["vt_f_a"] = WT["vt_f_s"] = WT["vt_f_d"] = WT["vt_f_tlh"] = WT["vt_f_tlv"] = "";
			var c = {};
			if (!this.dcsGetCookie(name, c)) {
				if (this.gTempWtId.length) {
					if(Webtrends.gWtId[this.domain].length)
						WT["co_f"] = Webtrends.gWtId[this.domain]; //Use the same vid if their is one.
					else
						WT["co_f"] = this.gTempWtId;
					WT["vt_f"] = "1";
				} else if (Webtrends.gWtId[this.domain].length) {
					WT["co_f"] = Webtrends.gWtId[this.domain];
				} else {
					WT["co_f"] = "2";
					var curt = dCur.getTime().toString();
					for (var i = 2; i <= (32 - curt.length); i++) {
						WT["co_f"] += Math.floor(Math.random() * 16.0).toString(16);
					}
					WT["co_f"] += curt;
					WT["vt_f"] = "1";
				}
				if (this.gWtAccountRollup.length == 0) {
					WT["vt_f_a"] = "1";
				}
				WT["vt_f_s"] = WT["vt_f_d"] = "1";
				WT["vt_f_tlh"] = WT["vt_f_tlv"] = "0";
			} else {
				var id = c["id"];
				var lv = parseInt(c["lv"]);
				var ss = parseInt(c["ss"]);
				if ((id == null) || (id == "null") || isNaN(lv) || isNaN(ss)) {
					return;
				}
				WT["co_f"] = id;
				var dLst = new Date(lv);
				WT["vt_f_tlh"] = Math.floor((dLst.getTime() - adj) / 1000);
				dSes.setTime(ss);
				if ((dCur.getTime() > (dLst.getTime() + 1800000)) || (dCur.getTime() > (dSes.getTime() + 28800000))) {
					WT["vt_f_tlv"] = Math.floor((dSes.getTime() - adj) / 1000);
					dSes.setTime(dCur.getTime());
					WT["vt_f_s"] = "1";
				}
				if ((dCur.getDate() != dLst.getDate()) || (dCur.getMonth() != dLst.getMonth()) || (dCur.getFullYear() != dLst.getFullYear())) {
					WT["vt_f_d"] = "1";
				}
			}
			WT["co_f"] = escape(WT["co_f"]);
			WT["vtid"] = (typeof (this.vtid) == "undefined") ? WT["co_f"] : (this.vtid || "");
			WT["vtvs"] = (dSes.getTime() - adj).toString();
			var expiry = (this.FPCsessionOnly) ? "":("; expires=" + this.cookieExpiration.toGMTString());
			var cookieMetaData = expiry + "; path=/" + (((this.fpcdom != "")) ? ("; domain=" + this.fpcdom) : (""));
			var cur = dCur.getTime().toString();
			var ses = dSes.getTime().toString();
			c["id"] = WT["co_f"];
			c["lv"] = cur;
			c["ss"] = ses;
			this.dcsSaveCookie(name, c, cookieMetaData);
			var rc = this.dcsIsFpcSet(name, WT["co_f"], cur, ses);
			if (rc != 0) {
				WT["co_f"] = WT["vtvs"] = WT["vt_f_s"] = WT["vt_f_d"] = WT["vt_f_tlh"] = WT["vt_f_tlv"] = "";
				if (typeof (this.vtid) == "undefined") {
					WT["vtid"] = "";
				}
				WT["vt_f"] = WT["vt_f_a"] = rc;
			}
		},
		track: function () {
			try {
				var o;
				if (arguments && arguments.length > 1) {
					o = {
						'argsa': Array.prototype.slice.call(arguments)
					};
				} else if (arguments.length === 1) {
					o = arguments[0];
				}
				if (typeof o === "undefined") o = {
					element: undefined,
					event: undefined,
					argsa: []
				};
				if (typeof o['argsa'] === "undefined") o['argsa'] = [];
				this.enQueue('collect', o);
				return this;
			} catch (e) {
				this.errors.push(e);
				this.errorlogger(e);
			}
		},
		dcsMultiTrack: function (o) {
			if (o && o.length > 1) {
				o = {
					'argsa': Array.prototype.slice.call(arguments)
				};
			}
			this._multiTrack(o);
		},
		_multiTrack: function (o) {
			try {
				if (typeof o === "undefined") {
					return;
				}
				this.enQueue('multitrack', o);
				if (o['delayTime']) {
					//if the object in the multitrack call has a dcsTime key.
					var delay = Number(o['delayTime']);
					this.spinLock((isNaN(delay)) ? Webtrends.dcsdelay : delay);
				} else if (this.delayAll) {
					//if delayAll flag is true, set in dcs.init from the config object.
					this.spinLock(Webtrends.dcsdelay);
				}
				return false;
			} catch (e) {
				this.errors.push(e);
				this.errorlogger(e);
			}
		},
		dcsCleanUp: function () {
			this.DCS = {};
			this.WT = {};
			this.DCSext = {};
			if (arguments.length % 2 == 0) {
				this.dcsSetProps(arguments);
			}
		},
		dcsSetProps: function (args) {
			if (!args) return;
			for (var i = 0, al = args.length; i < al; i += 2) {
				if (args[i].indexOf('WT.') == 0) {
					this.WT[args[i].substring(3)] = args[i + 1];
				} else if (args[i].indexOf('DCS.') == 0) {
					this.DCS[args[i].substring(4)] = args[i + 1];
				} else if (args[i].indexOf('DCSext.') == 0) {
					this.DCSext[args[i].substring(7)] = args[i + 1];
				}
			}
		},
		dcsSaveProps: function (args) {
			var key, param;
			if (this.preserve) {
				this.args = [];
				for (var i = 0, al = args.length; i < al; i += 2) {
					param = args[i];
					if (param.indexOf('WT.') == 0) {
						key = param.substring(3);
						this.args.push(param, this.WT[key] || "");
					} else if (param.indexOf('DCS.') == 0) {
						key = param.substring(4);
						this.args.push(param, this.DCS[key] || "");
					} else if (param.indexOf('DCSext.') == 0) {
						key = param.substring(7);
						this.args.push(param, this.DCSext[key] || "");
					}
				}
			}
		},
		dcsRestoreProps: function () {
			if (this.preserve) {
				this.dcsSetProps(this.args);
				this.args = [];
			}
		},
		dcsVar: function () {
			var dCurrent = new Date();
			var self = this;
			var WT = this.WT;
			var DCS = this.DCS;
			WT["tz"] = parseInt(dCurrent.getTimezoneOffset() / 60 * -1) || "0";
			WT["bh"] = dCurrent.getHours() || "0";
			WT["ul"] = _navigator.appName == "Netscape" ? _navigator.language : _navigator.userLanguage;
			if (typeof (screen) == "object") {
				WT["cd"] = _navigator.appName == "Netscape" ? screen.pixelDepth : screen.colorDepth;
				WT["sr"] = screen.width + "x" + screen.height;
			}
			if (typeof (_navigator.javaEnabled()) == "boolean") {
				WT["jo"] = _navigator.javaEnabled() ? "Yes" : "No";
			}
			if (_document.title) {
				if (_window.RegExp) {
					var tire = new RegExp("^" + _location.protocol + "//" + _location.hostname + "\\s-\\s");
					WT["ti"] = _document.title.replace(tire, "");
				} else {
					WT["ti"] = _document.title;
				}
			}
			WT["js"] = "Yes";
			WT["jv"] = (function () {
				var agt = navigator.userAgent.toLowerCase();
				var major = parseInt(navigator.appVersion);
				var mac = (agt.indexOf("mac") != -1);
				var ff = (agt.indexOf("firefox") != -1);
				var ff0 = (agt.indexOf("firefox/0.") != -1);
				var ff10 = (agt.indexOf("firefox/1.0") != -1);
				var ff15 = (agt.indexOf("firefox/1.5") != -1);
				var ff20 = (agt.indexOf("firefox/2.0") != -1);
				var ff3up = (ff && !ff0 && !ff10 & !ff15 & !ff20);
				var nn = (!ff && (agt.indexOf("mozilla") != -1) && (agt.indexOf("compatible") == -1));
				var nn4 = (nn && (major == 4));
				var nn6up = (nn && (major >= 5));
				var ie = ((agt.indexOf("msie") != -1) && (agt.indexOf("opera") == -1));
				var ie4 = (ie && (major == 4) && (agt.indexOf("msie 4") != -1));
				var ie5up = (ie && !ie4);
				var op = (agt.indexOf("opera") != -1);
				var op5 = (agt.indexOf("opera 5") != -1 || agt.indexOf("opera/5") != -1);
				var op6 = (agt.indexOf("opera 6") != -1 || agt.indexOf("opera/6") != -1);
				var op7up = (op && !op5 && !op6);
				var jv = "1.1";
				if (ff3up) {
					jv = "1.8";
				} else if (ff20) {
					jv = "1.7";
				} else if (ff15) {
					jv = "1.6";
				} else if (ff0 || ff10 || nn6up || op7up) {
					jv = "1.5";
				} else if ((mac && ie5up) || op6) {
					jv = "1.4";
				} else if (ie5up || nn4 || op5) {
					jv = "1.3";
				} else if (ie4) {
					jv = "1.2";
				}
				return jv;
			})();
			WT["ct"] = "unknown";
			if (_document.body && _document.body.addBehavior) {
				try {
					_document.body.addBehavior("#default#clientCaps");
					WT["ct"] = _document.body.connectionType || "unknown";
					_document.body.addBehavior("#default#homePage");
					WT["hp"] = _document.body.isHomePage(location.href) ? "1" : "0";
				} catch (e) {
					self.errorlogger(e);
				}
			}
			if (_document.all) {
				WT["bs"] = _document.body ? _document.body.offsetWidth + "x" + _document.body.offsetHeight : "unknown";
			} else {
				WT["bs"] = _window.innerWidth + "x" + _window.innerHeight;
			}
			WT["fv"] = (function () {
				var i, flash;
				if (_window.ActiveXObject) {
					for (i = 15; i > 0; i--) {
						try {
							flash = new ActiveXObject("ShockwaveFlash.ShockwaveFlash." + i);
							return i + ".0";
						} catch (e) {
							self.errorlogger(e)
						}
					}
				} else if (_navigator.plugins && _navigator.plugins.length) {
					for (i = 0; i < _navigator.plugins.length; i++) {
						if (_navigator.plugins[i].name.indexOf('Shockwave Flash') != -1) {
							return _navigator.plugins[i].description.split(" ")[2];
						}
					}
				}
				return "Not enabled";
			})();
			WT["slv"] = (function () {
				var slv = "Not enabled";
				try {
					if (_navigator.userAgent.indexOf('MSIE') != -1) {
						var sli = new ActiveXObject('AgControl.AgControl');
						if (sli) {
							slv = "Unknown";
						}
					} else if (_navigator.plugins["Silverlight Plug-In"]) {
						slv = "Unknown";
					}
				} catch (e) {
					self.errorlogger(e);
				}
				if (slv != "Not enabled") {
					var i, m, M, F;
					if ((typeof (Silverlight) == "object") && (typeof (Silverlight.isInstalled) == "function")) {
						for (i = 9; i > 0; i--) {
							M = i;
							if (Silverlight.isInstalled(M + ".0")) {
								break;
							}
							if (slv == M) {
								break;
							}
						}
						for (m = 9; m >= 0; m--) {
							F = M + "." + m;
							if (Silverlight.isInstalled(F)) {
								slv = F;
								break;
							}
							if (slv == F) {
								break;
							}
						}
					}
				}
				return slv;
			})();
			if (this.i18n) {
				if (typeof (_document.defaultCharset) == "string") {
					WT["le"] = _document.defaultCharset;
				} else if (typeof (_document.characterSet) == "string") {
					WT["le"] = _document.characterSet;
				} else {
					WT["le"] = "unknown";
				}
			}
			WT["tv"] = Webtrends.version;
			WT["sp"] = this.splitvalue;
			WT["dl"] = "0";
			if (Webtrends.qryparams && Webtrends.qryparams.fb_ref) {
				WT["fb_ref"] = Webtrends.qryparams.fb_ref;
			}
			if (Webtrends.qryparams && Webtrends.qryparams.fb_source) {
				WT["fb_source"] = Webtrends.qryparams.fb_source;
			}
			WT["ssl"] = (_location.protocol.indexOf('https:') == 0) ? "1" : "0";
			DCS["dcsdat"] = dCurrent.getTime();
			DCS["dcssip"] = _location.hostname;
			DCS["dcsuri"] = _location.pathname;
			WT["es"] = DCS["dcssip"] + DCS["dcsuri"];
			if (_location.search) {
				DCS["dcsqry"] = _location.search;
			}
			if (DCS["dcsqry"]) {
				var dcsqry = DCS["dcsqry"].toLowerCase();
				var params = this.paidsearchparams.length ? this.paidsearchparams.toLowerCase().split(",") : [];
				for (var i = 0; i < params.length; i++) {
					if (dcsqry.indexOf(params[i] + "=") != -1) {
						WT["srch"] = "1";
						break;
					}
				}
			}
			if ((_document.referrer != "") && (_document.referrer != "-")) {
				if (!(_navigator.appName == "Microsoft Internet Explorer" && parseInt(_navigator.appVersion) < 4)) {
					DCS["dcsref"] = _document.referrer;
				}
			}
			if (this.disablecookie) {
				DCS["dcscfg"] = "1";
			}
		},
		dcsEscape: function (S, REL) {
			if (REL != "") {
				if (S === null || S === undefined) {
					return "";
				}
				S = S.toString();
				for (var R in REL) {
					if (REL[R] instanceof RegExp) {
						S = S.replace(REL[R], R);
					}
				}
				return S;
			} else {
				return escape(S);
			}
		},
		dcsA: function (N, V) {
			if (this.i18n && (this.exre != "") && !this.exre.test(N)) {
				if (N == "dcsqry") {
					var newV = "";
					var params = V.substring(1).split("&");
					for (var i = 0; i < params.length; i++) {
						var pair = params[i];
						var pos = pair.indexOf("=");
						if (pos != -1) {
							var key = pair.substring(0, pos);
							var val = pair.substring(pos + 1);
							if (i != 0) {
								newV += "&";
							}
							newV += key + "=" + Webtrends.dcsEncode(val);
						}
					}
					V = V.substring(0, 1) + newV;
				} else {
					V = Webtrends.dcsEncode(V);
				}
			}
			return "&" + N + "=" + this.dcsEscape(V, this.re);
		},
		dcsCreateImage: function (dcsSrc, o) {
			if (_document.images) {
				var img = new Image();
				this.images.push(img);
				if (arguments.length === 2 && o && Webtrends.isFn(o['callback'])) {
					var hasFinished = false;
					var callback = o['callback'];
					var o_out = o;
					var dcs = this;
					img.onload = function () {
						if (!hasFinished) {
							hasFinished = true;
							callback(dcs, o_out);
							return true;
						}
					};
					_window.setTimeout(function () {
						if (!hasFinished) {
							hasFinished = true;
							callback(dcs, o_out);
							return true;
						}
					}, Webtrends.dcsdelay);
				}
				img.src = dcsSrc;
			}
		},
		dcsMeta: function () {
			var elems;
			if (_document.documentElement) {
				elems = _document.getElementsByTagName("meta");
			} else if (_document.all) {
				elems = _document.all.tags("meta");
			}
			if (typeof (elems) != "undefined") {
				var length = elems.length;
				for (var i = 0; i < length; i++) {
					var name = elems.item(i).name;
					var content = elems.item(i).content;
					var equiv = elems.item(i).httpEquiv;
					if (name.length > 0) {
						name = name.toLowerCase();
						if (name.toUpperCase().indexOf("WT.") == 0) {
							this.WT[name.substring(3)] = content;
						} else if (name.toUpperCase().indexOf("DCSEXT.") == 0) {
							this.DCSext[name.substring(7)] = content;
						} else if (name.toUpperCase().indexOf("DCS.") == 0) {
							this.DCS[name.substring(4)] = content;
						} else if (this.metanames && this.metanames.indexOf(name) != -1) {
							this.DCSext["meta_" + name] = content;
						}
					}
				}
			}
		},
		dcsTag: function (o) {
			if (_document.cookie.indexOf("WTLOPTOUT=") != -1) {
				return;
			}
			var WT = this.WT;
			var DCS = this.DCS;
			var DCSext = this.DCSext;
			var i18n = this['i18n'];
			var P = "http" + (_location.protocol.indexOf('https:') == 0 ? 's' : '') + "://" + this['domain'] + (this['dcsid'] == "" ? '' : '/' + this['dcsid']) + "/dcs.gif?";
			if (i18n) {
				WT["dep"] = "";
			}
			for (var N in DCS) {
				if (DCS[N] != "" && DCS[N] != undefined && (typeof DCS[N] != "function")) {
					P += this.dcsA(N, DCS[N]);
				}
			}
			for (N in WT) {
				if (WT[N] != "" && WT[N] != undefined && (typeof WT[N] != "function")) {
					P += this.dcsA("WT." + N, WT[N]);
				}
			}
			for (N in DCSext) {
				if (DCSext[N] != "" && DCSext[N] != undefined && (typeof DCSext[N] != "function")) {
					if (i18n) {
						WT["dep"] = (WT["dep"].length == 0) ? N : (WT["dep"] + ";" + N);
					}
					P += this.dcsA(N, DCSext[N]);
				}
			}
			if (i18n && (WT["dep"].length > 0)) {
				P += this.dcsA("WT.dep", WT["dep"]);
			}
			if (P.length > 2048 && _navigator.userAgent.indexOf('MSIE') >= 0) {
				P = P.substring(0, 2040) + "&WT.tu=1";
			}
			this.dcsCreateImage(P, o);
			this.WT["ad"] = "";
		},
		pageAnalyze: function () {
			this.dcsVar();
			this.dcsMeta();
			if (this.adclickparam && this.adclickparam.length > 0) this.dcsAdSearch();
			//var e=(navigator.appVersion.indexOf("MSIE")!=-1)?"click":"mousedown";
			this.pageAnalyzehasRun = true;
		},
		getTime: function () {
			return (new Date()).getTime();
		},
		dumpCounter: 0,
		//Trick Google's closure compiler to not compile out the spinLock function call.  aka we now have a side effect.
		spinLock: function (delay) {
			var s = this.getTime();
			while (this.getTime() - s < delay) {
				this.dumpCounter++;
			}
		},
		dcsCollect: function () {
			return this.track.apply(this, arguments);
		},
		enQueue: function (action, o) {
			if (!action) action = 'collect';
			this.queue.push({
				'action': action,
				'message': o
			});
		},
		doAction: function (cmd) {
			if (!this.enabled)
				return;
			var action = 'action_'+cmd['action'];
			var o = cmd['message'];
			// make sure we have run pageAnalysis
			if (!this.pageAnalyzehasRun)
				this.pageAnalyze();

			// if o has an event, lets crawl up the DOM to find the handler, assume A (TODO add support for other tags...)
			if (o["event"] && !o["element"])
				o["element"] = Webtrends.elemOfEvent(o["event"], "A");
			/* Filters are a function you attach to a multiTrack object
			 * that return true if you want to "filter out" this mulitrack
			 * call.  Used mostly with selectors, for example to filter
			 * out clicks to onsite links.   */
			if(Webtrends.isFn(o['filter']) && o['filter'](this, o))
				return;
			//merge o.args(KVP object) into o.argsa(array pairs)
			if (o["args"]) {
				o["argsa"] = o["argsa"] || [];
				for (var key in o["args"]) {
					o["argsa"].push(key, o["args"][key]);
				}
			}
			// look for new data-wtmt suppliments
			if (o["element"] && o["element"].getAttribute && o['element'].getAttribute("data-wtmt")) {
				o["argsa"] = o["argsa"].concat(o['element'].getAttribute("data-wtmt").split(","));
			}

			// make sure you run transforms BEFORE the save,setprops
			_fireEvent('transform.' + cmd['action'], this, o);
			_fireEvent('transform.all', this, o);
			if (o['transform'] && Webtrends.isFn(o['transform'])) {
				o['transform'](this, o);
			}

			this.dcsFPC();
			//If action = collect or multitrack it calls the functions below
			//  but this allows for other action types to be added on the fly.
			if (Webtrends.isFn(this[action])) this[action](o);
			_fireEvent("finish." + cmd['action'], this, o);
			_fireEvent("finish.all", this, o);
			if (o['finish'] && Webtrends.isFn(o['finish'])) {
				o['finish'](this, o);
			}
		},
		/* ***************************************************************
		 * The following is the multitrack(action) which is called
		 * by doAction() if the cmd.action element == "multitrack"
		 ******************************************************************/
		action_multitrack: function (o) {
			var useMtrackArgs = (o && o['argsa'] && o['argsa'].length % 2 == 0);
			//this.dcsCleanUp();
			if (useMtrackArgs) {
				this.dcsSaveProps(o['argsa']);
				this.dcsSetProps(o['argsa']);
			}
			this.DCS['dcsdat'] = this.getTime();
			this.dcsTag(o);
			if (useMtrackArgs) this.dcsRestoreProps();
		},
		/* ***************************************************************
		 * The following is the collect(action) which is called
		 * by doAction() if the cmd.action element == "collect"
		 ******************************************************************/
		action_collect: function (o) {
			var useMtrackArgs = (o && o['argsa'] && o['argsa'].length % 2 == 0);
			if (useMtrackArgs) {
				this.dcsSetProps(o['argsa']);
			}
			this.dcsTag(o);
		},
		/**
		 * Methods for debugging
		 */
		dcsDebugData: function (imgIdx) {
			if (arguments.length === 0 && this.images && this.images.length > 0) {
				imgIdx = this.images.length - 1;
			}
			if (imgIdx < 0 || imgIdx === undefined) return "No requests";
			var i = this.images[imgIdx].src;
			var q = i.indexOf("?");
			var r = i.substring(0, q).split("/");
			var m = "<h3>url info</h3><b>Protocol</b>: <code>" + r[0] + "<br></code>";
			m += "<b>Domain:</b> <code>" + r[2] + "<br></code>";
			m += "<b>Path:</b> <code>/" + r[3] + "/" + r[4] + "</code>";
			m += "<h3>dcs image Params:</h3><code>" + i.substring(q + 1).replace(/\&/g, "<br>") + "</code>";
			m += "<br><h3>Cookies</h3><br><code>" + document.cookie.replace(/\;/g, "<br>") + "</code><br>";
			m += "<b>Image Count: </b><code>" + imgIdx + 1 + "<br></code>";
			if (this.errors.length > 0) {
				m += "<br><b>Errors: </b><br>";
				extendArray(this.errors).forEach(function (error) {
					if (error.stack) m += "<pre>" + error.stack + "</pre><br>";
					else m += "<pre>" + error + "</pre><br>";
				});
			}
			return m;
		},
		dcsDebug: function (o) {
			var rs = false;
			if (o && o.returnAsString) {
				rs = true
			}
			var t = this;
			var m = t.dcsDebugData();
			if (rs) return m;
			else {
				if (t.w && !t.w.closed) {
					t.w.close();
				}
				t.w = window.open("", "dcsDebug", "width=500,height=650,scrollbars=yes,resizable=yes");
				t.w.document.write(m);
				t.w.focus();
			}
		},
		/*
		 * The following section are a collection of functions used for event tracking.
		 */
		/*
		 * Takes a click event object and extracts the URI info if it has it.
		 */
		getURIArrFromEvent: function (e) {
			var res = {};
			res.dcssip = e.hostname ? (e.hostname.split(":")[0]) : "";
			res.dcsuri = e.pathname ? ((e.pathname.indexOf("/") != 0) ? "/" + e.pathname : e.pathname) : "/";
			res.dcsqry = e.search ? e.search.substring(e.search.indexOf("?") + 1, e.search.length) : "";
			res.dcsref = _window.location;
			return res;
		},
		/*
		 *   Used to determine if a given hostname is onsite or not.
		 *   host : a sting with a host name.
		 *   onsiteDoms : either an array of onsite domain names OR a regular expression which will match an onsite domain.
		 *   returns: True if the given host is onsite, false if it isn't.
		 */
		dcsIsOnsite: function (host, onsiteDoms) {
			if (host.length > 0) {
				host = host.toLowerCase();
				if (host == window.location.hostname.toLowerCase()) {
					return true;
				}
				if (Webtrends.isFn(onsiteDoms.test)) {
					return onsiteDoms.test(host);
				} else if (onsiteDoms.length > 0) {
					var len = onsiteDoms.length;
					for (var i = 0; i < len; i++) {
						if (host == onsiteDoms[i]) {
							return true;
						}
					}
				}
			}
			return false;
		},
		/*
		 * Used to determine if a given URI ends with a filetype from the list of types.
		 */
		dcsTypeMatch: function (pth, types) {
			var type = pth.toLowerCase().substring(pth.lastIndexOf(".") + 1, pth.length);
			var tlen = types.length;
			for (var i = 0; i < tlen; i++) {
				if (type == types[i]) {
					return true;
				}
			}
			return false;
		},
		dcsNavigation: function (evt, navTags) {
			var id = "";
			var cname = "";
			var elen = navTags.length;
			var i, e, elem;
			for (i = 0; i < elen; i++) {
				elem = navTags[i];
				if (elem.length) {
					e = Webtrends.elemOfEvent(evt, elem);
					id = (e.getAttribute && e.getAttribute("id")) ? e.getAttribute("id") : "";
					cname = e.className || "";
					if (id.length || cname.length) {
						break;
					}
				}
			}
			return id.length ? id : cname;
		},
		getTTL: function(ev, el , alt){
			var text = _document.all ? el.innerText : el.text;
			var img = Webtrends.elemOfEvent(ev, "IMG");
			var ttl;
			if(img && img.alt) {
				ttl = img.alt;
			} else if(text) {
				ttl = text;
			} else if(el.innerHTML) {
				ttl = el.innerHTML;
			}
			return (ttl)?ttl:alt;
		},
		_autoEvtSetup: function(o){
			if(!this.preserve){
				this.preserve = true;
				this._overridePreserve = true;
				this.dcsSaveProps(o['argsa']);
				this.dcsSetProps(o['argsa']);
			}
		},
		_autoEvtCleanup: function(o){
			if(this._overridePreserve){
				var dcs = this;
				o['finish']=function(){
					dcs.dcsRestoreProps();
					dcs.preserve = false;
				};
				this._overridePreserve=false;
			}
		},
		_isRightClick: function(evt){
	        var rightclick = false;
	        if (!evt)
	        	var evt = window.event;
	        if (evt.which)
	        	rightclick = (evt.which == 3);
	        else if (evt.button)
	        	rightclick = (evt.button == 2);
	        return rightclick;
		},
		/*
		 * This method tags all links on the page, but only sends a hit if the link is targeting
		 * an offsite link.  As defined by the onsitedoms configuration parameter. Which
		 * can be either a comma separated list or a regular expression.
		 */
		addOffsiteTracking: function () {
			//Use the CSS not selector to
			this.addSelector('a', {
				filter: function (dcsObject, o) {
					var e = o['element'] || {};
					var evt = o['event'] || {};
					if(e.hostname && !dcsObject.dcsIsOnsite(e.hostname, dcsObject._onsitedoms) &&
					    !dcsObject._isRightClick(evt)
					)
						return false;
					else
						return true;
				},
				transform: function (dcsObject, o) {
					var e = o['event'] || {};
					var el = o['element'] || {};
					dcsObject._autoEvtSetup(o);
					var res = dcsObject.getURIArrFromEvent(el);
					o['argsa'].push(
						"DCS.dcssip", res.dcssip,
						"DCS.dcsuri", res.dcsuri,
						"DCS.dcsqry", res.dcsqry,
						"DCS.dcsref", res.dcsref,
						"WT.ti", "Offsite:" + res.dcssip + res.dcsuri + (res.dcsqry.length ? ("?" + res.dcsqry) : ""),
						"WT.dl", "24");
					dcsObject._autoEvtCleanup(o);
				}
			});
		},
		// Code section for Track clicks to links that contain anchors.
		addAnchorTracking: function (evt) {
			this.addSelector('a', {
				filter: function (dcsObject, o) {
					var e = o['element'] || {};
					var evt = o['event'] || {};
					if (dcsObject.dcsIsOnsite(e.hostname, dcsObject._onsitedoms) &&
					    e.hash && (e.hash != "") && (e.hash != "#") && !dcsObject._isRightClick(evt))
						return false;
					else
						return true;
				},
				transform: function (dcsObject, o) {
					var e = o['event'] || {};
					var el = o['element'] || {};
					dcsObject._autoEvtSetup(o);
					var res = dcsObject.getURIArrFromEvent(el);
					o['argsa'].push(
						"DCS.dcssip", res.dcssip,
						"DCS.dcsuri", escape(res.dcsuri + o['element'].hash),
						"DCS.dcsqry", res.dcsqry,
						"DCS.dcsref", res.dcsref,
						"WT.ti", escape("Anchor:" +o['element'].hash),
						"WT.nv", dcsObject.dcsNavigation(e, dcsObject.navigationtag),
						"WT.dl", "21");
					dcsObject._autoEvtCleanup(o);
				}
			});
		},
		addDownloadTracking: function () {
			this.addSelector('a', {
				filter: function (dcsObject, o) {
					var e = o['element'] || {};
					var evt = o['event'] || {};
					if (dcsObject.dcsTypeMatch(e.pathname, dcsObject._downloadtypes)&&
					    !dcsObject._isRightClick(evt)
					)
						return false;
					else
						return true;
				},
				transform: function (dcsObject, o) {
					var e = o['event'] || {};
					var el = o['element'] || {};
					dcsObject._autoEvtSetup(o);
					var res = dcsObject.getURIArrFromEvent(el);
					var ttl = dcsObject.getTTL(e,el,res.dcsuri);
					o['argsa'].push(
						"DCS.dcssip", res.dcssip,
						"DCS.dcsuri", res.dcsuri,
						"DCS.dcsqry", res.dcsqry,
						"DCS.dcsref", res.dcsref,
						"WT.ti", "Download:" + ttl,
						"WT.nv", dcsObject.dcsNavigation(e,dcsObject.navigationtag),
						"WT.dl", "20");
					dcsObject._autoEvtCleanup(o);
				}
			});
		},
		addRightClickTracking: function () {
			this.addSelector('a', {
				filter: function (dcsObject, o) {
					var e = o['element'] || {};
					var evt = o['event'] || {};
					if (dcsObject.dcsTypeMatch(e.pathname, dcsObject._downloadtypes)&&
					    dcsObject._isRightClick(evt)
					)
						return false;
					else
						return true;
				},
				transform: function (dcsObject, o) {
					var e = o['event'] || {};
					var el = o['element'] || {};
					dcsObject._autoEvtSetup(o);
					var res = dcsObject.getURIArrFromEvent(el);
					var ttl = dcsObject.getTTL(e,el,res.dcsuri);
					o['argsa'].push(
						"DCS.dcssip", res.dcssip,
						"DCS.dcsuri", res.dcsuri,
						"DCS.dcsqry", res.dcsqry,
						"DCS.dcsref", res.dcsref,
						"WT.ti", "RightClick:" + ttl,
						"WT.nv", dcsObject.dcsNavigation(e,dcsObject.navigationtag),
						"WT.dl", "25");
					dcsObject._autoEvtCleanup(o);
				}
			});
		},
		addJavaScriptTracking: function () {
			this.addSelector('a', {
				filter: function (dcsObject, o) {
					var e = o['element'] || {};
					var evt = o['event'] || {};
					if (e.href && e.protocol && e.protocol.toLowerCase() == "javascript:")
						return false;
					else
						return true;
				},
				transform: function (dcsObject, o) {
					var e = o['event'] || {};
					var el = o['element'] || {};
					dcsObject._autoEvtSetup(o);
					var res = dcsObject.getURIArrFromEvent(el);
					o['argsa'].push(
						"DCS.dcssip", _window.location.hostname,
						"DCS.dcsuri", el.href,
						"DCS.dcsqry", res.dcsqry,
						"DCS.dcsref", res.dcsref,
						"WT.ti", "JavaScript:" + ((el.innerHTML) ? el.innerHTML : ""),
						"WT.dl", "22",
						"WT.nv", dcsObject.dcsNavigation(e,dcsObject.navigationtag));
					dcsObject._autoEvtCleanup(o);
				}
			});
		},
		// Code section for Generate an Ad View query parameter for every Ad Click link.
		dcsAdSearch: function () {
			if (_document.links) {
				var param = this.adclickparam + "=";
				var paramlen = param.length;
				var paramre = new RegExp(param, "i");
				var len = _document.links.length;
				var pos = end = -1;
				var anch = urlp = value = "";
				var urlpre;
				var url = _document.URL + "";
				var start = url.search(paramre);
				if (start != -1) {
					end = url.indexOf("&", start);
					urlp = url.substring(start, (end != -1) ? end : url.length);
					urlpre = new RegExp(urlp + "(&|#)", "i");
				}
				for (var i = 0; i < len; i++) {
					if (_document.links[i].href) {
						anch = _document.links[i].href + "";
						if (urlp.length > 0) {
							anch = anch.replace(urlpre, "$1");
						}
						pos = anch.search(paramre);
						if (pos != -1) {
							start = pos + paramlen;
							end = anch.indexOf("&", start);
							value = anch.substring(start, (end != -1) ? end : anch.length);
							this.WT['ad'] = this.WT['ad'] ? (this.WT['ad'] + ";" + value) : value;
						}
					}
				}
			}
		}
	};
	// legacy dcsMultiTrack support
	function dcsMultiTrack() {
		var args_in = [];
		for(var i=0; i<arguments.length; i++)
			args_in[i] = arguments[i];
		var o = {
			argsa: args_in
		};
		Webtrends.multiTrack(o);
	}
	//These are private but still need to be exported.
	Webtrends.dcs.prototype['action_multitrack'] = Webtrends.dcs.prototype.action_multitrack;
	Webtrends.dcs.prototype['action_collect'] = Webtrends.dcs.prototype.action_collect;
	// exports for google closure compiler
	_window['dcsMultiTrack'] = dcsMultiTrack;
	_window['Webtrends'] = Webtrends;
	_window['WebTrends'] = Webtrends; //legacy support
	_window['WT'] = _window['Webtrends'];
	_window['dcsDebug'] = Webtrends.dcsDebug;
	Webtrends['multiTrack'] = Webtrends.multiTrack;
	Webtrends['dcs'] = Webtrends.dcs;
	Webtrends['dcss'] = Webtrends.dcss;
	Webtrends['addTransform'] = Webtrends.addTransform;
	Webtrends['bindEvent'] = Webtrends.bindEvent;
	Webtrends['getQryParams'] = Webtrends.getQryParams;
	Webtrends['dcsdelay'] = Webtrends.dcsdelay;
	Webtrends['find'] = Webtrends.find;
	Webtrends['registerPlugin'] = Webtrends.registerPlugin;
	Webtrends['dcsDebug'] = Webtrends.dcsDebug;
	Webtrends.dcs.prototype['init'] = Webtrends.dcs.prototype.init;
	Webtrends.dcs.prototype['dcsMultiTrack'] = Webtrends.dcs.prototype.dcsMultiTrack;
	Webtrends.dcs.prototype['track'] = Webtrends.dcs.prototype.track;
	Webtrends.dcs.prototype['addSelector'] = Webtrends.dcs.prototype.addSelector;
	Webtrends.dcs.prototype['dcsGetIdCallback'] = Webtrends.dcs.prototype.dcsGetIdCallback;
	Webtrends.dcs.prototype['dcsDebug'] = Webtrends.dcs.prototype.dcsDebug;
	Webtrends.dcs.prototype['dcsCleanUp'] = Webtrends.dcs.prototype.dcsCleanUp;
	Webtrends.dcs.prototype['dcsGetFPC'] = Webtrends.dcs.prototype.dcsGetFPC;
	Webtrends.dcs.prototype['addTransform'] = Webtrends.dcs.prototype.addTransform;
	Webtrends.init();
})(window, window.document, window.navigator, window.location);
