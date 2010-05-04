var GSFN;
if(GSFN == undefined) {
  GSFN = {};
}
 
if(!GSFN.initialized) {
  
  GSFN.gId = function(id) {
    return document.getElementById(id);
  };

  GSFN.hasClassName = function(element, className) {
    var elementClassName = element.className;

    return (elementClassName.length > 0 && (elementClassName == className ||
      new RegExp("(^|\\s)" + className + "(\\s|$)").test(elementClassName)));
  };

  GSFN.addClassName = function(element, className) {
    if (!GSFN.hasClassName(element, className))
      element.className += (element.className ? ' ' : '') + className;
    return element;
  };

  GSFN.removeClassName = function(element, className) {
    var newClass = GSFN.strip(element.className.replace(new RegExp("(^|\\s+)" + className + "(\\s+|$)"), ' '));
    element.className = newClass;
    return element;
  };

  GSFN.strip = function(string) {
    return string.replace(/^\s+/, '').replace(/\s+$/, '');
  };
  
  GSFN.add_css = function(css_content) {
    var head = document.getElementsByTagName('head')[0];
    var style = document.createElement('style');
    style.type = 'text/css';
    
    if(style.styleSheet) {
      style.styleSheet.cssText = css_content;
    } else {
      rules = document.createTextNode(css_content);
      style.appendChild(rules);
    }
    head.appendChild(style);
  }

  GSFN.initialized = true;
}

