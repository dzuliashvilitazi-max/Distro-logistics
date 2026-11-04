"use strict";

const crypto = require("crypto");
const express = require("express");
const { newOrderHandler } = require("./controllers/orderController");
const { initializeWhatsAppClient } = require("./services/whatsappService");

const app = express();
app.use(express.json({ limit: "100kb" }));

function requireSecret(req, res, next) {
  const expected = process.env.NOTIFIER_SECRET || "";
  const given = String(req.get("x-notifier-secret") || "");
  const a = Buffer.from(expected);
  const b = Buffer.from(given);
  if (!expected || a.length !== b.length || !crypto.timingSafeEqual(a, b)) {
    return res.status(401).json({ error: "Unauthorized" });
  }
  return next();
}

app.get("/health", (_req, res) => res.json({ ok: true }));
app.post("/notify/new-order", requireSecret, newOrderHandler);

if (require.main === module) {
  const port = Number(process.env.PORT || 4010);
  initializeWhatsAppClient();
  app.listen(port, () => console.log(`[notifier] listening on ${port}`));
}

module.exports = app;
