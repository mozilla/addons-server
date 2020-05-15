/* This is an underscore.js template. It's pre-compiled so we don't need to
 * compile it on each page view, and also to avoid using the _.template()
 * helper which needs eval, which we want to prevent using CSP.
 *
 * If you need to change it, change the html/template in the comment below,
 * then copy the full _.template(...) call, and run it. The result will be a
 * function resembling the one below, uncommented, and this is the new
 * pre-compiled template you want to paste below. */

/*
_.template(`
    <div class="syntaxhighlighter">
       <table border="0" cellpadding="0" cellspacing="0">
           <colgroup><col class="highlighter-column-line-numbers"/>
                     <col class="highlighter-column-code"/></colgroup>
           <tbody>
           {% _.each(lines, function(line) { %}
               <tr class="tr-line">
                   <td class="td-line-number">
                       <a href="#{{ line.id }}" id="{{ line.id }}"
                          class="{{ line.class }} original line line-number"
                          data-linenumber="{{ line.number }}"></a>
                   </td>
                   <td class="{{ line.class }} td-line-code alt{{ line.number % 2 + 1}}"><span
                           class="original line line-code"><%=
                       line.code
                   %></span></td>
               </tr>
           {% }) %}
           </tbody>
       </table>
    </div>
`).source;
*/

/* The following is the above commented template, pre-compiled. */
function syntaxhighlighter_template(obj){
var __t,__p='',__j=Array.prototype.join,print=function(){__p+=__j.call(arguments,'');};
with(obj||{}){
__p+='\n    <div class="syntaxhighlighter">\n       <table border="0" cellpadding="0" cellspacing="0">\n           <colgroup><col class="highlighter-column-line-numbers"/>\n                     <col class="highlighter-column-code"/></colgroup>\n           <tbody>\n           ';
 _.each(lines, function(line) {
__p+='\n               <tr class="tr-line">\n                   <td class="td-line-number">\n                       <a href="#'+
((__t=( line.id ))==null?'':_.escape(__t))+
'" id="'+
((__t=( line.id ))==null?'':_.escape(__t))+
'"\n                          class="'+
((__t=( line.class ))==null?'':_.escape(__t))+
' original line line-number"\n                          data-linenumber="'+
((__t=( line.number ))==null?'':_.escape(__t))+
'"></a>\n                   </td>\n                   <td class="'+
((__t=( line.class ))==null?'':_.escape(__t))+
' td-line-code alt'+
((__t=( line.number % 2 + 1))==null?'':_.escape(__t))+
'"><span\n                           class="original line line-code">'+
((__t=(
                       line.code
                   ))==null?'':__t)+
'</span></td>\n               </tr>\n           ';
 })
__p+='\n           </tbody>\n       </table>\n    </div>\n';
}
return __p;
}
