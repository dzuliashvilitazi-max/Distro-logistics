import { Navigate } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";
import { Loader2 } from "lucide-react";

export function ProtectedRoute({
  children, roles, storeOwnerOnly = false, storePermission, supplierOwnerOnly = false, supplierPermission,
}) {
  const { user, loading } = useAuth();
  if (loading)
    return (
      <div className="flex h-screen items-center justify-center bg-background">
        <Loader2 className="h-8 w-8 animate-spin text-primary" />
      </div>
    );
  if (!user) return <Navigate to="/login" replace />;
  if (roles && !roles.includes(user.role)) return <Navigate to="/" replace />;
  if (storeOwnerOnly && user.role === "retailer" && (user.store_access_role || "global_admin") !== "global_admin")
    return <Navigate to="/orders" replace />;
  if (storePermission && user.role === "retailer"
    && (user.store_access_role || "global_admin") !== "global_admin"
    && user.permissions?.[storePermission] !== true)
    return <Navigate to="/orders" replace />;
  if (supplierOwnerOnly && user.role === "supplier" && (user.supplier_access_role || "global_admin") !== "global_admin")
    return <Navigate to="/supplier" replace />;
  if (supplierPermission && user.role === "supplier" && user.supplier_access_role === "branch_manager") {
    const permissions = new Set(user.operational_permissions || []);
    const aliases = {
      routes: ["routes", "deliveries"],
      drivers: ["drivers", "deliveries"],
    };
    if (!(aliases[supplierPermission] || [supplierPermission]).some((permission) => permissions.has(permission)))
      return <Navigate to="/profile" replace />;
  }
  return children;
}
