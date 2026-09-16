"use client";

import { useMemo, useState } from "react";
import { Check, ChevronDown, Search } from "lucide-react";
import type { SelectOption } from "@/components/ui/select";

interface SearchableSelectProps {
  label: string;
  options: SelectOption[];
  value: string;
  onValueChange: (value: string) => void;
  placeholder?: string;
  searchPlaceholder?: string;
  emptyMessage?: string;
  disabled?: boolean;
}

function normalize(value: string) {
  return value.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLocaleLowerCase();
}

export function SearchableSelect({
  label,
  options,
  value,
  onValueChange,
  placeholder = "Seleccionar...",
  searchPlaceholder = "Escribe para buscar...",
  emptyMessage = "No se encontraron resultados.",
  disabled = false,
}: SearchableSelectProps) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [activeIndex, setActiveIndex] = useState(0);
  const selected = options.find((option) => option.value === value);
  const filteredOptions = useMemo(() => {
    const normalizedQuery = normalize(query.trim());
    if (!normalizedQuery) return options;
    return options.filter((option) => normalize(option.label).includes(normalizedQuery));
  }, [options, query]);

  function choose(option: SelectOption) {
    onValueChange(option.value);
    setQuery("");
    setOpen(false);
  }

  const listId = `search-options-${label.replace(/\W+/g, "-").toLowerCase()}`;

  return (
    <div className="space-y-1.5">
      <label className="block text-sm font-medium text-foreground">{label}</label>
      <div className="relative">
        <div className="relative">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <input
            role="combobox"
            aria-label={label}
            aria-autocomplete="list"
            aria-expanded={open}
            aria-controls={listId}
            autoComplete="off"
            disabled={disabled}
            placeholder={open ? searchPlaceholder : placeholder}
            value={open ? query : selected?.label || ""}
            onFocus={() => {
              setQuery("");
              setActiveIndex(0);
              setOpen(true);
            }}
            onChange={(event) => {
              setQuery(event.target.value);
              setActiveIndex(0);
              setOpen(true);
            }}
            onBlur={() => {
              setOpen(false);
              setQuery("");
            }}
            onKeyDown={(event) => {
              if (event.key === "ArrowDown") {
                event.preventDefault();
                setOpen(true);
                setActiveIndex((index) => Math.min(index + 1, filteredOptions.length - 1));
              } else if (event.key === "ArrowUp") {
                event.preventDefault();
                setActiveIndex((index) => Math.max(index - 1, 0));
              } else if (event.key === "Enter" && open && filteredOptions[activeIndex]) {
                event.preventDefault();
                choose(filteredOptions[activeIndex]);
              } else if (event.key === "Escape") {
                setOpen(false);
                setQuery("");
              }
            }}
            className="flex h-12 w-full rounded-md border border-input bg-background py-2 pl-10 pr-10 text-base ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
          />
          <ChevronDown className="pointer-events-none absolute right-3 top-1/2 h-4 w-4 -translate-y-1/2 opacity-50" />
        </div>
        {open && (
          <div id={listId} role="listbox" className="absolute z-50 mt-1 max-h-60 w-full overflow-y-auto rounded-md border border-slate-200 bg-white p-1 text-foreground shadow-xl">
            {filteredOptions.length ? filteredOptions.map((option, index) => (
              <button
                key={option.value}
                type="button"
                role="option"
                aria-selected={option.value === value}
                onMouseDown={(event) => event.preventDefault()}
                onMouseEnter={() => setActiveIndex(index)}
                onClick={() => choose(option)}
                className={`flex min-h-10 w-full items-center justify-between gap-2 rounded-sm bg-white px-3 py-2 text-left text-sm text-slate-900 hover:bg-blue-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-primary ${activeIndex === index ? "bg-blue-50" : ""}`}
              >
                <span>{option.label}</span>
                {option.value === value && <Check className="h-4 w-4 shrink-0 text-primary" />}
              </button>
            )) : (
              <p className="px-3 py-2 text-sm text-muted-foreground">{emptyMessage}</p>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
