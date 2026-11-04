import { createContext, useContext, useState } from "react";

const CartContext = createContext(null);
export const useCart = () => useContext(CartContext);

export function CartProvider({ children }) {
  const [items, setItems] = useState(() => {
    try { return JSON.parse(localStorage.getItem("distro_cart") || "[]"); } catch { return []; }
  });

  const persist = (next) => {
    setItems(next);
    localStorage.setItem("distro_cart", JSON.stringify(next));
  };

  const addItem = (product, quantity) => {
    const existing = items.find((i) => i.product_id === product.id);
    let next;
    if (existing) {
      next = items.map((i) => i.product_id === product.id ? { ...i, quantity: i.quantity + quantity } : i);
    } else {
      next = [...items, {
        product_id: product.id, name: product.name, image: product.image,
        supplier_id: product.supplier_id, supplier_name: product.supplier_name,
        moq: product.moq, tier_pricing: product.tier_pricing, price_per_unit: product.price_per_unit,
        quantity,
      }];
    }
    persist(next);
  };

  const addItems = (products) => {
    let next = [...items];
    for (const p of products) {
      const fresh = {
        product_id: p.id, name: p.name, image: p.image,
        supplier_id: p.supplier_id, supplier_name: p.supplier_name,
        moq: p.moq, tier_pricing: p.tier_pricing, price_per_unit: p.price_per_unit,
      };
      const idx = next.findIndex((i) => i.product_id === p.id);
      if (idx >= 0) next[idx] = { ...next[idx], ...fresh, quantity: next[idx].quantity + p.quantity };
      else next.push({ ...fresh, quantity: p.quantity });
    }
    persist(next);
  };

  const updateQty = (product_id, quantity) => {
    persist(items.map((i) => i.product_id === product_id ? { ...i, quantity } : i));
  };
  const removeItem = (product_id) => persist(items.filter((i) => i.product_id !== product_id));
  const clear = () => persist([]);
  const count = items.reduce((s, i) => s + i.quantity, 0);

  return (
    <CartContext.Provider value={{ items, addItem, addItems, updateQty, removeItem, clear, count }}>
      {children}
    </CartContext.Provider>
  );
}
