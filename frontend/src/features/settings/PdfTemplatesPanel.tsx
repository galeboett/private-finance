import { ScanText, Trash2 } from "lucide-react";
import { api, useApiMutation, useApiQuery } from "../../api/hooks";

type PdfTemplate = {
  id: number;
  institution: string;
  account_id: number | null;
  field: "balance" | "statement_date" | "account_last4";
  page_number: number;
  anchor_text: string | null;
  confirmations: number;
};

export function PdfTemplatesPanel({ csrf }: { csrf: string }) {
  const templates = useApiQuery<PdfTemplate[]>(["imports", "pdf-templates"], "/api/pdf-templates");
  const remove = useApiMutation(
    (id: number) => api<{ operation_id: string }>(`/api/pdf-templates/${id}`, { method: "DELETE", headers: { "x-csrf-token": csrf } }),
    { onSuccess: () => void templates.refetch() },
  );

  return (
    <section className="pdfTemplatesPanel">
      <div><strong><ScanText size={16} />Taught PDF regions</strong><span>Re-teach a field from a pending statement to replace it. Deleting returns that field to safe regex/manual review.</span></div>
      {templates.isLoading ? <p className="emptyText">Loading taught regions…</p> : null}
      {templates.data?.map((template) => (
        <div className="pdfTemplateRow" key={template.id}>
          <span><strong>{template.institution} · {template.field.replace("_", " ")}</strong><small>Page {template.page_number} · {template.anchor_text ? `Anchor: ${template.anchor_text}` : "Absolute region"} · {template.confirmations} clean confirmation{template.confirmations === 1 ? "" : "s"}</small></span>
          <button type="button" className="dangerTextButton" disabled={remove.isPending} onClick={() => { if (window.confirm("Delete this taught PDF region?")) remove.mutate(template.id); }}><Trash2 size={14} />Delete</button>
        </div>
      ))}
      {!templates.isLoading && templates.data?.length === 0 ? <p className="emptyText">No PDF regions have been taught yet.</p> : null}
    </section>
  );
}
