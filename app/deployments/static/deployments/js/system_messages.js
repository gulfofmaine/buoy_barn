/*
 * Makes the PromQL block in the system-messages sidebar (and on the SystemMessage change
 * page, where the same markup is reused for the `promql_query` readonly field) easy to copy:
 * clicking the <pre> selects its whole contents, and the "Copy" button next to it copies the
 * query to the clipboard.
 *
 * No inline handlers (the admin's CSP disallows them in some deployments anyway), no jQuery,
 * no build step. The query text is read back out of the DOM via `textContent` rather than
 * being handed to us in a data attribute or templated into this file -- dataset and server
 * names come from ERDDAP and are untrusted, and `textContent` is exactly the read that can't
 * be turned into an injection.
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
          // Clipboard permission denied or unavailable at call time -- fall back to
          // selecting the text so the user can still copy it themselves.
          selectAllText(pre);
          flash(button, "Selected, use Ctrl/Cmd-C");
        },
      );
      return;
    }

    // `navigator.clipboard` is undefined outside secure contexts (plain HTTP on a
    // non-localhost host), which is plausible for an internal admin. Select the text so a
    // manual Ctrl/Cmd-C still works.
    selectAllText(pre);
    flash(button, "Selected, use Ctrl/Cmd-C");
  }

  // Delegated from `document` rather than bound to each block on load. Django's `Media`
  // renders this into <head> with no `defer`, so it executes before the sidebar it operates
  // on has been parsed -- querying for `.system-message-promql` here would match nothing and
  // leave every button inert, with the page still rendering perfectly and every test passing.
  // `document` is the one node guaranteed to exist at this point.
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
