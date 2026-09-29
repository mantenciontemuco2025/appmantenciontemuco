"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { PlantAreaOption } from "@/lib/types";
import { WORK_ORDER_AREAS } from "@/lib/work-order-areas";

const fixedOptions: PlantAreaOption[] = WORK_ORDER_AREAS.map((name, index) => ({
  id: -(index + 1),
  name,
}));

function mergeOptions(catalog: PlantAreaOption[]) {
  const merged = new Map<string, PlantAreaOption>();
  [...fixedOptions, ...catalog].forEach((area) => {
    const name = area.name.trim();
    if (name) merged.set(name.toLocaleUpperCase("es-CL"), { ...area, name });
  });
  return Array.from(merged.values()).sort((left, right) => left.name.localeCompare(right.name, "es"));
}

export function usePlantAreaOptions() {
  const [options, setOptions] = useState<PlantAreaOption[]>(fixedOptions);

  useEffect(() => {
    api.getCached<PlantAreaOption[]>("/api/catalogs/plant-areas", 5 * 60 * 1000)
      .then((catalog) => setOptions(mergeOptions(catalog)))
      .catch(() => setOptions(fixedOptions));
  }, []);

  return options;
}
