import type { SignDecision } from "./ImportReview";

export type ImportSignConvention = "auto" | "preset" | "reverse";

type Props = {
  value: ImportSignConvention;
  decision?: SignDecision | null;
  disabled?: boolean;
  onChange: (value: ImportSignConvention) => void;
  onRemember: (value: "preset" | "reverse") => void;
};

function reversedAmount(value?: string) {
  if (!value) return "—";
  return value.startsWith("-") ? value.slice(1) : `-${value}`;
}

export function SignConventionPrompt({ value, decision, disabled, onChange, onRemember }: Props) {
  return (
    <div className="manualOverride signConventionPrompt">
      <label>Amount signs</label>
      <select value={value} onChange={(event) => onChange(event.target.value as ImportSignConvention)} disabled={disabled}>
        <option value="auto">Use saved convention or detect automatically</option>
        <option value="preset">Use detected signs for this file</option>
        <option value="reverse">Reverse detected signs for this file</option>
      </select>
      {decision?.using_saved_profile && !decision.requires_confirmation ? <small>Using your saved sign convention for this account and CSV source.</small> : null}
      {decision?.requires_confirmation ? (
        <div className="inboxScanIssues" role="alert">
          <strong>This file’s signs look different from the expected convention.</strong>
          <span>Check the examples, then choose the interpretation that makes charges negative and refunds or deposits positive.</span>
          <div className="inboxPreviewRows">
            {decision.heuristic.examples.map((example, index) => (
              <div key={`${example.transaction_date ?? "row"}-${index}`}>
                <span>{example.transaction_date ?? `Example ${index + 1}`}</span>
                <strong>{example.description ?? "Imported transaction"}</strong>
                <span>Detected {example.amount ?? "—"} · Reversed {reversedAmount(example.amount)}</span>
              </div>
            ))}
          </div>
          <div className="buttonRow">
            <button className="secondaryButton" type="button" onClick={() => onRemember("preset")}>Detected signs are right — remember</button>
            <button className="primaryButton" type="button" onClick={() => onRemember("reverse")}>Reverse signs — remember</button>
          </div>
        </div>
      ) : <small>Charges should be negative; refunds, deposits, and income should be positive.</small>}
    </div>
  );
}
