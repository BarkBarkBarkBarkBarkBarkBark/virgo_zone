"use strict";

const virgoBase = new URL("../", document.currentScript.src);
window.virgoUrl = (path) => new URL(path.replace(/^\//, ""), virgoBase).toString();

class FairySocket {
  constructor({ onEvent, onOpen, onState }) {
    this.onEvent = onEvent;
    this.onOpen = onOpen;
    this.onState = onState;
    this.socket = null;
    this.reconnectAttempt = 0;
    this.reconnectTimer = null;
    this.stopped = false;
  }

  start() {
    this.stopped = false;
    this.connect();
  }

  connect() {
    if (this.stopped || this.socket?.readyState === WebSocket.OPEN || this.socket?.readyState === WebSocket.CONNECTING) {
      return;
    }
    this.onState("connecting");
    const protocol = location.protocol === "https:" ? "wss:" : "ws:";
    const url = new URL(window.virgoUrl("/ws"));
    url.protocol = protocol;
    this.socket = new WebSocket(url);
    this.socket.addEventListener("open", () => {
      this.reconnectAttempt = 0;
      this.onState("online");
      this.onOpen();
    });
    this.socket.addEventListener("message", (event) => {
      try {
        const envelope = JSON.parse(event.data);
        if (envelope && typeof envelope.type === "string" && !["hello", "pong"].includes(envelope.type)) {
          this.onEvent(envelope);
        }
      } catch (error) {
        console.debug("Ignoring invalid WebSocket envelope", error);
      }
    });
    this.socket.addEventListener("close", () => {
      this.socket = null;
      this.onState("offline");
      this.scheduleReconnect();
    });
    this.socket.addEventListener("error", () => this.socket?.close());
  }

  scheduleReconnect() {
    if (this.stopped || this.reconnectTimer !== null) {
      return;
    }
    const baseDelay = Math.min(30_000, 500 * (2 ** this.reconnectAttempt));
    const delay = baseDelay + Math.floor(Math.random() * 250);
    this.reconnectAttempt += 1;
    this.reconnectTimer = window.setTimeout(() => {
      this.reconnectTimer = null;
      this.connect();
    }, delay);
  }

  stop() {
    this.stopped = true;
    if (this.reconnectTimer !== null) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    this.socket?.close();
  }
}

window.FairySocket = FairySocket;