GSFN.feedback_widget = function(options) {
  this.options = options;
  this.is_ssl = ("https:" == document.location.protocol);
  
  if(!this.options.display){ this.options.display = "overlay";}
  
  if(this.is_ssl) {
    this.feedback_base_url = this.local_ssl_base_url;
    this.asset_base_url = this.s3_ssl_base_url;
  } else {
    this.feedback_base_url = this.local_base_url;
    this.asset_base_url = this.s3_base_url;
  }
  
  if(this.options.local_assets == true) {
    this.asset_base_url = this.feedback_base_url;  
  }

  var disable_tagging = this.options.auto_tag == false;

  query_string_obj = [];
  
  if(!disable_tagging){
    if(this.options.product){ 
      query_string_obj.push("product=" + encodeURIComponent(this.options.product));
    }
  
    if(this.options.tag){
      query_string_obj.push("tag=" + encodeURIComponent(this.options.tag));
    }
  
    if(this.options.user_defined_code){ 
      query_string_obj.push("user_defined_code=" + encodeURIComponent(this.options.user_defined_code));
    }
  }
  
  if(this.options.display){ 
    query_string_obj.push("display=" + encodeURIComponent(this.options.display));
  }
  
  if(this.options.style){ 
    query_string_obj.push("style=" + encodeURIComponent(this.options.style));
  }
  
  if(this.options.popular_topics){ 
    query_string_obj.push("popular_topics=" + encodeURIComponent(this.options.popular_topics));
  }

  if(this.options.limit){
    query_string_obj.push("limit=" + encodeURIComponent(this.options.limit));
  }
  
  if(this.options.problem){ 
    query_string_obj.push("problem=" + encodeURIComponent(this.options.problem));
  }
    
  if(this.options.powered_by){ 
    query_string_obj.push("powered_by=" + encodeURIComponent(this.options.powered_by));
  }
  
  if(this.options.custom_css){
    query_string_obj.push("custom_css=" + encodeURIComponent(this.options.custom_css));
  }
  
  if(this.options.auto_tag == false){
    query_string_obj.push("auto_tag=" + encodeURIComponent(this.options.auto_tag));
  }
  
  if(this.options.interstitial) {
    query_string_obj.push("interstitial=" + encodeURIComponent(this.options.interstitial));
  }
  
  if(this.options.community_base_url) {
    query_string_obj.push("community_base_url=" + encodeURIComponent(this.options.community_base_url));
  }
  
  query_string = "?" + query_string_obj.join("&");

  this.feedback_url = this.feedback_base_url + "/" + this.options.company + "/feedback/topics/new" + query_string;
  
  this.options = options ? options : {};
  this.options.placement = this.options.placement ? this.options.placement : 'left';
  this.options.color = this.options.color ? this.options.color : '#222';

  if(this.options.display == 'overlay') {
    this.initial_iframe_url = this.empty_url();
    if(!this.options.width)   { this.options.width = "658px"; }
    if(!this.options.height)  { this.options.height = "100%"; }
  } else {
    this.initial_iframe_url = this.feedback_url;
    if(!this.options.width)   { this.options.width = "100%"; }
    if(!this.options.height)  { this.options.height = "500px"; }
  }
  
  this.iframe_html = '<iframe id="fdbk_iframe" allowTransparency="true" scrolling="no" frameborder="0" class="loading"' +
                      ' src="'    + this.initial_iframe_url + '"' +
                      ' width="'  + this.options.width + '"' +
                      ' height="'  + this.options.height + '"' +
                      ' style="width: '  + this.options.width + '; height: '  + this.options.height + ';"></iframe>';
  
  this.tab_html = '<a href="#" id="fdbk_tab" class="fdbk_tab_'+this.options.placement+'" style="background-color:'+this.options.color+'">FEEDBACK</a>';
  this.overlay_html = '<div id="fdbk_overlay" style="display:none">' +
                        '<div id="fdbk_container">' +
                          '<a href="#" id="fdbk_close"></a>' +
                          this.iframe_html + 
                        '</div>' +
                        '<div id="fdbk_screen"></div>' +
                      '</div>';
  
  if(this.options.display == 'overlay') {
    raw_css = "#fdbk_overlay {\n  width: 100%;\n  height: 100%;\n  top: 0;\n  left: 0;\n  z-index: 1000000;\n  position: absolute; }\n\n#fdbk_screen {\n  top: 0;\n  left: 0;\n  z-index: 1;\n  width: 100%;\n  position: absolute;\n  background-color: #000;\n  opacity: 0.45;\n  -moz-opacity: 0.45;\n  filter: alpha(opacity=45); }\n\n#fdbk_container {\n  width: 680px;\n  height: 640px;\n  margin: 0 auto;\n  z-index: 2;\n  position: relative; }\n  #fdbk_container iframe {\n    width: 658px;\n    height: 100%;\n    margin: 20px;\n    background: transparent; }\n  #fdbk_container iframe.loading {\n    background: transparent url(https:\/\/s3.amazonaws.com\/getsatisfaction.com\/images\/fb_loading.png) no-repeat; }\n\na#fdbk_tab {\n  top: 25%;\n  left: 0;\n  width: 42px;\n  height: 102px;\n  color: #FFF;\n  cursor: pointer;\n  text-indent: -100000px;\n  overflow: hidden;\n  position: fixed;\n  z-index: 100000;\n  margin-left: -7px;\n  background-image: url(https:\/\/s3.amazonaws.com\/getsatisfaction.com\/images\/feedback_trans_tab.png);\n  _position: absolute;\n  _background-image: url(https:\/\/s3.amazonaws.com\/getsatisfaction.com\/images\/feedback_tab_ie6.png); }\n  a#fdbk_tab:hover {\n    margin-left: -4px; }\n\na.fdbk_tab_right {\n  right: 0 !important;\n  left: auto !important;\n  margin-right: 0 !important;\n  margin-left: auto !important;\n  width: 35px !important; }\n  a.fdbk_tab_right:hover {\n    width: 38px !important;\n    margin-right: 0 !important;\n    margin-left: auto !important; }\n\na.fdbk_tab_bottom {\n  top: auto!important;\n  bottom: 0 !important;\n  left: 20% !important;\n  height: 38px !important;\n  width: 102px !important;\n  background-position: 0 -102px !important;\n  margin-bottom: -7px !important;\n  margin-left: auto !important; }\n  a.fdbk_tab_bottom:hover {\n    margin-bottom: -4px !important;\n    margin-left: auto !important; }\n\na.fdbk_tab_hidden {\n  display: none !important; }\n\na#fdbk_close {\n  position: absolute;\n  cursor: pointer;\n  outline: none;\n  top: 0;\n  left: 0;\n  z-index: 4;\n  width: 42px;\n  height: 42px;\n  overflow: hidden;\n  background-image: url(https:\/\/s3.amazonaws.com\/getsatisfaction.com\/images\/feedback-close.png);\n  _background: none;\n  _filter: progid:DXImageTransform.Microsoft.AlphaImageLoader(src='https:\/\/s3.amazonaws.com\/getsatisfaction.com\/images\/feedback-close.png', sizingMethod='crop'); }\n  a#fdbk_close:hover {\n    background-position: -42px 0; }\n\n.feedback_tab_on embed, .feedback_tab_on select, .feedback_tab_on object {\n  visibility: hidden; }\n";
	  replacer_regex = new RegExp(this.s3_ssl_base_url, "g");
    translated_css = raw_css.replace(replacer_regex, this.asset_base_url);
    GSFN.add_css(translated_css);
    
    if(this.options.container) {
      var container_el = GSFN.gId(this.options.container); 
      container_el.innerHTML = this.tab_html + this.overlay_html;
    } else {
      document.write(this.tab_html);
      document.write(this.overlay_html);     
    }
    
    var feedback_obj = this;
    GSFN.gId('fdbk_tab').onclick = function() { feedback_obj.show(); return false; }
    GSFN.gId('fdbk_close').onclick = function() { feedback_obj.hide(); return false; }
    GSFN.gId('fdbk_iframe').setAttribute("src", this.empty_url());

  } else {
    if(this.options.container) {
      var container_el = GSFN.gId(this.options.container);
      container_el.innerHTML = this.iframe_html; 
    } else {
      document.write(this.iframe_html);
    }
  }

};

