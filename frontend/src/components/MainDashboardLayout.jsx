import { useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { useI18n } from "@/context/I18nContext";
import { toast } from "sonner";
import {
  ArrowDownRight, ArrowRight, ArrowUpRight, Bell, Boxes, ClipboardList,
  PackageCheck, TrendingUp,
} from "lucide-react";
import { cn } from "@/lib/utils";

function DashboardCard({ to, icon: Icon, label, value, detail, tone, children, testid }) {
  const content = (
    <>
      <div className="flex items-start justify-between gap-4">
        <div className={cn("flex h-11 w-11 items-center justify-center rounded-lg", tone)}>
          <Icon className="h-5 w-5" />
        </div>
        <ArrowUpRight className="h-4 w-4 text-muted-foreground transition-transform duration-200 group-hover:-translate-y-0.5 group-hover:translate-x-0.5 group-hover:text-highlight" />
      </div>
      <p className="mt-6 text-xs font-semibold uppercase tracking-[0.16em] text-muted-foreground">{label}</p>
      <p className="mt-2 text-3xl font-bold tracking-tight text-foreground sm:text-4xl">{value}</p>
      <p className="mt-2 text-sm text-muted-foreground">{detail}</p>
      {children}
    </>
  );
  const classes = "group flex min-h-56 flex-col rounded-lg border border-border bg-card p-5 transition-colors duration-200 hover:border-highlight/70 sm:p-6";

  if (!to) {
    return <article data-testid={testid} className={classes}>{content}</article>;
  }
  return <Link to={to} data-testid={testid} className={classes}>{content}</Link>;
}

function NotificationPanel({ role }) {
  const { t, lang } = useI18n();
  const navigate = useNavigate();
  const [notifications, setNotifications] = useState([]);
  const loadFailed = useRef(false);
  const unread = notifications.filter((notification) => !notification.read).length;

  useEffect(() => {
    let active = true;
    const load = () => api.get("/notifications").then(({ data }) => {
      if (!active) return;
      setNotifications(data.slice(0, 8));
      loadFailed.current = false;
    }).catch((error) => {
      if (!active || loadFailed.current) return;
      console.error("Could not load dashboard notifications:", error);
      loadFailed.current = true;
      toast.error(t("dashboard.notificationsLoadError"));
    });
    load();
    const timer = setInterval(load, 15000);
    return () => {
      active = false;
      clearInterval(timer);
    };
  }, [t]);

  const destination = (notification) => {
    if (["negotiation_request", "negotiation_counter", "negotiation_rejected", "negotiation_accepted"].includes(notification.type)
      && notification.negotiation_id) {
      const path = role === "supplier" ? "/supplier/price-negotiations" : "/store/price-negotiations";
      return `${path}?negotiation_id=${encodeURIComponent(notification.negotiation_id)}`;
    }
    const distributorId = notification.distributor_id || notification.distributorId;
    const productId = notification.product_id || notification.productId;
    if (notification.type === "product_offer" && role === "retailer"
      && distributorId && productId) {
      return `/catalog?distributor_id=${encodeURIComponent(distributorId)}&product_id=${encodeURIComponent(productId)}`;
    }
    if (notification.type === "connection_approved" && role === "retailer") {
      return "/store/distributors";
    }
    if (notification.type === "connection_request" && role === "supplier") {
      return "/distributor/stores";
    }
    if (notification.order_id) {
      const path = role === "supplier" ? "/supplier/orders" : role === "admin" ? "/admin/orders" : "/orders";
      return `${path}?order=${encodeURIComponent(notification.order_id)}`;
    }
    if (notification.invoice_id && role === "supplier") {
      return `/supplier/invoices?invoice=${encodeURIComponent(notification.invoice_id)}`;
    }
    if (notification.type === "approval" && role === "admin") return "/admin/users";
    if (notification.type === "message") return "/messages";
    if (notification.type === "account") return "/profile";
    return role === "supplier" ? "/supplier/orders" : role === "admin" ? "/admin/orders" : "/orders";
  };

  const openNotification = async (notification) => {
    if (!notification.read) {
      try {
        await api.post(`/notifications/${encodeURIComponent(notification.id)}/read`);
        setNotifications((current) => current.map((item) => (
          item.id === notification.id ? { ...item, read: true } : item
        )));
      } catch (error) {
        console.error("Could not mark dashboard notification as read:", error);
        toast.error(t("notifications.readError"));
      }
    }
    navigate(destination(notification));
  };

  return (
    <section className="rounded-lg border border-border bg-card p-5 transition-colors duration-200 hover:border-highlight/50 sm:p-6" data-testid="dashboard-notifications">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.16em] text-highlight">{t("dashboard.activity")}</p>
          <h2 className="mt-1 flex items-center gap-2 text-lg font-semibold text-foreground">
            <Bell className="h-4 w-4 text-highlight" />
            {t("notifications.title")}
          </h2>
        </div>
        {unread > 0 && (
          <span className="inline-flex items-center gap-1.5 rounded-full border border-highlight/30 bg-highlight/10 px-3 py-1 text-xs font-semibold text-highlight">
            <span className="h-1.5 w-1.5 rounded-full bg-highlight" />
            {unread} {t("notifications.unread")}
          </span>
        )}
      </div>
      <hr className="my-4" />
      {notifications.length === 0 ? (
        <p className="py-4 text-center text-sm text-muted-foreground">{t("notifications.empty")}</p>
      ) : (
        <div className="divide-y divide-border">
          {notifications.slice(0, 5).map((notification) => (
            <button
              key={notification.id}
              type="button"
              data-testid={`dashboard-notification-${notification.id}`}
              onClick={() => openNotification(notification)}
              className={cn(
                "flex w-full items-start gap-3 rounded-md px-3 py-3 text-left transition-colors duration-200 hover:bg-secondary/70",
                !notification.read && "bg-highlight/5"
              )}
            >
              <span className={cn("mt-1.5 h-2 w-2 shrink-0 rounded-full", notification.read ? "bg-transparent" : "bg-highlight")} />
              <span className="min-w-0 flex-1">
                <span className={cn("block text-sm leading-relaxed", notification.read ? "text-muted-foreground" : "font-medium text-foreground")}>
                  {notification.text}
                </span>
                <span className="mt-1 block text-xs text-muted-foreground">
                  {new Date(notification.created_at).toLocaleString(lang === "ka" ? "ka-GE" : lang)}
                </span>
              </span>
              <ArrowRight className="mt-1 h-4 w-4 shrink-0 text-muted-foreground" />
            </button>
          ))}
        </div>
      )}
      <div className="mt-3 flex justify-end">
        <Link to="/supplier/orders" className="inline-flex items-center gap-1 text-sm font-medium text-highlight transition-colors hover:text-foreground">
          {t("dashboard.viewOrders")} <ArrowRight className="h-4 w-4" />
        </Link>
      </div>
    </section>
  );
}

