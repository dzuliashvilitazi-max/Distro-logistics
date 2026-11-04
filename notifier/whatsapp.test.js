"use strict";

const test = require("node:test");
const assert = require("node:assert");
const { formatOrderMessage, toChatId, sendWhatsAppOrderAlert } = require("./services/whatsappService");

test("message contains order id, store, amount and link", () => {
  const text = formatOrderMessage({ id: "o-1", totalAmount: 12.5 }, { name: "Shop" });
  assert.match(text, /შეკვეთის #: o-1/);
  assert.match(text, /მაღაზია: Shop/);
  assert.match(text, /ჯამური თანხა: 12\.50 ₾/);
  assert.match(text, /https:\/\/distrologistics\.ge\/orders\/o-1/);
});

test("chat id formatting", () => {
  assert.strictEqual(toChatId("555 12 34 56"), "995555123456@c.us");
  assert.strictEqual(toChatId("+995 555 123 456"), "995555123456@c.us");
  assert.strictEqual(toChatId("00995555123456"), "995555123456@c.us");
  assert.strictEqual(toChatId("12"), null);
});

test("invalid phone is swallowed and reported as false", async () => {
  assert.strictEqual(await sendWhatsAppOrderAlert("bad", { order: { id: "o-3" } }), false);
});