GSFN.feedback_widget.prototype = {
  local_base_url: "http:\/\/getsatisfaction.com",
  local_ssl_base_url: "https:\/\/getsatisfaction.com",
  s3_base_url: "http://s3.amazonaws.com/getsatisfaction.com",
  s3_ssl_base_url: "https://s3.amazonaws.com/getsatisfaction.com",
  
  asset_url: function(asset) {
    return this.asset_base_url + asset;
  },
  
  empty_url : function() {
    return this.asset_url("/images/transparent.gif");
  },
  
  set_position : function() {
    this.scroll_top = document.documentElement.scrollTop || document.body.scrollTop;
    this.scroll_height = document.documentElement.scrollHeight;
    this.client_height = window.innerHeight || document.documentElement.clientHeight;
    
    GSFN.gId('fdbk_screen').style.height = this.scroll_height+"px";
    GSFN.gId('fdbk_container').style.top = this.scroll_top+(this.client_height*0.1)+"px";
  },
  
  show : function() {
    GSFN.gId('fdbk_iframe').setAttribute("src", this.feedback_url);
    if (GSFN.gId('fdbk_iframe').addEventListener) {
      GSFN.gId('fdbk_iframe').addEventListener("load", this.loaded, false);
    } else if (GSFN.gId('fdbk_iframe').attachEvent) {
      GSFN.gId('fdbk_iframe').attachEvent("onload", this.loaded);
    }
    this.set_position();

    GSFN.addClassName(document.getElementsByTagName('html')[0], 'feedback_tab_on');
    GSFN.gId('fdbk_overlay').style.display = "block";
  },
  
  hide : function() {
    if (GSFN.gId('fdbk_iframe').addEventListener) {
      GSFN.gId('fdbk_iframe').removeEventListener("load", this.loaded, false);
    } else if (GSFN.gId('fdbk_iframe').attachEvent) {
      GSFN.gId('fdbk_iframe').detachEvent("onload", this.loaded);
    }
    
    GSFN.gId('fdbk_overlay').style.display = "none";
    GSFN.gId('fdbk_iframe').setAttribute("src", this.empty_url());
    GSFN.gId('fdbk_iframe').className = "loading";

    GSFN.removeClassName(document.getElementsByTagName('html')[0], 'feedback_tab_on');
  },
  
  loaded : function() {
    GSFN.gId('fdbk_iframe').className = "loaded";
  }
}
