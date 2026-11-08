import test from "node:test";
import assert from "node:assert/strict";
import { calculatePurchaseAnalytics, purchaseDay } from "./purchaseAnalytics.mjs";

test("purchase analytics filter orders and confirmed payments independently", () => {
  const orders = [
    { id: "one", order_no: "1", status: "Delivered", supplier_id: "supplier", supplier_name: "Supplier", created_at: "2026-10-30T12:00:00Z", items: [{ product_id: "product", name: "Product", quantity: 2, unit_price: 10 }], payment_entries: [{ amount: 7.25, recorded_at: "2026-11-02T10:00:00Z" }] },
    { id: "two", order_no: "2", status: "Delivered", supplier_id: "supplier", supplier_name: "Supplier", created_at: "2026-11-03T12:00:00Z", items: [{ product_id: "product", name: "Product", quantity: 3, unit_price: 11 }], payment_entries: [{ amount: 5.10, recorded_at: "2026-11-04T10:00:00Z" }] },
    { id: "three", status: "Cancelled", created_at: "2026-11-05T12:00:00Z", items: [{ product_id: "product", quantity: 100 }], payment_entries: [{ amount: 999, recorded_at: "2026-11-05T10:00:00Z" }] },
  ];
  const result = calculatePurchaseAnalytics(orders, "2026-11-01", "2026-11-30");
  assert.equal(result.orderCount, 2);
  assert.equal(result.completedCount, 1);
  assert.equal(result.spent, 12.35);
  assert.equal(result.products[0].quantity, 3);
  assert.equal(result.products[0].history[0].orderNo, "2");
  assert.equal(result.suppliers[0].orders, 1);
  assert.deepEqual(result.paymentsByWeek, [{ date: "2026-11-02", value: 12.35 }]);
  assert.equal(purchaseDay("2026-11-01T22:00:00Z"), "2026-11-02");
});

test("product frequency counts orders, not line count or quantity", () => {
  const orders = [
    { id: "one", status: "Delivered", created_at: "2026-11-01T10:00:00Z", items: [{ product_id: "a", quantity: 50 }, { product_id: "a", quantity: 2 }, { product_id: "b", quantity: 1 }] },
    { id: "two", status: "Delivered", created_at: "2026-11-02T10:00:00Z", items: [{ product_id: "b", quantity: 1 }] },
    { id: "three", status: "Processing", created_at: "2026-11-02T10:00:00Z", items: [{ product_id: "b", quantity: 100 }], amount_paid: 99 },
  ];
  const result = calculatePurchaseAnalytics(orders, "2026-11-01", "2026-11-30");
  assert.equal(result.products[0].id, "b");
  assert.equal(result.products[0].orders, 2);
  assert.equal(result.products[1].orders, 1);
  assert.equal(result.products[1].quantity, 52);
  assert.equal(result.spent, 0);
  assert.equal(result.undatedPayments, 1);
});

test("legacy checkout payments use the actual checkout date", () => {
  const orders = [{ id: "legacy", status: "Delivered", created_at: "2026-11-02T10:00:00Z", payment_method: "online", paid_at_checkout: true, amount_paid: 20, payment_entries: [] }];
  const result = calculatePurchaseAnalytics(orders, "2026-11-01", "2026-11-30");
  assert.equal(result.spent, 20);
  assert.equal(result.undatedPayments, 0);
});