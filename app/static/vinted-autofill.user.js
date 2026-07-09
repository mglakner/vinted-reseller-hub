// ==UserScript==
// @name         Vinted Hub — auto-fill
// @namespace    vinted-hub
// @version      2.1
// @description  Automatically fills Vinted's new-listing form when the page is opened via "Fill on Vinted" in Vinted Hub. Never publishes by itself.
// @include      /^https:\/\/www\.vinted\.[a-z.]+\/items\/new.*/
// @run-at       document-idle
// @grant        none
// ==/UserScript==

/*
  Installation (once, in the browser you list from):
    1. Install the Tampermonkey extension.
    2. In Chrome: chrome://extensions → enable "Developer mode" (or Tampermonkey →
       Details → "Allow User Scripts"), otherwise userscripts silently don't run.
    3. Open this script from Vinted Hub → Status → "One-click auto-fill", click Install.
  After that, "Fill on Vinted" is one click: the page opens AND fills itself.

  Uses a plain fetch (CORS is allowed on the package route), so no @grant/@connect
  and no permission pop-up. Never publishes — the final click (Upload) is always yours.
*/

(function () {
  "use strict";

  const pkgUrl = new URLSearchParams(location.search).get("vh");
  if (!pkgUrl) return; // manuel oprettelse forstyrres ikke

  // Kør kun én gang pr. sideindlæsning — så hverken SPA-genindsprøjtning
  // eller en dubletinstallation kan uploade fotos to gange.
  if (window.__vintedHubFilled) return;
  window.__vintedHubFilled = true;

  const log = (m) => console.log("[VintedHub]", m);

  function setNativeValue(el, value) {
    const proto = el.tagName === "TEXTAREA"
      ? window.HTMLTextAreaElement.prototype
      : window.HTMLInputElement.prototype;
    Object.getOwnPropertyDescriptor(proto, "value").set.call(el, value);
    el.dispatchEvent(new Event("input", { bubbles: true }));
    el.dispatchEvent(new Event("change", { bubbles: true }));
  }

  function waitFor(selector, timeout = 15000) {
    return new Promise((resolve, reject) => {
      const t0 = Date.now();
      (function tick() {
        const el = document.querySelector(selector);
        if (el) return resolve(el);
        if (Date.now() - t0 > timeout) return reject(new Error("timeout: " + selector));
        setTimeout(tick, 300);
      })();
    });
  }

  function banner(text, color) {
    let b = document.getElementById("vh-banner");
    if (!b) {
      b = document.createElement("div");
      b.id = "vh-banner";
      b.style.cssText =
        "position:fixed;top:0;left:0;right:0;z-index:99999;padding:10px;" +
        "text-align:center;font:600 15px system-ui;color:#fff";
      document.body.appendChild(b);
    }
    b.style.background = color;
    b.textContent = text;
  }

  async function run() {
    banner("Vinted Hub is filling in…", "#3d6de0");
    try {
      const pkg = await (await fetch(pkgUrl)).json();
      log(pkg);

      const title = await waitFor("#title");
      setNativeValue(title, pkg.title);
      const desc = document.querySelector("#description");
      if (desc) setNativeValue(desc, pkg.description);
      const price = document.querySelector("#price");
      if (price && pkg.price) setNativeValue(price, String(pkg.price));

      const input = document.querySelector('input[type="file"][name="photos"]');
      if (input && pkg.photos && pkg.photos.length) {
        const dt = new DataTransfer();
        for (let i = 0; i < pkg.photos.length; i++) {
          const blob = await (await fetch(pkg.photos[i])).blob();
          dt.items.add(new File([blob], `photo_${i + 1}.jpg`, { type: blob.type || "image/jpeg" }));
        }
        input.files = dt.files;
        input.dispatchEvent(new Event("change", { bubbles: true }));
      }

      banner(
        "✔ Filled in. Check the category (" + (pkg.category?.title || "pick it") +
        "), brand (" + (pkg.brand?.title || "pick it") + ")" +
        (pkg.size_hint ? " and size (" + pkg.size_hint + ")" : "") +
        " — then hit Upload.",
        "#1d7a4f"
      );
    } catch (e) {
      banner("Vinted Hub error: " + e.message, "#b3392e");
      log(e);
    }
  }

  run();
})();
