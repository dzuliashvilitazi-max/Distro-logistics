import { lazy, Suspense } from "react";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { AuthProvider, useAuth } from "@/context/AuthContext";
import { ThemeProvider } from "@/context/ThemeContext";
import { I18nProvider } from "@/context/I18nContext";
import { CartProvider } from "@/context/CartContext";
import { StoreBranchProvider } from "@/context/StoreBranchContext";
import { SupplierWarehouseProvider } from "@/context/SupplierWarehouseContext";
import { ProtectedRoute } from "@/components/ProtectedRoute";
import { AppLayout } from "@/components/AppLayout";
import { Toaster } from "@/components/ui/sonner";
import { Loader2 } from "lucide-react";

import Landing from "@/pages/Landing";
import Auth from "@/pages/Auth";

// Route pages load on demand so the first paint ships only the shell, auth and landing code.
const lazyPage = (loader, name) => lazy(() => loader().then((m) => ({ default: name ? m[name] : m.default })));
const ForgotPassword = lazyPage(() => import("@/pages/PasswordRecovery"), "ForgotPassword");
const ResetPassword = lazyPage(() => import("@/pages/PasswordRecovery"), "ResetPassword");
const Catalog = lazyPage(() => import("@/pages/retailer/Catalog"));
const Cart = lazyPage(() => import("@/pages/retailer/Cart"));
const Orders = lazyPage(() => import("@/pages/retailer/Orders"));
const CompletedOrders = lazyPage(() => import("@/pages/retailer/PurchasePanels"), "CompletedOrders");
const CompletedOrderDetail = lazyPage(() => import("@/pages/retailer/PurchasePanels"), "CompletedOrderDetail");
const PurchaseAnalytics = lazyPage(() => import("@/pages/retailer/PurchasePanels"), "PurchaseAnalytics");
const PurchaseInvoices = lazyPage(() => import("@/pages/retailer/PurchasePanels"), "PurchaseInvoices");
const StoreFinance = lazyPage(() => import("@/pages/retailer/StoreFinance"));
const StoreBranches = lazyPage(() => import("@/pages/retailer/StoreBranches"));
const StoreIntegrations = lazyPage(() => import("@/pages/retailer/StoreIntegrations"));
const StoreAnalytics = lazyPage(() => import("@/pages/retailer/StoreAnalytics"));
const StorePricing = lazyPage(() => import("@/pages/retailer/StorePricing"));
const StoreStaff = lazyPage(() => import("@/pages/retailer/StoreStaff"));
const StoreDistributors = lazyPage(() => import("@/pages/retailer/StoreDistributors"));
const SupplierStores = lazyPage(() => import("@/pages/supplier/SupplierStores"));
const SupplierPromotions = lazyPage(() => import("@/pages/supplier/SupplierPromotions"));
const StoreDiscovery = lazyPage(() => import("@/pages/supplier/StoreDiscovery"));
const SupplierPriceNegotiations = lazyPage(() => import("@/pages/supplier/PriceNegotiations"));
const StorePriceNegotiations = lazyPage(() => import("@/pages/retailer/PriceNegotiations"));
const SupplierDashboard = lazyPage(() => import("@/pages/supplier/SupplierDashboard"));
const Inventory = lazyPage(() => import("@/pages/supplier/Inventory"));
const SupplierOrders = lazyPage(() => import("@/pages/supplier/SupplierOrders"));
const DeliveryRoute = lazyPage(() => import("@/pages/supplier/DeliveryRoute"));
const DriverRoute = lazyPage(() => import("@/pages/DriverRoute"));
const SupplierDrivers = lazyPage(() => import("@/pages/supplier/SupplierDrivers"));
const AdminDashboard = lazyPage(() => import("@/pages/admin/AdminDashboard"));
const AdminUsers = lazyPage(() => import("@/pages/admin/AdminUsers"));
const AdminOrders = lazyPage(() => import("@/pages/admin/AdminOrders"));
const AdminSettings = lazyPage(() => import("@/pages/admin/AdminSettings"));
const AdminFinancials = lazyPage(() => import("@/pages/admin/AdminFinancials"));
const AdminAnalytics = lazyPage(() => import("@/pages/admin/AdminAnalytics"));
const AdminSupport = lazyPage(() => import("@/pages/admin/AdminSupport"));
const AdminBroadcast = lazyPage(() => import("@/pages/admin/AdminBroadcast"));
const Support = lazyPage(() => import("@/pages/Support"));
const SupplierInvoices = lazyPage(() => import("@/pages/supplier/SupplierInvoices"));
const ReturnsDashboard = lazyPage(() => import("@/pages/ReturnsDashboard"));
const SupplierFinance = lazyPage(() => import("@/pages/supplier/SupplierFinance"));
const SupplierWarehouses = lazyPage(() => import("@/pages/supplier/SupplierWarehouses"));
const SupplierStaff = lazyPage(() => import("@/pages/supplier/SupplierStaff"));
const Messages = lazyPage(() => import("@/pages/Messages"));
const Profile = lazyPage(() => import("@/pages/Profile"));
const TermsOfService = lazyPage(() => import("@/pages/TermsOfService"));
const PrivacyPolicy = lazyPage(() => import("@/pages/PrivacyPolicy"));

