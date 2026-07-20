import { useEffect, useMemo, useRef, useState, type PointerEvent } from "react";
import { ChevronLeft, ChevronRight, ScanText, X } from "lucide-react";
import { api } from "../../api/hooks";

type WordBox = { text: string; x0: number; y0: number; x1: number; y1: number };
type Inspection = {
  page_count: number;
  page: number;
  width: number;
  height: number;
  page_image: string | null;
  render_mode: "word_boxes";
  words: WordBox[];
};
type Region = { x0: number; y0: number; x1: number; y1: number };
type Field = "balance" | "statement_date" | "account_last4";

type Props = {
  batchId: number;
  csrf: string;
  onSaved: (message: string) => void;
  onClose: () => void;
};

export function PdfRegionTeacher({ batchId, csrf, onSaved, onClose }: Props) {
  const surfaceRef = useRef<HTMLDivElement>(null);
  const [page, setPage] = useState(1);
  const [inspection, setInspection] = useState<Inspection | null>(null);
  const [field, setField] = useState<Field>("balance");
  const [anchorText, setAnchorText] = useState("");
  const [region, setRegion] = useState<Region | null>(null);
  const [dragStart, setDragStart] = useState<{ x: number; y: number } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    setBusy(true);
    setError("");
    setRegion(null);
    api<Inspection>("/api/imports/pdf/inspect", {
      method: "POST",
      body: JSON.stringify({ staged_batch_id: batchId, page }),
    })
      .then(setInspection)
      .catch((reason) => setError(reason instanceof Error ? reason.message : "The PDF page could not be inspected."))
      .finally(() => setBusy(false));
  }, [batchId, page]);

  const selectedWords = useMemo(() => {
    if (!inspection || !region) return [];
    const ordered = orderRegion(region);
    return inspection.words.filter((word) => {
      const x = (word.x0 + word.x1) / 2;
      const y = (word.y0 + word.y1) / 2;
      return x >= ordered.x0 && x <= ordered.x1 && y >= ordered.y0 && y <= ordered.y1;
    });
  }, [inspection, region]);
  const capturedText = selectedWords
    .slice()
    .sort((left, right) => left.y0 - right.y0 || left.x0 - right.x0)
    .map((word) => word.text)
    .join(" ");

  function point(event: PointerEvent<HTMLDivElement>) {
    const bounds = surfaceRef.current?.getBoundingClientRect();
    if (!bounds) return { x: 0, y: 0 };
    return {
      x: Math.max(0, Math.min(1, (event.clientX - bounds.left) / bounds.width)),
      y: Math.max(0, Math.min(1, (event.clientY - bounds.top) / bounds.height)),
    };
  }

  function beginSelection(event: PointerEvent<HTMLDivElement>) {
    const start = point(event);
    event.currentTarget.setPointerCapture(event.pointerId);
    setDragStart(start);
    setRegion({ x0: start.x, y0: start.y, x1: start.x, y1: start.y });
  }

  function moveSelection(event: PointerEvent<HTMLDivElement>) {
    if (!dragStart) return;
    const current = point(event);
    setRegion({ x0: dragStart.x, y0: dragStart.y, x1: current.x, y1: current.y });
  }

  function finishSelection(event: PointerEvent<HTMLDivElement>) {
    if (!dragStart) return;
    moveSelection(event);
    setDragStart(null);
  }

  async function save() {
    if (!region || !capturedText) {
      setError("Draw a box around the value first.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const ordered = orderRegion(region);
      const result = await api<{ operation_id: string; template: { anchor_text: string | null } }>("/api/pdf-templates", {
        method: "POST",
        headers: { "x-csrf-token": csrf },
        body: JSON.stringify({
          staged_batch_id: batchId,
          field,
          page_number: page,
          ...ordered,
          anchor_text: anchorText.trim() || null,
        }),
      });
      onSaved(`Saved the ${field.replace("_", " ")} region${result.template.anchor_text ? ` anchored to “${result.template.anchor_text}”` : ""}.`);
      setRegion(null);
      setAnchorText("");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "The extraction region could not be saved.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="modalBackdrop pdfTeacherBackdrop" role="presentation">
      <section className="pdfTeacherModal" role="dialog" aria-modal="true" aria-label="Teach PDF extractor">
        <header>
          <div><strong><ScanText size={18} />Teach the extractor</strong><span>Draw a box around a value. The nearest stable label becomes its anchor.</span></div>
          <button type="button" className="iconButton" aria-label="Close PDF teacher" onClick={onClose}><X size={18} /></button>
        </header>
        <div className="pdfTeacherControls">
          <label>Field<select value={field} onChange={(event) => setField(event.target.value as Field)}><option value="balance">Balance</option><option value="statement_date">Statement date</option><option value="account_last4">Account last four</option></select></label>
          <label>Anchor override<input value={anchorText} onChange={(event) => setAnchorText(event.target.value)} placeholder="Optional label text" /></label>
          <div className="pdfPageControls"><button type="button" disabled={page <= 1 || busy} onClick={() => setPage((value) => value - 1)}><ChevronLeft size={16} /></button><span>Page {page} of {inspection?.page_count ?? "…"}</span><button type="button" disabled={!inspection || page >= inspection.page_count || busy} onClick={() => setPage((value) => value + 1)}><ChevronRight size={16} /></button></div>
        </div>
        <div
          ref={surfaceRef}
          className="pdfWordCanvas"
          style={{ aspectRatio: inspection ? `${inspection.width} / ${inspection.height}` : "612 / 792" }}
          onPointerDown={beginSelection}
          onPointerMove={moveSelection}
          onPointerUp={finishSelection}
        >
          {inspection?.words.map((word, index) => <span key={`${index}-${word.text}`} className="pdfWordBox" style={{ left: `${word.x0 * 100}%`, top: `${word.y0 * 100}%`, width: `${(word.x1 - word.x0) * 100}%`, height: `${(word.y1 - word.y0) * 100}%` }}>{word.text}</span>)}
          {region ? <span className="pdfSelectionBox" style={regionStyle(orderRegion(region))} /> : null}
          {busy && !inspection ? <span className="pdfCanvasMessage">Reading page…</span> : null}
        </div>
        <div className="pdfTeacherFeedback">
          <span>Captured text</span>
          <strong>{capturedText || "Draw across the value shown on the page."}</strong>
          {field === "balance" && capturedText && !/^\s*\$?\s*\(?-?[\d,]+\.\d{2}\)?\s*$/.test(capturedText) ? <small className="validationError">This does not look like a currency value yet.</small> : null}
          {error ? <small className="validationError">{error}</small> : null}
        </div>
        <footer><button type="button" className="secondaryButton" onClick={onClose}>Done</button><button type="button" className="primaryButton" disabled={busy || !capturedText} onClick={() => void save()}>{busy ? "Saving…" : "Save region"}</button></footer>
      </section>
    </div>
  );
}

function orderRegion(region: Region): Region {
  return {
    x0: Math.min(region.x0, region.x1),
    y0: Math.min(region.y0, region.y1),
    x1: Math.max(region.x0, region.x1),
    y1: Math.max(region.y0, region.y1),
  };
}

function regionStyle(region: Region) {
  return {
    left: `${region.x0 * 100}%`,
    top: `${region.y0 * 100}%`,
    width: `${(region.x1 - region.x0) * 100}%`,
    height: `${(region.y1 - region.y0) * 100}%`,
  };
}
