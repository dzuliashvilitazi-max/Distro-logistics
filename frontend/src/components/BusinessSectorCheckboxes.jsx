import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import { useI18n } from "@/context/I18nContext";

const sectors = [
  "grocery",
  "zoo",
  "household",
  "laundry",
  "restaurant_cafe_bar",
  "hotel_hostel",
  "office_company",
  "other",
];

export function BusinessSectorCheckboxes({ value = [], onChange, idPrefix = "sector" }) {
  const { t } = useI18n();

  const toggle = (sector, checked) => {
    onChange(checked ? [...new Set([...value, sector])] : value.filter((item) => item !== sector));
  };

  return (
    <section className="rounded-lg border border-border p-4" data-testid="business-sector-checkboxes">
      <Label className="text-sm font-semibold">{t("auth.servedSectors")}</Label>
      <div className="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-2">
        {sectors.map((sector) => (
          <div key={sector} className="flex items-center gap-2">
            <Checkbox
              id={`${idPrefix}-${sector}`}
              checked={value.includes(sector)}
              onCheckedChange={(checked) => toggle(sector, checked === true)}
              data-testid={`business-sector-${sector}`}
            />
            <Label htmlFor={`${idPrefix}-${sector}`} className="font-normal">{t(`est.${sector}`)}</Label>
          </div>
        ))}
      </div>
    </section>
  );
}
