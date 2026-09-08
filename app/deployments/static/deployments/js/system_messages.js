/*
 * Makes the PromQL block copyable: clicking the <pre> selects its contents, and the "Copy"
 * button copies the query. Used by the system-messages sidebar and by the SystemMessage
 * change page's `promql_query` field, which render the same markup.
 *
 * The query is read back out of the DOM via `textContent` rather than templated into this
 * file (dataset and server names come from ERDDAP and are untrusted), and `textContent` is
 * the one read that cannot be turned into an injection.
 */
(function () {
  "use strict";

  var FLASH_MS = 1500;

  function selectAllText(node) {
    var selection = window.getSelection && window.getSelection();
    if (!selection) {
      return;
    }
    var range = document.createRange();
    range.selectNodeContents(node);
    selection.removeAllRanges();
    selection.addRange(range);
  }

  function flash(button, label) {
    if (!button.dataset.originalLabel) {
      button.dataset.originalLabel = button.textContent;
    }
    button.textContent = label;
    window.clearTimeout(button._systemMessageCopyTimeout);
    button._systemMessageCopyTimeout = window.setTimeout(function () {
      button.textContent = button.dataset.originalLabel;
    }, FLASH_MS);
  }

  function copyQuery(pre, button) {
    var text = pre.textContent;

    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(
        function () {
          flash(button, "Copied");
        },
        function () {
          // Clipboard permission denied, fall back to selecting the text.
          selectAllText(pre);
          flash(button, "Selected, use Ctrl/Cmd-C");
        },
      );
      return;
    }

    // `navigator.clipboard` is undefined outside secure contexts, plain HTTP on a
    // non-localhost host, which is plausible for an internal admin.
    selectAllText(pre);
    flash(button, "Selected, use Ctrl/Cmd-C");
  }

  // Delegated from `document`, not bound to each block. Django's `Media` renders this into
  // <head> with no `defer`, so it runs before the sidebar is parsed: querying for
  // `.system-message-promql` here matches nothing and leaves every button silently inert.
  document.addEventListener("click", function (event) {
    var button = event.target.closest(".system-message-copy");
    if (button) {
      var block = button.closest(".system-message-promql");
      var blockPre = block && block.querySelector("pre");
      if (blockPre) {
        copyQuery(blockPre, button);
      }
      return;
    }

    var pre = event.target.closest(".system-message-promql pre");
    if (pre) {
      selectAllText(pre);
    }
  });
})();
