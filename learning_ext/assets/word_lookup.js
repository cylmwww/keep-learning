(function () {
  function installWordLookup() {
    if (window.__leWordLookupInstalled) return;
    window.__leWordLookupInstalled = true;

    var popupId = "le-lookup-popup";
    var popupBodyId = "le-lookup-popup-body";
    var courseSelector = "#le-guide-md, #le-center-content, .le-lookup-zone";
    var activeTerm = "";
    var readyMarker = document.getElementById("le-word-lookup-ready");
    if (!readyMarker) {
      readyMarker = document.createElement("div");
      readyMarker.id = "le-word-lookup-ready";
      readyMarker.style.display = "none";
      document.documentElement.appendChild(readyMarker);
    }

    function nodeElement(node) {
      if (!node) return null;
      return node.nodeType === 1 ? node : node.parentElement;
    }

    function normalizeSelection() {
      var selection = window.getSelection ? window.getSelection() : null;
      var text = selection ? selection.toString().trim().replace(/\s+/g, " ") : "";
      return { selection: selection, text: text };
    }

    function selectionIsInCourse(selection, eventTarget) {
      var target = eventTarget && eventTarget.closest ? eventTarget : nodeElement(eventTarget);
      var anchor = nodeElement(selection && selection.anchorNode);
      var focus = nodeElement(selection && selection.focusNode);
      return Boolean(
        (target && target.closest && target.closest(courseSelector)) ||
        (anchor && anchor.closest && anchor.closest(courseSelector)) ||
        (focus && focus.closest && focus.closest(courseSelector))
      );
    }

    function escapeHtml(value) {
      return String(value).replace(/[&<>"']/g, function (ch) {
        return {
          "&": "&amp;",
          "<": "&lt;",
          ">": "&gt;",
          '"': "&quot;",
          "'": "&#39;",
        }[ch];
      });
    }

    function ensurePopup() {
      var popup = document.getElementById(popupId);
      if (popup) return popup;
      popup = document.createElement("div");
      popup.id = popupId;
      popup.style.cssText = [
        "position:fixed",
        "z-index:99999",
        "display:none",
        "width:min(440px,calc(100vw - 24px))",
        "max-height:60vh",
        "overflow:auto",
        "padding:14px",
        "border:1px solid #E5E7EB",
        "border-radius:10px",
        "background:#FFFFFF",
        "color:#111827",
        "box-shadow:0 12px 28px rgba(0,0,0,0.18)",
        "font:14px/1.55 -apple-system,BlinkMacSystemFont,\"Microsoft YaHei\",sans-serif",
      ].join(";");
      document.body.appendChild(popup);
      return popup;
    }

    function positionPopup(popup, x, y) {
      var margin = 12;
      var width = Math.min(440, window.innerWidth - margin * 2);
      var left = Math.min(x + 12, window.innerWidth - width - margin);
      var top = Math.min(y + 12, window.innerHeight - 220);
      popup.style.left = Math.max(margin, left) + "px";
      popup.style.top = Math.max(margin, top) + "px";
    }

    function renderPopupFrame(title, bodyHtml, actionsHtml) {
      var popup = ensurePopup();
      popup.innerHTML = ""
        + '<div style="display:flex;align-items:flex-start;justify-content:space-between;gap:12px;margin-bottom:8px;">'
        + '<div style="font-weight:800;font-size:15px;">' + title + "</div>"
        + '<button type="button" data-le-lookup-close="1" aria-label="关闭" style="border:0;background:transparent;color:#6B7280;font-size:18px;line-height:1;cursor:pointer;padding:0 2px;">×</button>'
        + "</div>"
        + '<div id="' + popupBodyId + '">' + bodyHtml + "</div>"
        + (actionsHtml || "");
      popup.querySelector("[data-le-lookup-close]").onclick = hidePopup;
      return popup;
    }

    function renderActionPopup(term) {
      var safeText = term.length > 40 ? term.slice(0, 40) + "..." : term;
      var popup = renderPopupFrame(
        "是否需要名词解释？",
        '<div style="color:#4B5563;margin-bottom:12px;">' + escapeHtml(safeText) + "</div>",
        '<div style="display:flex;gap:8px;align-items:center;">'
          + '<button type="button" data-le-lookup-confirm="1" style="border:0;border-radius:7px;background:#4F46E5;color:white;padding:7px 12px;font-weight:700;cursor:pointer;">解释这个名词</button>'
          + '<button type="button" data-le-lookup-cancel="1" style="border:1px solid #E5E7EB;border-radius:7px;background:white;color:#374151;padding:7px 12px;cursor:pointer;">取消</button>'
          + "</div>"
      );
      popup.querySelector("[data-le-lookup-confirm]").onclick = function () {
        activeTerm = term;
        renderLoadingPopup(term);
        triggerExplain(term);
      };
      popup.querySelector("[data-le-lookup-cancel]").onclick = hidePopup;
      return popup;
    }

    function renderLoadingPopup(term) {
      var safeText = term.length > 40 ? term.slice(0, 40) + "..." : term;
      var popup = renderPopupFrame(
        "AI 正在解释",
        '<div style="font-weight:700;margin-bottom:8px;">' + escapeHtml(safeText) + "</div>"
          + '<div style="color:#6B7280;">正在结合当前知识点生成解释...</div>',
        ""
      );
      popup.style.display = "block";
      return popup;
    }

    function renderResultPopup(html) {
      var popup = ensurePopup();
      var body = document.getElementById(popupBodyId);
      if (!body || popup.style.display === "none") {
        popup = renderPopupFrame("AI 解释", "", "");
        body = document.getElementById(popupBodyId);
      }
      if (body) {
        body.innerHTML = '<div class="le-lookup-result" style="font-size:14px;">' + html + "</div>";
      }
      popup.style.display = "block";
    }

    function setNativeValue(input, value) {
      var proto = input instanceof HTMLTextAreaElement
        ? window.HTMLTextAreaElement.prototype
        : window.HTMLInputElement.prototype;
      var descriptor = Object.getOwnPropertyDescriptor(proto, "value");
      if (descriptor && descriptor.set) descriptor.set.call(input, value);
      else input.value = value;
      input.dispatchEvent(new Event("input", { bubbles: true }));
      input.dispatchEvent(new Event("change", { bubbles: true }));
    }

    function triggerExplain(term) {
      var input = document.querySelector("#le-selected-term textarea, #le-selected-term input");
      if (!input) return;
      setNativeValue(input, "");
      window.setTimeout(function () {
        setNativeValue(input, term);
      }, 30);
    }

    function hidePopup() {
      var popup = document.getElementById(popupId);
      if (popup) popup.style.display = "none";
    }

    function observeExplainOutput() {
      var output = document.getElementById("le-term-output");
      if (!output || output.__leLookupObserved) return;
      output.__leLookupObserved = true;
      var lastHtml = "";
      var observer = new MutationObserver(function () {
        var html = output.innerHTML.trim();
        var text = output.textContent.trim();
        if (!html || !text || html === lastHtml) return;
        lastHtml = html;
        var popup = document.getElementById(popupId);
        if (activeTerm || (popup && popup.style.display !== "none")) {
          renderResultPopup(html);
        }
      });
      observer.observe(output, { childList: true, subtree: true, characterData: true });
    }

    observeExplainOutput();
    window.setInterval(observeExplainOutput, 1200);

    document.addEventListener("mousedown", function (event) {
      var popup = document.getElementById(popupId);
      if (popup && !popup.contains(event.target)) hidePopup();
    });

    document.addEventListener("mouseup", function (event) {
      window.setTimeout(function () {
        var current = normalizeSelection();
        if (
          !current.text ||
          current.text.length > 80 ||
          !selectionIsInCourse(current.selection, event.target)
        ) {
          hidePopup();
          return;
        }

        activeTerm = "";
        var popup = renderActionPopup(current.text);
        positionPopup(popup, event.clientX, event.clientY);
        popup.style.display = "block";
      }, 0);
    });
  }

  window.__leInstallWordLookup = installWordLookup;
  installWordLookup();
})();
