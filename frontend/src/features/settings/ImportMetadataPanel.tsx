import { useApiQuery } from "../../api/hooks";
import { PdfTemplatesPanel } from "./PdfTemplatesPanel";

type ImportMetadata = {
  sign_profiles: Array<{ id: number; account: string; preset_type: string | null; sign_convention: string; decided_by: string }>;
  csv_mappings: Array<{ id: number; account: string; name: string; preset_type: string }>;
  pdf_patterns: Array<{ id: number; institution: string; balance_label: string; date_label: string | null }>;
};

export function ImportMetadataPanel({ csrf }: { csrf: string }) {
  const metadata = useApiQuery<ImportMetadata>(["imports", "metadata"], "/api/settings/import-metadata");
  if (metadata.isLoading) return <p className="emptyText">Loading saved import choices…</p>;
  if (metadata.isError) return <p className="validationError">Saved import choices could not be loaded.</p>;
  const data = metadata.data!;
  return (
    <details className="importMetadataPanel">
      <summary><span><strong>Saved import choices</strong><small>{data.csv_mappings.length} CSV mapping{data.csv_mappings.length === 1 ? "" : "s"} · {data.sign_profiles.length} sign profile{data.sign_profiles.length === 1 ? "" : "s"} · {data.pdf_patterns.length} PDF pattern{data.pdf_patterns.length === 1 ? "" : "s"}</small></span></summary>
      <div className="importMetadataGrid">
        <section><strong>CSV mappings</strong>{data.csv_mappings.map((row) => <div key={row.id}><span>{row.name}</span><small>{row.account} · {row.preset_type}</small></div>)}{data.csv_mappings.length === 0 ? <p className="emptyText">No custom mappings saved.</p> : null}</section>
        <section><strong>Amount signs</strong>{data.sign_profiles.map((row) => <div key={row.id}><span>{row.account}</span><small>{row.preset_type ?? "All presets"} · {row.sign_convention.replaceAll("_", " ")} · {row.decided_by.replaceAll("_", " ")}</small></div>)}{data.sign_profiles.length === 0 ? <p className="emptyText">No sign decisions saved.</p> : null}</section>
        <section><strong>PDF balance patterns</strong>{data.pdf_patterns.map((row) => <div key={row.id}><span>{row.institution}</span><small>{row.balance_label}{row.date_label ? ` · ${row.date_label}` : ""}</small></div>)}{data.pdf_patterns.length === 0 ? <p className="emptyText">No PDF labels learned.</p> : null}</section>
      </div>
      <PdfTemplatesPanel csrf={csrf} />
    </details>
  );
}
