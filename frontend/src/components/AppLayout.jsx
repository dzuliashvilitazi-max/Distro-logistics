import { lazy, Suspense, useEffect, useRef, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";
import { useTheme } from "@/context/ThemeContext";
import { useI18n } from "@/context/I18nContext";
import { useCart } from "@/context/CartContext";
import { useStoreBranch } from "@/context/StoreBranchContext";
import { useSupplierWarehouse } from "@/context/SupplierWarehouseContext";
import { api } from "@/lib/api";
import { LogoAvatar } from "@/components/BusinessLogo";
import { LANGUAGES } from "@/lib/i18n";
import { usePwaInstall } from "@/lib/pwa";
import { enablePush, preparePushSubscription, syncExistingPushSubscription, subscribeToPush } from "@/lib/push";
import {
  Truck, Package, LayoutDashboard, ShoppingCart, ClipboardList, Boxes, RotateCcw,
  Users, MessageSquare, Settings, Bell, Moon, Sun, LogOut, Menu, BarChart3, Globe, FileText, Wallet, Route, Store, ChartNoAxesCombined, Cable, Tags, Download, LifeBuoy, Megaphone, CheckCheck, Landmark,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetTitle, SheetTrigger } from "@/components/ui/sheet";
import { toast } from "sonner";
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel,
  DropdownMenuSeparator, DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

const AddressSelector = lazy(() => import("@/components/AddressSelector"));

const NAV = {
  retailer: [
    { to: "/catalog", key: "catalog", testid: "nav-catalog", icon: Package },
    { to: "/distributors", key: "myDistributors", testid: "nav-my-distributors", icon: Users },
    { to: "/price-requests", key: "priceNegotiations", testid: "nav-store-negotiations", icon: Tags },
    { to: "/cart", key: "cart", testid: "nav-cart", icon: ShoppingCart },
    { to: "/orders", key: "myOrders", testid: "nav-my-orders", icon: ClipboardList },
    { to: "/completed-orders", label: "დასრულებული შეკვეთები", testid: "nav-completed-orders", icon: ClipboardList },
    { to: "/purchase-analytics", label: "შესყიდვების ანალიტიკა", testid: "nav-purchase-analytics", icon: BarChart3 },
    { to: "/purchase-invoices", label: "ინვოისები", testid: "nav-purchase-invoices", icon: FileText },
    { to: "/returns", key: "returns", testid: "nav-retailer-returns", icon: RotateCcw },
    { to: "/finances", key: "finance", testid: "nav-store-finance", icon: Wallet },
    { to: "/branches", key: "branches", testid: "nav-store-branches", icon: Store },
    { to: "/employees", key: "staff", testid: "nav-store-staff", icon: Users },
    { to: "/chat", key: "messages", testid: "nav-messages", icon: MessageSquare },
    { to: "/profile", key: "profile", testid: "nav-profile", icon: Settings },
    { to: "/support", label: "მხარდაჭერა", testid: "nav-support", icon: LifeBuoy },
    { to: "/analytics", key: "analytics", testid: "nav-store-analytics", icon: ChartNoAxesCombined, retailOnly: true },
    { to: "/profit-calculator", key: "pricing", testid: "nav-store-pricing", icon: Tags, retailOnly: true },
    { to: "/pos", key: "integrations", testid: "nav-store-integrations", icon: Cable, retailOnly: true },
  ],
  supplier: [
    { to: "/supplier", key: "dashboard", testid: "nav-dashboard", icon: LayoutDashboard },
    { to: "/supplier/inventory", key: "inventory", testid: "nav-inventory", icon: Boxes },
    { to: "/supplier/orders", key: "orders", testid: "nav-orders", icon: ClipboardList },
    { to: "/distributor/completed-orders", label: "დასრულებული შეკვეთები", testid: "nav-completed-orders", icon: CheckCheck },
    { to: "/distributor/analytics", label: "ანალიტიკა", testid: "nav-distributor-analytics", icon: ChartNoAxesCombined },
    { to: "/distributor/invoices-finance", label: "ინვოისები და ფინანსები", testid: "nav-invoices-finance", icon: Landmark },
    { to: "/supplier/returns", key: "returns", testid: "nav-supplier-returns", icon: RotateCcw },
    { to: "/distributor/stores", key: "myStores", testid: "nav-my-stores", icon: Store },
    { to: "/distributor/promotions", label: "აქციები", testid: "nav-promotions", icon: Megaphone },
    { to: "/supplier/store-discovery", key: "storeDiscovery", testid: "nav-store-discovery", icon: Globe },
    { to: "/supplier/price-negotiations", key: "priceNegotiations", testid: "nav-supplier-negotiations", icon: Tags },
    { to: "/supplier/routes", key: "routes", testid: "nav-routes", icon: Route },
    { to: "/supplier/drivers", key: "drivers", testid: "nav-drivers", icon: Truck },
    { to: "/supplier/invoices", key: "invoices", testid: "nav-invoices", icon: FileText },
    { to: "/supplier/finance", key: "finance", testid: "nav-supplier-finance", icon: Wallet },
    { to: "/supplier/warehouses", key: "supplierWarehouses", testid: "nav-supplier-warehouses", icon: Store },
    { to: "/supplier/staff", key: "supplierStaff", testid: "nav-supplier-staff", icon: Users },
    { to: "/messages", key: "messages", testid: "nav-messages", icon: MessageSquare },
    { to: "/profile", key: "profile", testid: "nav-profile", icon: Settings },
    { to: "/support", label: "მხარდაჭერა", testid: "nav-support", icon: LifeBuoy },
  ],
  admin: [
    { to: "/admin", key: "overview", testid: "nav-overview", icon: BarChart3 },
    { to: "/admin/orders", key: "orders", testid: "nav-orders", icon: ClipboardList },
    { to: "/admin/financials", key: "financials", testid: "nav-financials", icon: Wallet },
    { to: "/admin/analytics", label: "ანალიტიკა", testid: "nav-admin-analytics", icon: ChartNoAxesCombined },
    { to: "/admin/users", key: "users", testid: "nav-users", icon: Users },
    { to: "/admin/settings", key: "settings", testid: "nav-settings", icon: Settings },
    { to: "/admin/product-images", label: "პროდუქტის სურათები", testid: "nav-product-images", icon: Package },
    { to: "/admin/support", label: "მხარდაჭერა", testid: "nav-admin-support", icon: LifeBuoy },
    { to: "/admin/broadcast", label: "შეტყობინებები", testid: "nav-admin-broadcast", icon: Megaphone },
    { to: "/messages", key: "messages", testid: "nav-messages", icon: MessageSquare },
    { to: "/profile", key: "profile", testid: "nav-profile", icon: Settings },
    { to: "/support", label: "მხარდაჭერა", testid: "nav-support", icon: LifeBuoy },
  ],
};

function LanguageSwitcher() {
  const { lang, setLang } = useI18n();
  const current = LANGUAGES.find((l) => l.code === lang) || LANGUAGES[1];
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="icon" className="relative" data-testid="language-switcher">
          <Globe className="h-5 w-5" />
          <span className="absolute -bottom-0.5 right-0 rounded bg-primary px-0.5 text-[8px] font-bold text-primary-foreground">{current.short}</span>
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-40 bg-popover">
        {LANGUAGES.map((l) => (
          <DropdownMenuItem key={l.code} onClick={() => setLang(l.code)} data-testid={`lang-option-${l.code}`} className={l.code === lang ? "bg-primary/10 font-semibold text-primary" : ""}>
            {l.label}
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

const NOTIFICATION_SOUND = new Audio("data:audio/wav;base64,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");

function playNotificationSound() {
  const sound = NOTIFICATION_SOUND.cloneNode();
  sound.volume = 0.55;
  const playback = sound.play();
  if (playback) playback.catch((error) => console.warn("Notification sound could not play:", error));
}

function pushFailureDetails(error, stage) {
  return {
    stage,
    name: error?.name || "Error",
    message: error?.message || String(error),
    code: error?.code ?? null,
    status: error?.response?.status ?? null,
  };
}

function NotificationBell({ onPermissionChange, onPushContextReady, requiresHomeScreen, pushPermission, pushContextReady }) {
  const [items, setItems] = useState([]);
  const seenIds = useRef(null);
  const loadFailed = useRef(false);
  const navigate = useNavigate();
  const { user } = useAuth();
  const { t } = useI18n();
  const unread = items.filter((n) => !n.read).length;

  const load = () => api.get("/notifications").then((r) => {
    const nextItems = r.data;
    const nextIds = new Set(nextItems.map((n) => n.id || `${n.created_at}:${n.text}`));
    if (seenIds.current) {
      nextItems.forEach((n) => {
        const id = n.id || `${n.created_at}:${n.text}`;
        if (!seenIds.current.has(id)) {
          playNotificationSound();
          if (n.type === "order") showOrderNotification(n);
        }
      });
    }
    seenIds.current = nextIds;
    loadFailed.current = false;
    setItems(nextItems);
  }).catch((error) => {
    if (!loadFailed.current) {
      console.error("Could not load notifications:", error);
      toast.error(t("notifications.loadError"));
      loadFailed.current = true;
    }
  });
  useEffect(() => {
    load();
    const t = setInterval(load, 6000);
    return () => clearInterval(t);
  }, []);

  // Preload the worker/key; never create a new subscription from an effect.
  useEffect(() => {
    if (!("Notification" in window)) return undefined;
    onPermissionChange(Notification.permission);
    preparePushSubscription()
      .then((context) => {
        onPushContextReady(Boolean(context));
        if (Notification.permission === "granted" && context?.subscription) return syncExistingPushSubscription();
        return false;
      })
      .catch((error) => {
        onPushContextReady(false);
        console.error("Push preparation failed:", error);
      });
    return undefined;
  }, [user?.id, onPermissionChange, onPushContextReady]);

  // Tapping a push notification while the app is already open routes inside the running app.
  useEffect(() => {
    if (!("serviceWorker" in navigator)) return undefined;
    const onMessage = (event) => {
      if (event.data?.type !== "PUSH_NAVIGATE" || !event.data.url) return;
      const target = new URL(event.data.url, window.location.origin);
      if (target.origin === window.location.origin) navigate(`${target.pathname}${target.search}`);
    };
    navigator.serviceWorker.addEventListener("message", onMessage);
    return () => navigator.serviceWorker.removeEventListener("message", onMessage);
  }, [navigate]);

  const markRead = (notification) => {
    api.post(`/notifications/${encodeURIComponent(notification.id)}/read`).then(() => {
      setItems((current) => current.map((item) => item.id === notification.id ? { ...item, read: true } : item));
    }).catch((error) => {
      console.error("Could not mark notifications as read:", error);
      toast.error(t("notifications.readError"));
    });
  };

  const markAllRead = () => {
    api.post("/notifications/read").then(load).catch((error) => {
      console.error("Could not mark notifications as read:", error);
      toast.error(t("notifications.readError"));
    });
  };

  const requestBrowserNotifications = () => {
    if (requiresHomeScreen) {
      toast.info(t("pwa.iosHint"));
      return;
    }
    if (!("Notification" in window)) {
      toast.error(t("notifications.unsupported"));
      return;
    }
    if (Notification.permission === "granted") {
      subscribeToPush().catch((error) => {
        console.error("Could not refresh push subscription:", error);
        toast.error(t("notifications.permissionError"));
      });
      return;
    }
    if (Notification.permission === "denied") {
      toast.error(t("notifications.permissionDenied"));
      return;
    }
    const permissionRequest = enablePush();
    permissionRequest.then((permission) => {
      onPermissionChange(permission);
      if (permission === "granted") toast.success(t("notifications.permissionGranted"));
      else if (permission === "denied") toast.error(t("notifications.permissionDenied"));
    }).catch((error) => {
      const details = pushFailureDetails(error, "notification-bell-click");
      console.error("Browser notification permission/push setup failed", details);
      toast.error(`${t("notifications.permissionError")} (${details.name}: ${details.message})`);
    });
  };

  const notificationPath = (notification) => {
    if (["negotiation_request", "negotiation_counter", "negotiation_rejected", "negotiation_accepted"].includes(notification.type)
      && notification.negotiation_id) {
      const path = user.role === "supplier" ? "/supplier/price-negotiations" : "/store/price-negotiations";
      return `${path}?negotiation_id=${encodeURIComponent(notification.negotiation_id)}`;
    }
    const distributorId = notification.distributor_id || notification.distributorId;
    const productId = notification.product_id || notification.productId;
    if (["product_offer", "promo", "promo_expiring"].includes(notification.type) && user.role === "retailer"
      && distributorId && productId) {
      return `/catalog?distributor_id=${encodeURIComponent(distributorId)}&product_id=${encodeURIComponent(productId)}`;
    }
    if (notification.type === "connection_approved" && user.role === "retailer") {
      return "/store/distributors";
    }
    if (notification.type === "connection_request" && user.role === "supplier") {
      return "/distributor/stores";
    }
    if (notification.order_id) {
      const path = user.role === "supplier" ? "/supplier/orders"
        : user.role === "admin" ? "/admin/orders" : "/orders";
      return `${path}?order=${encodeURIComponent(notification.order_id)}`;
    }
    if (notification.invoice_id && user.role === "supplier") {
      return `/supplier/invoices?invoice=${encodeURIComponent(notification.invoice_id)}`;
    }
    if (notification.type === "approval" && user.role === "admin") return "/admin/users";
    if (notification.type === "message") return "/messages";
    if (notification.type === "account") return "/profile";
    if (notification.type === "billing" && user.role === "supplier") return "/supplier/invoices";
    return user.role === "supplier" ? "/supplier/orders" : user.role === "admin" ? "/admin/orders" : "/orders";
  };

  const openNotification = (notification) => {
    markRead(notification);
    navigate(notificationPath(notification));
  };

  const showOrderNotification = (notification) => {
    if (!("Notification" in window) || Notification.permission !== "granted") return;
    const nativeNotification = new Notification("მოგივიდა ახალი შეკვეთა!", {
      body: notification.text,
      tag: `n-${notification.id}`,
      icon: "/favicon.ico",
    });
    nativeNotification.onclick = () => {
      window.focus();
      openNotification(notification);
      nativeNotification.close();
    };
  };

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="icon" className="relative" data-testid="notification-bell"
          aria-label={t("notifications.title")} title={t("notifications.title")}
          disabled={!requiresHomeScreen && pushPermission === "default" && pushContextReady === null}
          onClick={requestBrowserNotifications}>
          <Bell className="h-5 w-5" />
          {unread > 0 && (
            <span data-testid="notification-count" className="absolute -right-1 -top-1 flex h-5 min-w-5 items-center justify-center rounded-full border-2 border-background bg-rose-600 px-1 text-[10px] font-bold text-white">
              {unread > 99 ? "99+" : unread}
            </span>
          )}
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-80 bg-popover">
        <DropdownMenuLabel className="flex items-center justify-between">
          <span>{t("notifications.title")}</span>
          {unread > 0 && <button type="button" className="text-xs font-medium text-primary hover:underline" onClick={markAllRead}>{t("notifications.markAllRead")}</button>}
        </DropdownMenuLabel>
        <DropdownMenuSeparator />
        {items.length === 0 && <div className="px-3 py-6 text-center text-sm text-muted-foreground">{t("notifications.empty")}</div>}
        <div className="max-h-80 overflow-y-auto">
          {items.slice(0, 15).map((n) => (
            <DropdownMenuItem key={n.id} onSelect={() => openNotification(n)} data-testid="notification-item"
              className={cn(
                "block cursor-pointer border-b border-border/50 px-3 py-2.5 text-sm last:border-0",
                !n.read && "border-l-2 border-l-primary bg-primary/10"
              )}>
              <div className="flex items-start justify-between gap-2">
                <p className={cn("text-foreground", !n.read && "font-semibold")}>{n.text}</p>
                {!n.read && <span className="shrink-0 rounded-full bg-primary px-2 py-0.5 text-[10px] font-bold text-primary-foreground">{t("notifications.unread")}</span>}
              </div>
              <p className="mt-0.5 font-mono text-[11px] text-muted-foreground">{new Date(n.created_at).toLocaleString()}</p>
            </DropdownMenuItem>
          ))}
        </div>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

export function AppLayout({ children }) {
  const { user, logout } = useAuth();
  const { theme, toggle } = useTheme();
  const { t } = useI18n();
  const pwa = usePwaInstall();
  const { count = 0 } = useCart() || {};
  const { activeBranch } = useStoreBranch();
  const { warehouses, activeWarehouseId, selectWarehouse } = useSupplierWarehouse();
  const location = useLocation();
  const navigate = useNavigate();
  const [mobileOpen, setMobileOpen] = useState(false);
  const [pushPermission, setPushPermission] = useState(() =>
    typeof Notification === "undefined" ? "unsupported" : Notification.permission,
  );
  const [pushContextReady, setPushContextReady] = useState(null);
  const [pushBusy, setPushBusy] = useState(false);
  const requiresHomeScreen = pwa.isIos && !pwa.installed;
  const pushSupported = requiresHomeScreen || (
    typeof Notification !== "undefined" && "serviceWorker" in navigator && "PushManager" in window
  );

  useEffect(() => {
    const desktop = window.matchMedia("(min-width: 1024px)");
    const closeOnDesktop = (event) => { if (event.matches) setMobileOpen(false); };
    desktop.addEventListener("change", closeOnDesktop);
    return () => desktop.removeEventListener("change", closeOnDesktop);
  }, []);

  const showHomeScreenHint = () => toast.info(t("pwa.iosHint"));

  const requestPushPermission = () => {
    let permissionRequest;
    try {
      permissionRequest = Notification.requestPermission();
    } catch (error) {
      const details = pushFailureDetails(error, "requestPermission");
      console.error("Push permission request failed synchronously", details);
      toast.error(`${t("notifications.permissionError")} (${details.name}: ${details.message})`);
      return;
    }
    setPushBusy(true);
    let stage = "requestPermission";
    permissionRequest.then((permission) => {
      setPushPermission(permission);
      if (permission === "granted") {
        stage = "enablePush/subscribe";
        return enablePush().then(() => {
          toast.success(t("notifications.permissionGranted"));
        });
      }
      if (permission === "denied") toast.error(t("notifications.permissionDenied"));
    }).catch((error) => {
      const details = pushFailureDetails(error, stage);
      console.error("Push permission flow failed", details);
      setPushPermission(typeof Notification === "undefined" ? "unsupported" : Notification.permission);
      toast.error(`${t("notifications.permissionError")} (${details.name}: ${details.message})`);
    }).finally(() => {
      setPushBusy(false);
    });
  };
  const isStoreOwner = user.role === "retailer" && (user.store_access_role || "global_admin") === "global_admin";
  const isSupplierOwner = user.role === "supplier" && (user.supplier_access_role || "global_admin") === "global_admin";
  const supplierPermissions = new Set(user.operational_permissions || []);
  const isRetail = user?.entityGroup === "RETAIL" || user?.is_retail === true;
  const nav = (NAV[user.role] || []).filter((item) => {
    if (item.retailOnly && !isRetail) return false;
    if (user.role === "retailer" && !isStoreOwner) {
      if (["/branches", "/employees"].includes(item.to)) return false;
      const required = {
        "/finances": "canViewFinancials", "/analytics": "canViewFinancials",
        "/completed-orders": "canViewFinancials",
        "/purchase-analytics": "canViewFinancials",
        "/purchase-invoices": "canViewFinancials",
        "/profit-calculator": "canChangePrices", "/pos": "canManageApi",
      }[item.to];
      if (required && user.permissions?.[required] !== true) return false;
    }
    if (user.role !== "supplier" || isSupplierOwner) return true;
    if (item.to === "/supplier") return supplierPermissions.has("orders");
    if (["/supplier/invoices", "/supplier/warehouses", "/supplier/staff", "/distributor/stores", "/distributor/promotions", "/supplier/store-discovery",
      "/supplier/price-negotiations"].includes(item.to)) return false;
    if (item.to === "/supplier/inventory") return supplierPermissions.has("inventory");
    if (item.to === "/supplier/orders") return supplierPermissions.has("orders");
    if (item.to === "/supplier/routes") return supplierPermissions.has("routes") || supplierPermissions.has("deliveries");
    if (item.to === "/supplier/drivers") return supplierPermissions.has("drivers") || supplierPermissions.has("deliveries");
    if (item.to === "/supplier/finance") return supplierPermissions.has("finance");
    if (["/distributor/completed-orders", "/distributor/analytics"].includes(item.to)) return supplierPermissions.has("orders");
    if (item.to === "/distributor/invoices-finance") return supplierPermissions.has("finance");
    return true;
  });

  const roleLabel = t(`roles.${user.role === "supplier"
    ? `supplier_${user.supplier_access_role || "global_admin"}`
    : user.role}`);

  const SideNav = () => (
    <nav className="flex flex-col gap-1 p-3">
      {nav.map((item) => {
        const active = location.pathname === item.to;
        const Icon = item.icon;
        return (
          <Link
            key={item.to}
            to={item.to}
            onClick={() => setMobileOpen(false)}
            data-testid={item.testid}
            className={cn(
              "flex items-center gap-3 rounded-xl border border-transparent px-3 py-2 text-sm font-medium transition-all duration-200",
              active ? "border-primary/20 bg-primary/10 text-primary" : "text-muted-foreground hover:bg-secondary/80 hover:text-foreground"
            )}
          >
            <Icon className="h-4.5 w-4.5" style={{ width: 18, height: 18 }} />
            <span>{item.label || t(`nav.${item.key}`)}</span>
            {item.to === "/cart" && count > 0 && (
              <span className="ml-auto rounded-full bg-processing/15 px-2 py-0.5 text-xs font-bold text-processing">{count}</span>
            )}
          </Link>
        );
      })}
    </nav>
  );

  return (
    <div className="min-h-screen bg-background">
      <header className="sticky top-0 z-40 border-b border-border/80 bg-background/90 backdrop-blur-xl">
        <div className="mx-auto flex min-h-16 max-w-screen-2xl flex-wrap items-center gap-x-3 gap-y-2 px-3 py-2 sm:flex-nowrap sm:justify-between sm:px-4 lg:px-8">
          <div className="flex min-w-0 flex-1 items-center gap-2 sm:flex-none sm:gap-3">
            <Sheet open={mobileOpen} onOpenChange={setMobileOpen}>
              <SheetTrigger asChild>
                <Button variant="ghost" size="icon" className="lg:hidden" aria-label="Menu" data-testid="mobile-menu-toggle">
                  <Menu className="h-5 w-5" />
                </Button>
              </SheetTrigger>
              <SheetContent side="left" className="flex w-[min(20rem,85vw)] flex-col overflow-y-auto p-0 lg:hidden" aria-describedby={undefined} data-testid="mobile-sidebar">
                <SheetTitle className="border-b border-border px-6 py-5 text-left">Distro Logistics</SheetTitle>
                <SideNav />
              </SheetContent>
            </Sheet>
            <Link to="/" className="flex min-w-0 items-center gap-2 sm:gap-2.5">
              <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-primary">
                <Truck className="h-5 w-5 text-primary-foreground" />
              </div>
              <div className="min-w-0 leading-tight">
                <p className="truncate whitespace-nowrap text-sm font-extrabold tracking-tight sm:text-base">Distro<span className="text-primary">Logistics</span></p>
                <p className="truncate whitespace-nowrap font-mono text-[10px] uppercase tracking-wider text-muted-foreground">B2B Distribution</p>
              </div>
            </Link>
          </div>
          <div className="ml-auto flex max-w-full shrink-0 flex-wrap items-center justify-end gap-0.5 sm:gap-1.5">
            {user.role === "supplier" && isSupplierOwner && warehouses.some((warehouse) => warehouse.active !== false) && (
              <select
                aria-label={t("warehouse.switch")}
                data-testid="supplier-warehouse-switcher"
                value={activeWarehouseId}
                onChange={(event) => selectWarehouse(event.target.value)}
                className="h-9 max-w-40 rounded-md border border-border bg-background px-2 text-xs font-medium text-foreground sm:max-w-52 sm:text-sm"
              >
                <option value="all">{t("warehouse.all")}</option>
                {warehouses.filter((warehouse) => warehouse.active !== false).map((warehouse) => (
                  <option key={warehouse.id} value={warehouse.id}>{warehouse.name}</option>
                ))}
              </select>
            )}
            {user.role === "retailer" && activeBranch && <Suspense fallback={null}><AddressSelector canManage={isStoreOwner} /></Suspense>}
            <span className="hidden rounded-full border border-primary/30 bg-primary/10 px-3 py-1 font-mono text-[11px] font-semibold uppercase tracking-wider text-primary sm:inline-flex" data-testid="role-badge">
              {user.role === "retailer" ? (user.roleName || t(`roles.${user.store_access_role || "global_admin"}`)) : roleLabel}
            </span>
            <Button variant="ghost" size="icon" onClick={toggle} data-testid="theme-toggle">
              {theme === "dark" ? <Sun className="h-5 w-5" /> : <Moon className="h-5 w-5" />}
            </Button>
            <LanguageSwitcher />
            <NotificationBell
              onPermissionChange={setPushPermission}
              onPushContextReady={setPushContextReady}
              requiresHomeScreen={requiresHomeScreen}
              pushPermission={pushPermission}
              pushContextReady={pushContextReady}
            />
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="ghost" className="gap-2 px-2" data-testid="user-menu">
                  <LogoAvatar entity={user} className="h-8 w-8 rounded-full text-sm" />
                  <span className="hidden max-w-32 truncate text-sm font-medium sm:inline">{user.business_name}</span>
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="w-56 bg-popover">
                <DropdownMenuLabel className="truncate">{user.email}</DropdownMenuLabel>
                <DropdownMenuSeparator />
                <DropdownMenuItem onClick={() => navigate("/profile")} data-testid="menu-profile">
                  <Settings className="mr-2 h-4 w-4" /> {t("common.profileSettings")}
                </DropdownMenuItem>
                {pwa.showInstall && (
                  <DropdownMenuItem
                    onClick={async () => { if ((await pwa.install()) === "manual") toast.info(t("pwa.iosHint")); }}
                    data-testid="install-app-btn">
                    <Download className="mr-2 h-4 w-4" /> {t("pwa.install")}
                  </DropdownMenuItem>
                )}
                <DropdownMenuItem onClick={() => { logout(); navigate("/login"); }} data-testid="logout-btn">
                  <LogOut className="mr-2 h-4 w-4" /> {t("common.signOut")}
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        </div>
      </header>

      <div className="flex">
        <aside className="hidden w-64 shrink-0 border-r border-border/80 bg-card/30 lg:block">
          <div className="sticky top-16 max-h-[calc(100vh-4rem)] overflow-y-auto"><SideNav /></div>
        </aside>
        <main className="min-w-0 flex-1">
          <div key={user.role === "supplier" ? activeWarehouseId : undefined} className="mx-auto max-w-screen-2xl px-4 py-6 sm:px-6 lg:px-8 lg:py-9">
            {pushPermission === "default" && pushSupported && (
              <section className="mb-5 flex flex-wrap items-center justify-between gap-3 rounded-lg border border-border bg-card px-4 py-3" data-testid="push-permission-prompt">
                <div className="min-w-0">
                  <p className="text-sm font-semibold">{t("notifications.pushPromptTitle")}</p>
                  <p className="mt-0.5 text-sm text-muted-foreground">
                    {requiresHomeScreen ? t("notifications.iosInstallPrompt") : t("notifications.pushPrompt")}
                  </p>
                </div>
                <Button type="button" onClick={requiresHomeScreen ? showHomeScreenHint : requestPushPermission}
                  disabled={pushBusy || (!requiresHomeScreen && pushContextReady === null)}
                  data-testid="enable-push-button">
                  <Bell className="mr-2 h-4 w-4" />
                  {requiresHomeScreen ? t("pwa.install") : t("notifications.enable")}
                </Button>
              </section>
            )}
            {children}
          </div>
        </main>
      </div>
    </div>
  );
}
