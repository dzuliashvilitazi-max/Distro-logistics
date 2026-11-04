import { Checkbox } from "@/components/ui/checkbox";
import { useI18n } from "@/context/I18nContext";

export const PERMISSION_FLAGS = [
  "canViewFinancials", "canManageInventory", "canChangePrices", "canAccessPOS", "canManageApi",
  "canManageOrders",
];

export const DEFAULT_PERMISSIONS = {
  canViewFinancials: false, canManageInventory: true, canChangePrices: false,
  canAccessPOS: true, canManageApi: false, canManageOrders: true,
};

export function PermissionMatrix({ value, onChange, idPrefix = "perm" }) {
  const { t } = useI18n();
  return (
    <fieldset className="rounded-lg border border-border p-4" data-testid="permission-matrix">
      <legend className="px-2 text-sm font-semibold">{t("perm.title")}</legend>
      <p className="mb-3 text-xs text-muted-foreground">{t("perm.hint")}</p>
      <div className="grid gap-3 sm:grid-cols-2">
        {PERMISSION_FLAGS.map((flag) => (
          <label key={flag} htmlFor={`${idPrefix}-${flag}`} className="flex cursor-pointer items-start gap-3 rounded-md border border-border p-3 hover:bg-secondary/40">
            <Checkbox
              id={`${idPrefix}-${flag}`}
              checked={value?.[flag] === true}
              onCheckedChange={(checked) => onChange({ ...value, [flag]: checked === true })}
              className="mt-0.5"
            />
            <span>
              <span className="block text-sm font-medium">{t(`perm.${flag}`)}</span>
              <span className="block text-xs text-muted-foreground">{t(`perm.${flag}.desc`)}</span>
            </span>
          </label>
        ))}
      </div>
    </fieldset>
  );
}
