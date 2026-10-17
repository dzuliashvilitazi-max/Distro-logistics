import { useEffect, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";
import { useTheme } from "@/context/ThemeContext";
import { useCart } from "@/context/CartContext";
import { api } from "@/lib/api";
import {
  Truck, Package, LayoutDashboard, ShoppingCart, ClipboardList, Boxes,
  Users, MessageSquare, Settings, Bell, Moon, Sun, LogOut, Menu, X, BarChart3,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel,
  DropdownMenuSeparator, DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

const NAV = {
  retailer: [
    { to: "/catalog", label: "Catalog", icon: Package },
    { to: "/cart", label: "Cart", icon: ShoppingCart },
    { to: "/orders", label: "My Orders", icon: ClipboardList },
    { to: "/messages", label: "Messages", icon: MessageSquare },
    { to: "/profile", label: "Profile", icon: Settings },
  ],
  supplier: [
    { to: "/supplier", label: "Dashboard", icon: LayoutDashboard },
    { to: "/supplier/inventory", label: "Inventory", icon: Boxes },
    { to: "/supplier/orders", label: "Orders", icon: ClipboardList },
    { to: "/messages", label: "Messages", icon: MessageSquare },
    { to: "/profile", label: "Profile", icon: Settings },
  ],
  admin: [
    { to: "/admin", label: "Overview", icon: BarChart3 },
    { to: "/admin/users", label: "Users", icon: Users },
    { to: "/messages", label: "Messages", icon: MessageSquare },
    { to: "/profile", label: "Profile", icon: Settings },
  ],
};

function NotificationBell() {
  const [items, setItems] = useState([]);
  const unread = items.filter((n) => !n.read).length;

  const load = () => api.get("/notifications").then((r) => setItems(r.data)).catch(() => {});
  useEffect(() => {
    load();
    const t = setInterval(load, 6000);
    return () => clearInterval(t);
  }, []);

  const markRead = () => { api.post("/notifications/read").then(load); };

  return (
    <DropdownMenu onOpenChange={(o) => o && unread && markRead()}>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="icon" className="relative" data-testid="notification-bell">
          <Bell className="h-5 w-5" />
          {unread > 0 && (
            <span data-testid="notification-count" className="absolute -right-0.5 -top-0.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-primary px-1 text-[10px] font-bold text-primary-foreground">
              {unread}
            </span>
          )}
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-80 bg-popover">
        <DropdownMenuLabel>Notifications</DropdownMenuLabel>
        <DropdownMenuSeparator />
        {items.length === 0 && <div className="px-3 py-6 text-center text-sm text-muted-foreground">No notifications yet</div>}
        <div className="max-h-80 overflow-y-auto">
          {items.slice(0, 15).map((n) => (
            <div key={n.id} data-testid="notification-item" className={cn("border-b border-border/50 px-3 py-2.5 text-sm last:border-0", !n.read && "bg-primary/5")}>
              <p className="text-foreground">{n.text}</p>
              <p className="mt-0.5 font-mono text-[11px] text-muted-foreground">{new Date(n.created_at).toLocaleString()}</p>
            </div>
          ))}
        </div>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

export function AppLayout({ children }) {
  const { user, logout } = useAuth();
  const { theme, toggle } = useTheme();
  const { count } = useCart();
  const location = useLocation();
  const navigate = useNavigate();
  const [mobileOpen, setMobileOpen] = useState(false);
  const nav = NAV[user.role] || [];

  const roleLabel = { retailer: "Retailer", supplier: "Supplier", admin: "Admin" }[user.role];

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
            data-testid={`nav-${item.label.toLowerCase().replace(/\s/g, "-")}`}
            className={cn(
              "flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition-colors duration-200",
              active ? "bg-primary text-primary-foreground shadow-sm" : "text-muted-foreground hover:bg-secondary hover:text-foreground"
            )}
          >
            <Icon className="h-4.5 w-4.5" style={{ width: 18, height: 18 }} />
            <span>{item.label}</span>
            {item.to === "/cart" && count > 0 && (
              <span className="ml-auto rounded-full bg-primary-foreground/20 px-1.5 text-xs font-bold">{count}</span>
            )}
          </Link>
        );
      })}
    </nav>
  );

  return (
    <div className="min-h-screen bg-background">
      <header className="sticky top-0 z-40 border-b border-border bg-background/80 backdrop-blur-md">
        <div className="flex items-center justify-between px-4 py-3 lg:px-8">
          <div className="flex items-center gap-3">
            <Button variant="ghost" size="icon" className="lg:hidden" onClick={() => setMobileOpen((v) => !v)} data-testid="mobile-menu-toggle">
              {mobileOpen ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
            </Button>
            <Link to="/" className="flex items-center gap-2.5">
              <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-primary">
                <Truck className="h-5 w-5 text-primary-foreground" />
              </div>
              <div className="leading-tight">
                <p className="text-base font-extrabold tracking-tight">Distro<span className="text-primary">Logistics</span></p>
                <p className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">B2B Distribution</p>
              </div>
            </Link>
          </div>
          <div className="flex items-center gap-1.5">
            <span className="hidden rounded-full border border-primary/30 bg-primary/10 px-3 py-1 font-mono text-[11px] font-semibold uppercase tracking-wider text-primary sm:inline-flex" data-testid="role-badge">
              {roleLabel}
            </span>
            <Button variant="ghost" size="icon" onClick={toggle} data-testid="theme-toggle">
              {theme === "dark" ? <Sun className="h-5 w-5" /> : <Moon className="h-5 w-5" />}
            </Button>
            <NotificationBell />
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="ghost" className="gap-2 px-2" data-testid="user-menu">
                  <div className="flex h-8 w-8 items-center justify-center rounded-full bg-secondary text-sm font-bold text-foreground">
                    {user.business_name?.[0]?.toUpperCase() || "U"}
                  </div>
                  <span className="hidden max-w-32 truncate text-sm font-medium sm:inline">{user.business_name}</span>
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="w-56 bg-popover">
                <DropdownMenuLabel className="truncate">{user.email}</DropdownMenuLabel>
                <DropdownMenuSeparator />
                <DropdownMenuItem onClick={() => navigate("/profile")} data-testid="menu-profile">
                  <Settings className="mr-2 h-4 w-4" /> Profile Settings
                </DropdownMenuItem>
                <DropdownMenuItem onClick={() => { logout(); navigate("/login"); }} data-testid="logout-btn">
                  <LogOut className="mr-2 h-4 w-4" /> Sign out
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        </div>
      </header>

      <div className="flex">
        <aside className="hidden w-60 shrink-0 border-r border-border lg:block">
          <div className="sticky top-16"><SideNav /></div>
        </aside>
        {mobileOpen && (
          <div className="fixed inset-0 z-30 lg:hidden">
            <div className="absolute inset-0 bg-black/50" onClick={() => setMobileOpen(false)} />
            <aside className="absolute left-0 top-14 h-full w-64 border-r border-border bg-background"><SideNav /></aside>
          </div>
        )}
        <main className="min-w-0 flex-1">
          <div className="mx-auto max-w-7xl px-4 py-6 sm:px-6 lg:px-8 lg:py-8">{children}</div>
        </main>
      </div>
    </div>
  );
}
