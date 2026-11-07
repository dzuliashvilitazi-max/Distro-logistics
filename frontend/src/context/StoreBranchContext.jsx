import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";

const StoreBranchContext = createContext(null);
const ACTIVE_BRANCH_KEY = "distro_active_branch";

export function StoreBranchProvider({ children }) {
  const { user } = useAuth();
  const [branches, setBranches] = useState([]);
  const [activeBranchId, setActiveBranchId] = useState("");
  const selectedBranchId = user?.role === "retailer"
    && (user.store_access_role || "global_admin") !== "global_admin"
    ? user.assigned_branch_id || ""
    : activeBranchId;

  const refreshBranches = useCallback(async (preferredBranchId = "") => {
    if (user?.role !== "retailer") {
      setBranches([]);
      return [];
    }
    const { data } = await api.get("/store/branches");
    setBranches(data);
    const saved = localStorage.getItem(ACTIVE_BRANCH_KEY);
    const activeBranches = data.filter((branch) => branch.active !== false);
    const nextId = activeBranches.some((branch) => branch.id === preferredBranchId)
      ? preferredBranchId
      : activeBranches.some((branch) => branch.id === saved)
        ? saved
        : activeBranches.find((branch) => branch.is_default)?.id || activeBranches[0]?.id || "";
    setActiveBranchId(nextId);
    if (nextId) localStorage.setItem(ACTIVE_BRANCH_KEY, nextId);
    return data;
  }, [user?.id, user?.role]);

  useEffect(() => {
    if (user?.role !== "retailer") return;
    refreshBranches().catch((error) => console.error("Could not load store branches:", error));
  }, [refreshBranches, user?.role]);

  const activeBranch = useMemo(
    () => branches.find((branch) => branch.id === selectedBranchId) || branches[0] || null,
    [branches, selectedBranchId],
  );

  const selectBranch = useCallback((branchId) => {
    if (!branches.some((branch) => branch.id === branchId && branch.active !== false)) return;
    setActiveBranchId(branchId);
    localStorage.setItem(ACTIVE_BRANCH_KEY, branchId);
    window.dispatchEvent(new CustomEvent("distro-store-branch-changed", { detail: { branchId } }));
  }, [branches]);

  return (
    <StoreBranchContext.Provider value={{ branches, activeBranch, activeBranchId: selectedBranchId, selectBranch, refreshBranches }}>
      {children}
    </StoreBranchContext.Provider>
  );
}

export function useStoreBranch() {
  return useContext(StoreBranchContext) || {
    branches: [], activeBranch: null, activeBranchId: "", selectBranch: () => {}, refreshBranches: async () => [],
  };
}
