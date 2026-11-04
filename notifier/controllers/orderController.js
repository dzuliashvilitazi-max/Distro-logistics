"use strict";

const { sendWhatsAppOrderAlert } = require("../services/whatsappService");

/**
 * Fire-and-forget: the alert runs in the background so the response to the
 * store is never delayed, and failures never reach the caller.
 */
function notifyNewOrder(order, store, distributor) {
  setImmediate(() => {
    sendWhatsAppOrderAlert(distributor?.phone, { order, store }).catch((error) => {
      console.error(`[orders] WhatsApp notification error: ${error.message}`);
    });
  });
}

// POST /notify/new-order — invoked by the Distro API after an order is stored.
function newOrderHandler(req, res) {
  const { order, store, distributor } = req.body || {};
  if (!order?.id || !distributor?.phone) {
    return res.status(400).json({ error: "order.id and distributor.phone are required" });
  }
  notifyNewOrder(order, store, distributor);
  return res.status(202).json({ queued: true });
}

module.exports = { notifyNewOrder, newOrderHandler };