export function MainDashboardLayout({ analytics }) {
  const { t, lang } = useI18n();
  const { user } = useAuth();
  const stockWarning = analytics.low_stock.length;
  const maxSales = Math.max(...analytics.series.map((day) => day.sales), 1);

  return (
    <div className="space-y-6" data-testid="main-dashboard">
      <header className="flex flex-col gap-3 border-b border-border pb-5 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className="font-mono text-[11px] font-semibold uppercase tracking-[0.2em] text-highlight">
            Distro Logistics / {t("dashboard.workspace")}
          </p>
          <h1 className="mt-2 text-2xl font-bold tracking-tight text-foreground sm:text-3xl">{t("sup.title")}</h1>
          <p className="mt-1 text-sm text-muted-foreground">{t("dashboard.welcomeBack")}, {user.business_name || user.name}</p>
        </div>
        <p className="font-mono text-xs text-muted-foreground">
          {new Date().toLocaleDateString(lang === "ka" ? "ka-GE" : lang, { weekday: "long", day: "numeric", month: "long" })}
        </p>
      </header>

      <main className="space-y-6">
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          <DashboardCard
            to="/supplier/orders"
            icon={ClipboardList}
            label={t("dashboard.orders")}
            value={analytics.active_orders}
            detail={`${analytics.total_orders} ${t("dashboard.ordersTotal")}`}
            tone="bg-processing/10 text-processing"
            testid="dashboard-orders-card"
          >
            <span className="mt-5 inline-flex w-fit items-center rounded-full border border-processing/30 bg-processing/10 px-2.5 py-1 text-xs font-medium text-processing">
              {analytics.active_orders} {t("dashboard.activeOrders")}
            </span>
          </DashboardCard>

          <DashboardCard
            to="/supplier/inventory"
            icon={Boxes}
            label={t("dashboard.stock")}
            value={analytics.product_count}
            detail={t("dashboard.stockItems")}
            tone="bg-highlight/10 text-highlight"
            testid="dashboard-stock-card"
          >
            <span className={cn(
              "mt-5 inline-flex w-fit items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium",
              stockWarning > 0 ? "border-processing/30 bg-processing/10 text-processing" : "border-delivered/30 bg-delivered/10 text-delivered"
            )}>
              <PackageCheck className="h-3.5 w-3.5" />
              {stockWarning > 0 ? `${stockWarning} ${t("dashboard.lowStock")}` : t("dashboard.stockHealthy")}
            </span>
          </DashboardCard>

          <DashboardCard
            to="/supplier#analytics"
            icon={TrendingUp}
            label={t("dashboard.analytics")}
            value={`₾${analytics.revenue.toLocaleString()}`}
            detail={t("dashboard.totalRevenue")}
            tone="bg-delivered/15 text-delivered"
            testid="dashboard-analytics-card"
          >
            <div className="mt-5 flex h-10 items-end gap-1.5" aria-label={t("sup.salesLast7")}>
              {analytics.series.map((day) => (
                <span
                  key={day.day}
                  title={`${day.day}: ₾${day.sales}`}
                  className="flex-1 rounded-t-sm bg-highlight/70 transition-colors duration-200 group-hover:bg-highlight"
                  style={{ height: `${Math.max(10, (day.sales / maxSales) * 100)}%` }}
                />
              ))}
            </div>
            <span className="mt-2 flex items-center gap-1 text-xs text-muted-foreground">
              <ArrowDownRight className="h-3.5 w-3.5 text-delivered" />
              {t("dashboard.today")}: ₾{analytics.daily.toLocaleString()}
            </span>
          </DashboardCard>
        </div>
        <NotificationPanel role={user.role} />
      </main>
    </div>
  );
}
