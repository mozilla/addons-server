var links = document.getElementsByTagName('link');
for (var i = 0; i < links.length; i++) {
  if (/\.less($|\?)/.test(links[i].href)) {
    links[i].type = 'text/x-less';
  }
}
