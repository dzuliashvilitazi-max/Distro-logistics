import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";

const SupplierWarehouseContext = createContext(null);
const STORAGE_PREFIX = "distro_supplier_warehouse:";

function supplierOwnerId(user) {
  return user?.supplier_id || user?.id || "";
}

export function SupplierWarehouseProvider({ children }) {
  const { user } = useAuth();
  const [warehouses, setWarehouses] = useState([]);
  const [selectedWarehouseId, setSelectedWarehouseId] = useState("all");
  const [loading, setLoading] = useState(false);
  const ownerId = supplierOwnerId(user);
  const isBranchManager = user?.role === "supplier" && user.supplier_access_role === "branch_manager";
  const assignedWarehouseId = isBranchManager ? user.assigned_branch_id || "" : "";
  const storageKey = `${STORAGE_PREFIX}${ownerId}`;
  const activeWarehouseId = isBranchManager ? assignedWarehouseId : selectedWarehouseId;

  const refreshWarehouses = useCallback(async () => {
    if (user?.role !== "supplier") {
      setWarehouses([]);
      return [];
    }
    if (user.supplier_access_role === "branch_manager"
      && !(user.operational_permissions || []).includes("inventory")) {
      setWarehouses([]);
      return [];
    }
    setLoading(true);
    try {
      const { data } = await api.get("/supplier/warehouses");
      const rows = Array.isArray(data) ? data : data?.warehouses || [];
      setWarehouses(rows);
      const saved = localStorage.getItem(`${STORAGE_PREFIX}${supplierOwnerId(user)}`);
      if (user.supplier_access_role === "branch_manager") {
        setSelectedWarehouseId(user.assigned_branch_id || "");
      } else if (saved === "all" || rows.some((warehouse) => warehouse.id === saved && warehouse.active !== false)) {
        setSelectedWarehouseId(saved);
      } else {
        setSelectedWarehouseId("all");
        localStorage.setItem(`${STORAGE_PREFIX}${supplierOwnerId(user)}`, "all");
      }
      return rows;
    } finally {
      setLoading(false);
    }
  }, [user?.id, user?.role, user?.supplier_id, user?.supplier_access_role, user?.assigned_branch_id]);

  useEffect(() => {
    if (user?.role !== "supplier") {
      setWarehouses([]);
      setSelectedWarehouseId("all");
      return;
    }
    refreshWarehouses().catch((error) => console.error("Could not load supplier warehouses:", error));
  }, [refreshWarehouses, user?.role]);

  const selectWarehouse = useCallback((warehouseId) => {
    if (isBranchManager) return;
    if (warehouseId !== "all" && !warehouses.some((warehouse) => (
      warehouse.id === warehouseId && warehouse.active !== false
    ))) return;
    setSelectedWarehouseId(warehouseId);
    localStorage.setItem(storageKey, warehouseId);
  }, [isBranchManager, storageKey, warehouses]);

  const activeWarehouse = useMemo(
    () => warehouses.find((warehouse) => warehouse.id === activeWarehouseId) || null,
    [activeWarehouseId, warehouses],
  );

  return (
    <SupplierWarehouseContext.Provider value={{
      warehouses, activeWarehouse, activeWarehouseId, selectWarehouse, refreshWarehouses,
      isBranchManager, loading,
    }}>
      {children}
    </SupplierWarehouseContext.Provider>
  );
}

export function useSupplierWarehouse() {
  return useContext(SupplierWarehouseContext) || {
    warehouses: [], activeWarehouse: null, activeWarehouseId: "all",
    selectWarehouse: () => {}, refreshWarehouses: async () => [],
    isBranchManager: false, loading: false,
  };
}
