"use strict";

const qrcode = require("qrcode-terminal");
const { Client, LocalAuth } = require("whatsapp-web.js");

const APP_URL = (process.env.APP_BASE_URL || "https://distrologistics.ge").replace(/\/+$/, "");

let client = null;
let ready = false;
let readyPromise = null;

function initializeWhatsAppClient() {
  if (client) return readyPromise;
  client = new Client({
    // LocalAuth persists the session on disk, so QR scanning is needed only once.
    authStrategy: new LocalAuth({ dataPath: process.env.WHATSAPP_SESSION_DIR || ".wwebjs_auth" }),
    puppeteer: { args: ["--no-sandbox", "--disable-setuid-sandbox"] },
  });
  readyPromise = new Promise((resolve, reject) => {
    client.on("qr", (qr) => {
      console.log("[whatsapp] Scan this QR code with WhatsApp (Linked devices):");
      qrcode.generate(qr, { small: true });
    });
    client.on("authenticated", () => console.log("[whatsapp] Authenticated."));
    client.on("auth_failure", (message) => {
      console.error(`[whatsapp] Authentication failed: ${message}`);
      reject(new Error(String(message)));
    });
    client.on("ready", () => {
      ready = true;
      console.log("WhatsApp Client is Ready!");
      resolve(client);
    });
    client.on("disconnected", (reason) => {
      ready = false;
      console.error(`[whatsapp] Disconnected: ${reason}`);
    });
  });
  // Keep an unhandled rejection from crashing the server if nobody awaits it.
  readyPromise.catch(() => {});
  client.initialize().catch((error) => {
    console.error(`[whatsapp] Initialization failed: ${error.message}`);
  });
  return readyPromise;
}

// 9955XXXXXXXX@c.us — strips spaces, '+', other symbols and leading zeros.
function toChatId(phone) {
  let digits = String(phone || "").replace(/\D/g, "").replace(/^0+/, "");
  if (digits.length === 9 && digits.startsWith("5")) digits = `995${digits}`;
  if (digits.length < 10 || digits.length > 15) return null;
  return `${digits}@c.us`;
}

function formatOrderMessage(order, store) {
  const amount = Number(order.totalAmount ?? order.total ?? 0).toFixed(2);
  return [
    "📦 *Distro Logistics — ახალი შეკვეთა!*",
    "",
    `• შეკვეთის #: ${order.id}`,
    `• მაღაზია: ${store?.name || "—"}`,
    `• ჯამური თანხა: ${amount} ₾`,
    "",
    `გახსენით პანელი დეტალების სანახავად: ${APP_URL}/orders/${order.id}`,
  ].join("\n");
}

/**
 * Sends the new-order alert. Never throws; resolves true on success.
 */
async function sendWhatsAppOrderAlert(distributorPhone, orderDetails) {
  try {
    const chatId = toChatId(distributorPhone);
    if (!chatId) throw new Error(`invalid phone "${distributorPhone}"`);
    if (!client) initializeWhatsAppClient();
    if (!ready) await readyPromise;
    const messageText = formatOrderMessage(orderDetails.order, orderDetails.store);
    await client.sendMessage(chatId, messageText);
    return true;
  } catch (error) {
    console.error(`[whatsapp] Failed to send alert for order ${orderDetails?.order?.id}: ${error.message}`);
    return false;
  }
}

module.exports = { initializeWhatsAppClient, sendWhatsAppOrderAlert, formatOrderMessage, toChatId };
