const dayFormatter = new Intl.DateTimeFormat("en-CA", {
  timeZone: "Asia/Tbilisi", year: "numeric", month: "2-digit", day: "2-digit",
});

export function purchaseDay(value) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  const parts = Object.fromEntries(dayFormatter.formatToParts(date).map((part) => [part.type, part.value]));
  return `${parts.year}-${parts.month}-${parts.day}`;
}

function weekStart(day) {
  const date = new Date(`${day}T00:00:00Z`);
  date.setUTCDate(date.getUTCDate() - (date.getUTCDay() + 6) % 7);
  return date.toISOString().slice(0, 10);
}

function inRange(day, from, to) {
  return Boolean(day) && (!from || day >= from) && (!to || day <= to);
}

export function calculatePurchaseAnalytics(orders, from, to) {
  const selected = orders.filter((order) => inRange(purchaseDay(order.created_at), from, to));
  const completed = selected.filter((order) => order.status === "Delivered");
  const products = new Map();
  const suppliers = new Map();
  const orderMonths = new Map();
  const paymentDays = new Map();
  const paymentWeeks = new Map();
  const paymentMonths = new Map();
  for (const order of selected) {
    const month = purchaseDay(order.created_at).slice(0, 7);
    orderMonths.set(month, (orderMonths.get(month) || 0) + 1);
  }
  for (const order of completed) {
    const supplierKey = order.supplier_id || order.supplier_name || "";
    const supplier = suppliers.get(supplierKey) || { id: supplierKey, name: order.supplier_name || "—", orders: 0 };
    supplier.orders += 1;
    suppliers.set(supplierKey, supplier);
    const countedProducts = new Set();
    for (const item of order.items || []) {
      const key = item.product_id || item.name;
      if (!key) continue;
      const product = products.get(key) || { id: key, name: item.name || key, quantity: 0, orders: 0, history: [] };
      product.quantity += Number(item.quantity || 0);
      if (!countedProducts.has(key)) product.orders += 1;
      countedProducts.add(key);
      product.history.push({ orderId: order.id, orderNo: order.order_no, date: order.created_at, supplier: order.supplier_name, quantity: item.quantity, price: item.unit_price });
      products.set(key, product);
    }
  }
  let spentCents = 0;
  let undatedPayments = 0;
  for (const order of orders) {
    if (order.status === "Cancelled") continue;
    let payments = order.payment_entries || [];
    if (!payments.length && Number(order.amount_paid || 0) > 0) {
      const paidAt = order.paid_at || (order.paid_at_checkout && order.payment_method === "online" ? order.created_at : "");
      if (paidAt) payments = [{ amount: order.amount_paid, recorded_at: paidAt }];
    }
    const datedCents = payments.reduce((total, payment) => total + (purchaseDay(payment.recorded_at) ? Math.round(Number(payment.amount || 0) * 100) : 0), 0);
    if (Math.round(Number(order.amount_paid || 0) * 100) > datedCents) undatedPayments += 1;
    for (const payment of payments) {
      const day = purchaseDay(payment.recorded_at);
      if (!inRange(day, from, to)) continue;
      const cents = Math.round(Number(payment.amount || 0) * 100);
      spentCents += cents;
      for (const [map, key] of [[paymentDays, day], [paymentWeeks, weekStart(day)], [paymentMonths, day.slice(0, 7)]]) {
        map.set(key, (map.get(key) || 0) + cents);
      }
    }
  }
  const series = (map, divisor = 1) => [...map].sort(([left], [right]) => left.localeCompare(right)).map(([date, value]) => ({ date, value: value / divisor }));
  return {
    orderCount: selected.length, completedCount: completed.length, spent: spentCents / 100, undatedPayments,
    products: [...products.values()].sort((left, right) => right.orders - left.orders || right.quantity - left.quantity),
    suppliers: [...suppliers.values()].sort((left, right) => right.orders - left.orders),
    ordersByMonth: series(orderMonths), paymentsByDay: series(paymentDays, 100),
    paymentsByWeek: series(paymentWeeks, 100), paymentsByMonth: series(paymentMonths, 100),
  };
}