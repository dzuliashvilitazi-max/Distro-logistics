import {
  ResponsiveContainer, ComposedChart, BarChart, Bar, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend,
} from "recharts";

const money = (v) => `\u20be${Number(v || 0).toLocaleString(undefined, { maximumFractionDigits: 2 })}`;
const axis = { stroke: "hsl(var(--muted-foreground))", fontSize: 12 };
const tooltipStyle = {
  backgroundColor: "hsl(var(--card))", border: "1px solid hsl(var(--border))", borderRadius: 8,
};

export function ChartCard({ title, testid, children }) {
  return (
    <div className="rounded-xl border border-border bg-card p-4" data-testid={testid}>
      <h3 className="mb-3 text-sm font-semibold">{title}</h3>
      <div className="h-72">{children}</div>
    </div>
  );
}

export function SummaryCard({ label, value, hint }) {
  return (
    <div className="rounded-xl border border-border bg-card p-4">
      <p className="text-xs uppercase tracking-wider text-muted-foreground">{label}</p>
      <p className="mt-1 text-2xl font-bold tracking-tight">{value}</p>
      {hint && <p className="mt-1 text-xs text-muted-foreground">{hint}</p>}
    </div>
  );
}

export function RevenueChart({ data }) {
  return (
    <ResponsiveContainer width="100%" height="100%">
      <ComposedChart data={data}>
        <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
        <XAxis
          dataKey="month"
          tickFormatter={(value) => value.length === 10 ? value.slice(8, 10) + "." + value.slice(5, 7) : value}
          {...axis}
        />
        <YAxis yAxisId="gmv" {...axis} />
        <YAxis yAxisId="fee" orientation="right" {...axis} />
        <Tooltip contentStyle={tooltipStyle} formatter={(v) => money(v)} labelFormatter={(value) => value} />
        <Legend />
        <Bar yAxisId="gmv" dataKey="gmv" name="GMV" fill="#6366f1" radius={[4, 4, 0, 0]} />
        <Line yAxisId="fee" type="monotone" dataKey="revenue" name="Platform revenue" stroke="#10b981" strokeWidth={2} dot />
      </ComposedChart>
    </ResponsiveContainer>
  );
}

export function UserGrowthChart({ data }) {
  return (
    <ResponsiveContainer width="100%" height="100%">
      <ComposedChart data={data}>
        <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
        <XAxis dataKey="month" {...axis} />
        <YAxis allowDecimals={false} {...axis} />
        <Tooltip contentStyle={tooltipStyle} />
        <Legend />
        <Line type="monotone" dataKey="new_distributors" name="Distributors" stroke="#f59e0b" strokeWidth={2} />
        <Line type="monotone" dataKey="new_stores" name="Stores / HoReCa" stroke="#3b82f6" strokeWidth={2} />
      </ComposedChart>
    </ResponsiveContainer>
  );
}

export function OrdersChart({ data }) {
  return (
    <ResponsiveContainer width="100%" height="100%">
      <BarChart data={data}>
        <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
        <XAxis dataKey="month" {...axis} />
        <YAxis allowDecimals={false} {...axis} />
        <Tooltip contentStyle={tooltipStyle} />
        <Legend />
        <Bar dataKey="delivered" name="Delivered" fill="#10b981" />
        <Bar dataKey="in_progress" name="In progress" fill="#f59e0b" />
        <Bar dataKey="cancelled" name="Cancelled" fill="#ef4444" />
      </BarChart>
    </ResponsiveContainer>
  );
}

export { money };
