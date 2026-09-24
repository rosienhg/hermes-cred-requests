/* Credential Requests — dashboard tab.
 *
 * Hermes files a request (via `hermes credreq add`) naming what it needs and where the value
 * should land. This tab shows the pending ones; the user types the value here and it is POSTed
 * straight to the destination writer — the value is never returned, logged or stored, and never
 * appears in the agent conversation.
 *
 * Deep link: /cred-requests?req=<id> highlights that request, scrolls to it and focuses its
 * first input, so a link sent over WhatsApp lands on the thing being asked for.
 */
(function () {
  "use strict";

  var SDK = window.__HERMES_PLUGIN_SDK__;
  var REGISTRY = window.__HERMES_PLUGINS__;
  var NAME = "hermes-cred-requests";

  if (!SDK || !REGISTRY) {
    console.error("[cred-requests] dashboard plugin SDK unavailable — tab not registered");
    return;
  }

  var React = SDK.React;
  var h = React.createElement;
  var C = SDK.components;
  var useState = SDK.hooks.useState;
  var useEffect = SDK.hooks.useEffect;
  var useCallback = SDK.hooks.useCallback;
  var useRef = SDK.hooks.useRef;

  var API = "/api/plugins/" + NAME;
  var POLL_MS = 15000;
  var JSON_HEADERS = { "Content-Type": "application/json" };

  function searchParam(key) {
    try {
      return new URLSearchParams(window.location.search).get(key);
    } catch (err) {
      return null;
    }
  }

  function destText(field) {
    var dest = field.dest || {};
    return dest.kind === "env" ? "env " + dest.target : "file " + dest.target;
  }

  function ago(iso) {
    if (!iso) return "";
    try {
      return SDK.utils.isoTimeAgo(iso);
    } catch (err) {
      return "";
    }
  }

  /* Masked input with a per-field reveal, and Enter to submit. */
  function SecretInput(props) {
    var shown = useState(false);
    var show = shown[0];
    var setShow = shown[1];
    return h("div", { className: "relative flex items-center" },
      h(C.Input, {
        id: props.id,
        type: show ? "text" : "password",
        value: props.value,
        autoComplete: "off",
        spellCheck: false,
        autoFocus: !!props.autoFocus,
        placeholder: props.placeholder || "paste the value",
        className: "pr-16 font-mono text-xs",
        onChange: function (event) { props.onChange(event.target.value); },
        onKeyDown: function (event) {
          if (event.key === "Enter" && props.onSubmit) props.onSubmit();
        },
      }),
      h("button", {
        type: "button",
        tabIndex: -1,
        className: "absolute right-2 text-[10px] uppercase tracking-wide text-muted-foreground hover:text-foreground",
        onClick: function () { setShow(!show); },
      }, show ? "hide" : "show")
    );
  }

  function RequestCard(props) {
    var request = props.request;
    var fields = request.fields || [];

    var valuesState = useState({});
    var values = valuesState[0];
    var setValues = valuesState[1];
    var statusState = useState({ kind: "idle" });
    var status = statusState[0];
    var setStatus = statusState[1];
    var busyState = useState(false);
    var busy = busyState[0];
    var setBusy = busyState[1];

    var setValue = function (name, value) {
      setValues(function (prev) {
        var next = Object.assign({}, prev);
        next[name] = value;
        return next;
      });
    };

    var complete = fields.length > 0 && fields.every(function (field) {
      return String(values[field.name] || "").trim().length > 0;
    });

    var submit = function () {
      if (busy || !complete) return;
      setBusy(true);
      setStatus({ kind: "idle" });
      SDK.fetchJSON(API + "/fulfill", {
        method: "POST",
        headers: JSON_HEADERS,
        body: JSON.stringify({ id: request.id, values: values }),
      })
        .then(function (result) {
          var where = (result.saved || []).map(function (entry) { return entry.dest; }).join(", ");
          setValues({});
          setStatus({ kind: "ok", message: "Saved to " + where + " — the value never entered the chat." });
          props.onChanged();
        })
        .catch(function (err) {
          setStatus({ kind: "err", message: (err && err.message) || String(err) });
        })
        .then(function () { setBusy(false); });
    };

    return h("div", { id: "req-" + request.id },
      h(C.Card, { className: props.focused ? "ring-2 ring-primary" : undefined },
        h(C.CardHeader, { className: "pb-2" },
          h("div", { className: "flex flex-wrap items-start justify-between gap-3" },
            h("div", null,
              h(C.CardTitle, { className: "text-base" }, request.title),
              h("div", { className: "mt-1 text-xs text-muted-foreground" },
                (request.why ? request.why + " · " : "") + "asked " + ago(request.created_at) + " · " + request.id)
            ),
            props.focused
              ? h(C.Badge, { variant: "secondary" }, "you were sent here for this")
              : null
          )
        ),
        h(C.CardContent, { className: "space-y-4" },
          fields.map(function (field, index) {
            var inputId = "f-" + request.id + "-" + field.name;
            return h("div", { className: "space-y-1", key: field.name },
              h(C.Label, { htmlFor: inputId, className: "text-xs" }, field.label),
              h("div", { className: "text-[11px] text-muted-foreground" }, "saves to " + destText(field)),
              field.hint
                ? h("div", { className: "text-[11px] text-muted-foreground" }, field.hint)
                : null,
              h(SecretInput, {
                id: inputId,
                value: values[field.name] || "",
                onChange: function (value) { setValue(field.name, value); },
                autoFocus: !!(props.focused && index === 0),
                onSubmit: submit,
              })
            );
          }),
          status.kind === "ok"
            ? h("div", { className: "text-xs text-primary" }, status.message)
            : null,
          status.kind === "err"
            ? h("div", { className: "text-xs text-destructive" }, status.message)
            : null,
          h("div", { className: "flex items-center gap-2 pt-1" },
            h(C.Button, { size: "sm", disabled: !complete || busy, onClick: submit },
              busy ? "Saving…" : "Save securely"),
            h(C.Button, {
              size: "sm",
              variant: "ghost",
              disabled: busy,
              onClick: function () { props.onCancel(request); },
            }, "Cancel request")
          )
        )
      )
    );
  }

  function HistoryList(props) {
    if (!props.requests.length) return null;
    return h(C.Card, null,
      h(C.CardHeader, { className: "pb-2" }, h(C.CardTitle, { className: "text-sm" }, "History")),
      h(C.CardContent, { className: "space-y-2" },
        props.requests.map(function (request) {
          var status = request.expired && request.status === "pending" ? "expired" : request.status;
          var where = (request.saved || []).map(function (entry) { return entry.dest; }).join(", ");
          var when = request.filled_at || request.cancelled_at || request.created_at;
          return h("div", { key: request.id, className: "flex items-start justify-between gap-3 text-xs" },
            h("span", { className: "truncate" }, request.title),
            h("span", { className: "shrink-0 text-muted-foreground" },
              status + (where && status === "filled" ? " · " + where : "") + (when ? " · " + ago(when) : ""))
          );
        })
      )
    );
  }

  function CredentialRequestsPage() {
    var state = useState({ loading: true, error: null, data: null });
    var current = state[0];
    var setState = state[1];
    var scrolled = useRef(false);

    var load = useCallback(function () {
      return SDK.fetchJSON(API + "/requests")
        .then(function (data) {
          setState({ loading: false, error: null, data: data });
        })
        .catch(function (err) {
          setState(function (prev) {
            return { loading: false, error: (err && err.message) || String(err), data: prev.data };
          });
        });
    }, []);

    useEffect(function () {
      load();
      var timer = setInterval(load, POLL_MS);
      var onFocus = function () { load(); };
      window.addEventListener("focus", onFocus);
      return function () {
        clearInterval(timer);
        window.removeEventListener("focus", onFocus);
      };
    }, [load]);

    var focusId = searchParam("req");
    var requests = (current.data && current.data.requests) || [];
    var pending = requests.filter(function (request) {
      return request.status === "pending" && !request.expired;
    });
    var closed = requests.filter(function (request) {
      return request.status !== "pending" || request.expired;
    });
    if (focusId) {
      pending.sort(function (a, b) { return (b.id === focusId) - (a.id === focusId); });
    }

    useEffect(function () {
      if (!focusId || !current.data || scrolled.current) return;
      var node = document.getElementById("req-" + focusId);
      if (node) {
        scrolled.current = true;
        if (node.scrollIntoView) node.scrollIntoView({ block: "start", behavior: "smooth" });
      }
    }, [focusId, current.data]);

    var cancel = function (request) {
      SDK.fetchJSON(API + "/cancel", {
        method: "POST",
        headers: JSON_HEADERS,
        body: JSON.stringify({ id: request.id }),
      }).then(load).catch(function () { load(); });
    };

    return h("div", { className: "space-y-4" },
      h(C.Card, null,
        h(C.CardHeader, { className: "pb-2" },
          h("div", { className: "flex flex-wrap items-center justify-between gap-3" },
            h("div", null,
              h(C.CardTitle, { className: "text-base" }, "Credential requests"),
              h("div", { className: "mt-1 text-xs text-muted-foreground" },
                "When Hermes needs a secret it files a request here. What you type goes straight to "
                + "its destination — the value never enters the chat.")
            ),
            h("div", { className: "flex items-center gap-2" },
              h(C.Badge, { variant: pending.length ? "default" : "secondary" },
                pending.length ? pending.length + " pending" : "nothing pending"),
              h(C.Button, { size: "sm", variant: "outline", onClick: load }, "Refresh")
            )
          )
        ),
        current.error
          ? h(C.CardContent, null,
              h("div", { className: "text-xs text-destructive" },
                "could not reach the backend: " + current.error))
          : null
      ),

      pending.map(function (request) {
        return h(RequestCard, {
          key: request.id,
          request: request,
          focused: !!focusId && request.id === focusId,
          onChanged: load,
          onCancel: cancel,
        });
      }),

      (!current.loading && !current.error && !pending.length)
        ? h(C.Card, null,
            h(C.CardContent, { className: "py-6 text-center text-xs text-muted-foreground" },
              "Nothing pending. Hermes will drop a request here — and send you a link to it — "
              + "when it needs a credential from you."))
        : null,

      h(HistoryList, { requests: closed }),

      h(C.Card, null,
        h(C.CardContent, { className: "py-3 text-[11px] leading-relaxed text-muted-foreground" },
          "Env values land in ~/.hermes/.env (0600) through Hermes's own writer, and are picked up "
          + "by the next session; an already-running session picks them up with /reload. File values "
          + "are written 0600 at the path shown. Nothing here is ever read back out.")
      )
    );
  }

  REGISTRY.register(NAME, CredentialRequestsPage);
})();