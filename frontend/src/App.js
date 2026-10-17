import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { AuthProvider, useAuth } from "@/context/AuthContext";
import { ThemeProvider } from "@/context/ThemeContext";
import { CartProvider } from "@/context/CartContext";
import { ProtectedRoute } from "@/components/ProtectedRoute";
import { AppLayout } from "@/components/AppLayout";
import { Toaster } from "@/components/ui/sonner";
import { Loader2 } from "lucide-react";

import Landing from "@/pages/Landing";
import Auth from "@/pages/Auth";
import Catalog from "@/pages/retailer/Catalog";
import Cart from "@/pages/retailer/Cart";
import Orders from "@/pages/retailer/Orders";
import SupplierDashboard from "@/pages/supplier/SupplierDashboard";
import Inventory from "@/pages/supplier/Inventory";
import SupplierOrders from "@/pages/supplier/SupplierOrders";
import AdminDashboard from "@/pages/admin/AdminDashboard";
import AdminUsers from "@/pages/admin/AdminUsers";
import Messages from "@/pages/Messages";
import Profile from "@/pages/Profile";

function RoleHome() {
  const { user, loading } = useAuth();
  if (loading) return <div className="flex h-screen items-center justify-center bg-background"><Loader2 className="h-8 w-8 animate-spin text-primary" /></div>;
  if (!user) return <Landing />;
  if (user.role === "supplier") return <Navigate to="/supplier" replace />;
  if (user.role === "admin") return <Navigate to="/admin" replace />;
  return <Navigate to="/catalog" replace />;
}

function Page({ roles, children }) {
  return <ProtectedRoute roles={roles}><AppLayout>{children}</AppLayout></ProtectedRoute>;
}

function App() {
  return (
    <ThemeProvider>
      <AuthProvider>
        <CartProvider>
          <BrowserRouter>
            <Routes>
              <Route path="/" element={<RoleHome />} />
              <Route path="/login" element={<Auth mode="login" />} />
              <Route path="/register" element={<Auth mode="register" />} />

              <Route path="/catalog" element={<Page roles={["retailer"]}><Catalog /></Page>} />
              <Route path="/cart" element={<Page roles={["retailer"]}><Cart /></Page>} />
              <Route path="/orders" element={<Page roles={["retailer"]}><Orders /></Page>} />

              <Route path="/supplier" element={<Page roles={["supplier"]}><SupplierDashboard /></Page>} />
              <Route path="/supplier/inventory" element={<Page roles={["supplier"]}><Inventory /></Page>} />
              <Route path="/supplier/orders" element={<Page roles={["supplier"]}><SupplierOrders /></Page>} />

              <Route path="/admin" element={<Page roles={["admin"]}><AdminDashboard /></Page>} />
              <Route path="/admin/users" element={<Page roles={["admin"]}><AdminUsers /></Page>} />

              <Route path="/messages" element={<Page roles={["retailer", "supplier", "admin"]}><Messages /></Page>} />
              <Route path="/profile" element={<Page roles={["retailer", "supplier", "admin"]}><Profile /></Page>} />
              <Route path="*" element={<Navigate to="/" replace />} />
            </Routes>
            <Toaster richColors position="top-right" />
          </BrowserRouter>
        </CartProvider>
      </AuthProvider>
    </ThemeProvider>
  );
}

export default App;
