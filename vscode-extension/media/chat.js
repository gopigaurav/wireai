(function () {
  const vscode = acquireVsCodeApi();
  const messages = document.getElementById("messages");
  const input = document.getElementById("input");
  const send = document.getElementById("send");
  const status = document.getElementById("status");
  const contextEl = document.getElementById("context");

  let turn = null;
  let queueSize = 0;

  function scroll() {
    messages.scrollTop = messages.scrollHeight;
  }

  function beginBotTurn() {
    const wrap = document.createElement("div");
    wrap.className = "turn";
    const bot = document.createElement("div");
    bot.className = "msg bot";
    const label = document.createElement("span");
    label.className = "label";
    label.textContent = "VoxPrime: ";
    const body = document.createElement("span");
    body.className = "bot-body";
    bot.appendChild(label);
    bot.appendChild(body);
    wrap.appendChild(bot);
    const thinking = document.createElement("div");
    thinking.className = "thinking";
    thinking.hidden = true;
    wrap.appendChild(thinking);
    const activity = document.createElement("div");
    activity.className = "activity";
    activity.hidden = true;
    wrap.appendChild(activity);
    messages.appendChild(wrap);
    scroll();
    return { wrap, body, thinking, activity, segmentOpen: false, label };
  }

  function addUser(text) {
    const div = document.createElement("div");
    div.className = "msg user";
    div.textContent = text;
    messages.appendChild(div);
    scroll();
  }

  function addActivity(activityEl, line) {
    activityEl.hidden = false;
    const row = document.createElement("div");
    row.textContent = line;
    activityEl.appendChild(row);
  }

  function queueSuffix() {
    return queueSize > 0 ? " · " + queueSize + " queued" : "";
  }

  function handleEvent(ev) {
    if (!turn) return;
    if (ev.type === "assistant_start") {
      if (turn.segmentOpen) turn.body.appendChild(document.createTextNode("\n\n"));
      turn.label.textContent = (ev.label || "VoxPrime") + ": ";
      turn.segmentOpen = true;
    } else if (ev.type === "assistant_delta") {
      turn.body.appendChild(document.createTextNode(ev.text || ""));
      scroll();
    } else if (ev.type === "thinking_delta") {
      turn.thinking.hidden = false;
      turn.thinking.appendChild(document.createTextNode(ev.text || ""));
      scroll();
    } else if (ev.type === "status") {
      status.textContent = (ev.text || "") + queueSuffix();
    } else if (ev.type === "activity") {
      addActivity(turn.activity, ev.line || "");
      scroll();
    } else if (ev.type === "error") {
      turn.body.appendChild(
        document.createTextNode("\n\nError: " + (ev.message || "unknown"))
      );
    } else if (ev.type === "turn_done") {
      status.textContent = queueSize > 0 ? queueSize + " queued" : "";
      for (const ln of ev.activity || []) {
        addActivity(turn.activity, ln);
      }
    }
  }

  function submit() {
    const text = input.value.trim();
    if (!text) return;
    input.value = "";
    addUser(text);
    vscode.postMessage({ type: "chat", text });
  }

  send.addEventListener("click", submit);
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submit();
    }
  });

  window.addEventListener("message", (e) => {
    const msg = e.data;
    if (msg.type === "context") {
      contextEl.textContent = msg.text;
    }
    if (msg.type === "prefill") {
      input.value = msg.text || "";
      input.focus();
    }
    if (msg.type === "queueSize") {
      queueSize = msg.size || 0;
      if (queueSize > 0) {
        status.textContent = queueSize + " message(s) queued";
      }
    }
    if (msg.type === "streamStart") {
      turn = beginBotTurn();
    }
    if (msg.type === "streamEvent") {
      handleEvent(msg.event);
    }
    if (msg.type === "streamEnd") {
      turn = null;
      scroll();
    }
  });

  vscode.postMessage({ type: "ready" });
})();
