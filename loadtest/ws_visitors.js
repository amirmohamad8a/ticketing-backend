// WebSocket + HTTP load test for the chat widget and the realtime layer.
//
// It opens N visitor sockets and M agent sockets against a running stack:
//   1. Every visitor starts a conversation over HTTP and gets a visitor token.
//   2. The visitor exchanges the token for a single-use WebSocket ticket and
//      connects to /ws/ with the site's allowed Origin.
//   3. The visitor joins its own ticket and then posts a message every
//      MSG_INTERVAL_MS over the widget REST route.
//   4. In parallel, every agent opens a /ws/ socket with a ticket from
//      POST /api/ws/ticket/ and answers the visitor messages it owns with
//      POST /api/tickets/{id}/comments/.
//
// Latency is measured in one process, so Date.now() is a shared clock:
//   * the visitor stamps every message it sends with client_msg_id=<send ms>
//     and the agent reports visitor_to_agent_ms when the event arrives;
//   * the agent stamps every reply with client_msg_id=<send ms> and the
//     visitor reports agent_to_visitor_ms when the reply event arrives.
//
// See loadtest/README.md for the prerequisites and how to read the results.

import exec from "k6/execution";
import http from "k6/http";
import ws from "k6/ws";
import { Counter, Rate, Trend } from "k6/metrics";

const BASE_URL = __ENV.BASE_URL || "http://localhost:8000";
const WS_URL = __ENV.WS_URL || BASE_URL.replace(/^http/, "ws");
const SITE_KEY = __ENV.SITE_KEY || "demo-store-widget-key";
const ORIGIN = __ENV.ORIGIN || "http://localhost:3000";

const AGENT_USERNAME = __ENV.AGENT_USERNAME || "demo_agent";
const AGENT_PASSWORD = __ENV.AGENT_PASSWORD || "demo-ticketing-2026";

const VISITORS = parseInt(__ENV.VISITORS || "10", 10);
const AGENTS = parseInt(__ENV.AGENTS || "5", 10);
const MSG_INTERVAL_MS = parseInt(__ENV.MSG_INTERVAL_MS || "1000", 10);
const SESSION_MS = parseInt(__ENV.SESSION_MS || "20000", 10);
const WARMUP_MS = parseInt(__ENV.WARMUP_MS || "2000", 10);
const MESSAGE_SIZE = parseInt(__ENV.MESSAGE_SIZE || "64", 10);

export const options = {
  summaryTrendStats: ["avg", "min", "med", "p(50)", "p(90)", "p(95)", "p(99)", "max"],
  scenarios: {
    connect: {
      executor: "per-vu-iterations",
      vus: VISITORS + AGENTS,
      iterations: 1,
      maxDuration: `${SESSION_MS + 20000}ms`,
      gracefulStop: "5s",
    },
  },
};

const visitorToAgent = new Trend("visitor_to_agent_ms", true);
const agentToVisitor = new Trend("agent_to_visitor_ms", true);
const connectTime = new Trend("ws_connect_ms", true);
const messagesSent = new Counter("messages_sent_total");
const repliesSent = new Counter("agent_replies_total");
const repliesReceived = new Counter("visitor_replies_received_total");
const http429 = new Counter("http_429_total");
const http5xx = new Counter("http_5xx_total");
const httpOther = new Counter("http_other_errors_total");
const wsFailures = new Counter("ws_connect_failures_total");
const wsClose1009 = new Counter("ws_close_1009_total");
const wsClose4429 = new Counter("ws_close_4429_total");
const wsClose1003 = new Counter("ws_close_1003_total");
const wsAbnormal = new Counter("ws_abnormal_close_total");
const connectRate = new Rate("ws_connect_success_rate");

function body(size) {
  return "x".repeat(Math.max(0, size));
}

function recordHttp(response) {
  if (response.status === 429) {
    http429.add(1);
  } else if (response.status >= 500) {
    http5xx.add(1);
  } else if (response.status >= 400) {
    httpOther.add(1);
  }
}

function positiveNumber(value) {
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : 0;
}

function onClose(code) {
  if (code === 1009) {
    wsClose1009.add(1);
  } else if (code === 4429) {
    wsClose4429.add(1);
  } else if (code === 1003) {
    wsClose1003.add(1);
  } else if (code !== 1000 && code !== 1001) {
    wsAbnormal.add(1);
  }
}

function jsonHeaders(extra) {
  return Object.assign({ "Content-Type": "application/json" }, extra || {});
}

export function setup() {
  const login = http.post(
    `${BASE_URL}/api/token/`,
    JSON.stringify({ username: AGENT_USERNAME, password: AGENT_PASSWORD }),
    { headers: jsonHeaders() }
  );
  if (login.status !== 200) {
    throw new Error(`Agent login failed with status ${login.status}`);
  }
  return { agentToken: login.json().access };
}

function startConversation(index) {
  const response = http.post(
    `${BASE_URL}/api/widget/conversations/`,
    JSON.stringify({ site_key: SITE_KEY, body: `load visitor ${index}` }),
    { headers: jsonHeaders({ Origin: ORIGIN }) }
  );
  if (response.status !== 200 && response.status !== 201) {
    recordHttp(response);
    return null;
  }
  const payload = response.json();
  return { token: payload.token, ticketId: payload.conversation.id };
}