function RoleHome() {
  const { user, loading } = useAuth();
  if (loading) return <div className="flex h-screen items-center justify-center bg-background"><Loader2 className="h-8 w-8 animate-spin text-primary" /></div>;
  if (!user) return <Landing />;
  if (user.role === "supplier") return <Navigate to="/supplier" replace />;
  if (user.role === "admin") return <Navigate to="/admin" replace />;
  if (user.role === "retailer" && (user.store_access_role || "global_admin") !== "global_admin") return <Navigate to="/orders" replace />;
  return <Navigate to="/store" replace />;
}

function Page({ roles, storeOwnerOnly = false, storePermission, supplierOwnerOnly = false, supplierPermission, children }) {
  return <ProtectedRoute
    roles={roles}
    storeOwnerOnly={storeOwnerOnly}
    storePermission={storePermission}
    supplierOwnerOnly={supplierOwnerOnly}
    supplierPermission={supplierPermission}
  ><AppLayout>{children}</AppLayout></ProtectedRoute>;
}

function App() {
  return (
    <ThemeProvider>
      <AuthProvider>
        <I18nProvider>
        <StoreBranchProvider>
        <SupplierWarehouseProvider>
        <CartProvider>
          <BrowserRouter>
            <Suspense fallback={<div className="flex h-screen items-center justify-center bg-background"><Loader2 className="h-8 w-8 animate-spin text-primary" /></div>}>
            <Routes>
              <Route path="/" element={<RoleHome />} />
              <Route path="/login" element={<Auth mode="login" />} />
              <Route path="/register" element={<Auth mode="register" />} />
              <Route path="/forgot-password" element={<ForgotPassword />} />
              <Route path="/reset-password" element={<ResetPassword />} />
              <Route path="/terms" element={<TermsOfService />} />
              <Route path="/privacy" element={<PrivacyPolicy />} />
              <Route path="/driver/routes/:token" element={<Suspense fallback={<div className="h-screen animate-pulse bg-secondary" />}><DriverRoute /></Suspense>} />
              <Route path="/m/driver-route" element={<Suspense fallback={<div className="h-screen animate-pulse bg-secondary" />}><DriverRoute /></Suspense>} />

              <Route path="/catalog" element={<Page roles={["retailer"]}><Catalog /></Page>} />
              <Route path="/cart" element={<Page roles={["retailer"]}><Cart /></Page>} />
              <Route path="/orders" element={<Page roles={["retailer"]}><Orders /></Page>} />
              <Route path="/completed-orders" element={<Page roles={["retailer"]} storePermission="canViewFinancials"><CompletedOrders /></Page>} />
              <Route path="/completed-orders/:orderId" element={<Page roles={["retailer"]} storePermission="canViewFinancials"><CompletedOrderDetail /></Page>} />
              <Route path="/purchase-analytics" element={<Page roles={["retailer"]} storePermission="canViewFinancials"><PurchaseAnalytics /></Page>} />
              <Route path="/purchase-invoices" element={<Page roles={["retailer"]} storePermission="canViewFinancials"><PurchaseInvoices /></Page>} />
              <Route path="/purchase-orders/:orderId" element={<Page roles={["retailer"]} storePermission="canViewFinancials"><CompletedOrderDetail completedOnly={false} /></Page>} />
              <Route path="/returns" element={<Page roles={["retailer"]}><ReturnsDashboard /></Page>} />
              <Route path="/store" element={<Page roles={["retailer"]} storePermission="canViewFinancials"><StoreFinance /></Page>} />
              <Route path="/store/finance" element={<Page roles={["retailer"]} storePermission="canViewFinancials"><StoreFinance /></Page>} />
              <Route path="/store/branches" element={<Page roles={["retailer"]} storeOwnerOnly><StoreBranches /></Page>} />
              <Route path="/store/staff" element={<Page roles={["retailer"]} storeOwnerOnly><StoreStaff /></Page>} />
              <Route path="/store/integrations" element={<Page roles={["retailer"]} storePermission="canManageApi"><StoreIntegrations /></Page>} />
              <Route path="/store/analytics" element={<Page roles={["retailer"]} storePermission="canViewFinancials"><StoreAnalytics /></Page>} />
              <Route path="/store/pricing" element={<Page roles={["retailer"]} storePermission="canChangePrices"><StorePricing /></Page>} />
              <Route path="/store/distributors" element={<Page roles={["retailer"]}><StoreDistributors /></Page>} />
              <Route path="/store/price-negotiations" element={<Page roles={["retailer"]}><StorePriceNegotiations /></Page>} />
              <Route path="/distributors" element={<Page roles={["retailer"]}><StoreDistributors /></Page>} />
              <Route path="/price-requests" element={<Page roles={["retailer"]}><StorePriceNegotiations /></Page>} />
              <Route path="/finances" element={<Page roles={["retailer"]} storePermission="canViewFinancials"><StoreFinance /></Page>} />
              <Route path="/branches" element={<Page roles={["retailer"]} storeOwnerOnly><StoreBranches /></Page>} />
              <Route path="/employees" element={<Page roles={["retailer"]} storeOwnerOnly><StoreStaff /></Page>} />
              <Route path="/analytics" element={<Page roles={["retailer"]} storePermission="canViewFinancials"><StoreAnalytics /></Page>} />
              <Route path="/profit-calculator" element={<Page roles={["retailer"]} storePermission="canChangePrices"><StorePricing /></Page>} />
              <Route path="/pos" element={<Page roles={["retailer"]} storePermission="canManageApi"><StoreIntegrations /></Page>} />
              <Route path="/distributor/stores" element={<Page roles={["supplier"]} supplierOwnerOnly><SupplierStores /></Page>} />
              <Route path="/distributor/promotions" element={<Page roles={["supplier"]} supplierOwnerOnly><SupplierPromotions /></Page>} />
              <Route path="/supplier/store-discovery" element={<Page roles={["supplier"]} supplierOwnerOnly><StoreDiscovery /></Page>} />
              <Route path="/supplier/price-negotiations" element={<Page roles={["supplier"]} supplierOwnerOnly><SupplierPriceNegotiations /></Page>} />

              <Route path="/supplier" element={<Page roles={["supplier"]} supplierPermission="orders"><SupplierDashboard /></Page>} />
              <Route path="/supplier/inventory" element={<Page roles={["supplier"]} supplierPermission="inventory"><Inventory /></Page>} />
              <Route path="/supplier/orders" element={<Page roles={["supplier"]} supplierPermission="orders"><SupplierOrders /></Page>} />
              <Route path="/supplier/returns" element={<Page roles={["supplier"]} supplierPermission="orders"><ReturnsDashboard /></Page>} />
              <Route path="/supplier/routes" element={<Page roles={["supplier"]} supplierPermission="routes"><Suspense fallback={<div className="h-96 animate-pulse rounded-xl bg-secondary" />}><DeliveryRoute /></Suspense></Page>} />
              <Route path="/supplier/drivers" element={<Page roles={["supplier"]} supplierPermission="drivers"><SupplierDrivers /></Page>} />
              <Route path="/supplier/invoices" element={<Page roles={["supplier"]} supplierOwnerOnly><SupplierInvoices /></Page>} />
              <Route path="/supplier/finance" element={<Page roles={["supplier"]} supplierPermission="finance"><SupplierFinance /></Page>} />
              <Route path="/supplier/warehouses" element={<Page roles={["supplier"]} supplierOwnerOnly><SupplierWarehouses /></Page>} />
              <Route path="/supplier/staff" element={<Page roles={["supplier"]} supplierOwnerOnly><SupplierStaff /></Page>} />

              <Route path="/admin" element={<Page roles={["admin"]}><AdminDashboard /></Page>} />
              <Route path="/admin/orders" element={<Page roles={["admin"]}><AdminOrders /></Page>} />
              <Route path="/admin/users" element={<Page roles={["admin"]}><AdminUsers /></Page>} />
              <Route path="/admin/settings" element={<Page roles={["admin"]}><AdminSettings /></Page>} />
              <Route path="/admin/financials" element={<Page roles={["admin"]}><AdminFinancials /></Page>} />
              <Route path="/admin/analytics" element={<Page roles={["admin"]}><AdminAnalytics /></Page>} />
              <Route path="/admin/support" element={<Page roles={["admin"]}><AdminSupport /></Page>} />
              <Route path="/admin/broadcast" element={<Page roles={["admin"]}><AdminBroadcast /></Page>} />
              <Route path="/support" element={<Page roles={["retailer", "supplier", "admin"]}><Support /></Page>} />

              <Route path="/messages" element={<Page roles={["retailer", "supplier", "admin"]}><Messages /></Page>} />
              <Route path="/chat" element={<Page roles={["retailer", "supplier", "admin"]}><Messages /></Page>} />
              <Route path="/profile" element={<Page roles={["retailer", "supplier", "admin"]}><Profile /></Page>} />
              <Route path="*" element={<Navigate to="/" replace />} />
            </Routes>
            </Suspense>
            <Toaster richColors position="top-right" />
          </BrowserRouter>
        </CartProvider>
        </SupplierWarehouseProvider>
        </StoreBranchProvider>
        </I18nProvider>
      </AuthProvider>
    </ThemeProvider>
  );
}

export default App;
