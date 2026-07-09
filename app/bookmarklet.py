"""Bookmarklet that fills Vinted's new-listing form from ?vh=<package-URL>.

Runs on vinted.*/items/new. Fetches the package (CORS allowed), fills
title/description/price and uploads photos. NEVER publishes by itself.

Single quotes only in the JS so it can sit in href="..." unescaped.
"""

_JS = (
    "(function(){"
    "function sv(el,v){var p=el.tagName==='TEXTAREA'?HTMLTextAreaElement.prototype:HTMLInputElement.prototype;"
    "Object.getOwnPropertyDescriptor(p,'value').set.call(el,v);"
    "el.dispatchEvent(new Event('input',{bubbles:true}));el.dispatchEvent(new Event('change',{bubbles:true}));}"
    "function wf(s,ms){ms=ms||12000;return new Promise(function(res,rej){var t0=Date.now();"
    "(function tk(){var e=document.querySelector(s);if(e)return res(e);"
    "if(Date.now()-t0>ms)return rej(new Error('timeout'));setTimeout(tk,300);})();});}"
    "var u=new URLSearchParams(location.search).get('vh');"
    "if(!u){alert('Open an item via the \\u201cFill on Vinted\\u201d button in Vinted Hub first.');return;}"
    "(async function(){try{"
    "var pkg=await (await fetch(u)).json();"
    "var t=await wf('#title');sv(t,pkg.title);"
    "var d=document.querySelector('#description');if(d)sv(d,pkg.description);"
    "var p=document.querySelector('#price');if(p&&pkg.price)sv(p,String(pkg.price));"
    "var inp=document.querySelector('input[type=file][name=photos]');"
    "if(inp&&pkg.photos&&pkg.photos.length){var dt=new DataTransfer();"
    "for(var i=0;i<pkg.photos.length;i++){var b=await (await fetch(pkg.photos[i])).blob();"
    "dt.items.add(new File([b],'photo_'+(i+1)+'.jpg',{type:b.type||'image/jpeg'}));}"
    "inp.files=dt.files;inp.dispatchEvent(new Event('change',{bubbles:true}));}"
    "alert('Vinted Hub: filled in! Check the category, brand and size, then hit Upload.');"
    "}catch(e){alert('Vinted Hub error: '+e);}})();"
    "})();"
)

BOOKMARKLET = "javascript:" + _JS