function widgetSocketTicket(token) {
  const response = http.post(`${BASE_URL}/api/widget/ws/ticket/`, null, {
    headers: { "X-Visitor-Token": token, Origin: ORIGIN },
  });
  if (response.status !== 200) {
    recordHttp(response);
    return null;
  }
  return response.json().ticket;
}

function sendMessages(socket, token, ticketId) {
  socket.setInterval(() => {
    const stamp = Date.now();
    const response = http.post(
      `${BASE_URL}/api/widget/conversations/${ticketId}/messages/`,
      JSON.stringify({ body: body(MESSAGE_SIZE), client_msg_id: String(stamp) }),
      { headers: jsonHeaders({ "X-Visitor-Token": token, Origin: ORIGIN }) }
    );
    if (response.status === 200 || response.status === 201) {
      messagesSent.add(1);
    } else {
      recordHttp(response);
    }
  }, MSG_INTERVAL_MS);
}

function runVisitor(index) {
  const conversation = startConversation(index);
  if (conversation === null) {
    return;
  }
  const ticket = widgetSocketTicket(conversation.token);
  if (ticket === null) {
    connectRate.add(false, { role: "visitor" });
    return;
  }

  const startedAt = Date.now();
  const response = ws.connect(
    `${WS_URL}/ws/?ticket=${ticket}`,
    { headers: { Origin: ORIGIN }, tags: { role: "visitor" } },
    function (socket) {
      connectTime.add(Date.now() - startedAt, { role: "visitor" });
      socket.on("open", function () {
        socket.send(JSON.stringify({ type: "join", ticket_id: conversation.ticketId }));
        socket.setTimeout(function () {
          sendMessages(socket, conversation.token, conversation.ticketId);
        }, WARMUP_MS);
      });
      socket.on("message", function (raw) {
        let event;
        try {
          event = JSON.parse(raw);
        } catch (error) {
          return;
        }
        if (event.type !== "message.created" || !event.data) {
          return;
        }
        if (event.data.sender_type !== "agent") {
          return;
        }
        repliesReceived.add(1);
        const sentAt = positiveNumber(event.data.client_msg_id);
        if (sentAt > 0) {
          agentToVisitor.add(Date.now() - sentAt, { role: "visitor" });
        }
      });
      socket.on("close", onClose);
      socket.on("error", function () {
        wsAbnormal.add(1);
      });
      socket.setTimeout(function () {
        socket.close();
      }, SESSION_MS);
    }
  );

  const connected = response.status === 101;
  connectRate.add(connected, { role: "visitor" });
  if (!connected) {
    wsFailures.add(1);
  }
}

function agentSocketTicket(token) {
  const response = http.post(`${BASE_URL}/api/ws/ticket/`, null, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (response.status !== 200) {
    recordHttp(response);
    return null;
  }
  return response.json().ticket;
}

function runAgent(index, agentToken) {
  const ticket = agentSocketTicket(agentToken);
  if (ticket === null) {
    connectRate.add(false, { role: "agent" });
    return;
  }

  const joined = {};
  const startedAt = Date.now();
  const response = ws.connect(
    `${WS_URL}/ws/?ticket=${ticket}`,
    { headers: { Origin: ORIGIN }, tags: { role: "agent" } },
    function (socket) {
      connectTime.add(Date.now() - startedAt, { role: "agent" });
      socket.on("message", function (raw) {
        let event;
        try {
          event = JSON.parse(raw);
        } catch (error) {
          return;
        }
        if (event.type !== "message.created" || !event.data) {
          return;
        }
        if (event.data.sender_type !== "visitor") {
          return;
        }
        const ticketId = event.ticket_id;
        if (ticketId % AGENTS !== index) {
          return;
        }
        const sentAt = positiveNumber(event.data.client_msg_id);
        if (sentAt > 0) {
          visitorToAgent.add(Date.now() - sentAt, { role: "agent" });
        }
        if (!joined[ticketId]) {
          joined[ticketId] = true;
          socket.send(JSON.stringify({ type: "join", ticket_id: ticketId }));
        }
        const replyStamp = Date.now();
        const response = http.post(
          `${BASE_URL}/api/tickets/${ticketId}/comments/`,
          JSON.stringify({ body: body(MESSAGE_SIZE), client_msg_id: String(replyStamp) }),
          { headers: jsonHeaders({ Authorization: `Bearer ${agentToken}` }) }
        );
        if (response.status === 200 || response.status === 201) {
          repliesSent.add(1);
        } else {
          recordHttp(response);
        }
      });
      socket.on("close", onClose);
      socket.on("error", function () {
        wsAbnormal.add(1);
      });
      socket.setTimeout(function () {
        socket.close();
      }, SESSION_MS);
    }
  );

  const connected = response.status === 101;
  connectRate.add(connected, { role: "agent" });
  if (!connected) {
    wsFailures.add(1);
  }
}

export default function (data) {
  const vu = exec.vu.idInTest;
  if (vu <= VISITORS) {
    runVisitor(vu - 1);
  } else {
    runAgent(vu - VISITORS - 1, data.agentToken);
  }
}
