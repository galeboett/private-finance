import { Sparkles } from "lucide-react";
import { useEffect, useState } from "react";

type Props = {
  transactionId: number;
  description: string;
  initialMatchText: string;
  typeLabel: string;
  categoryLabel: string;
  disabled?: boolean;
  compact?: boolean;
  onSave: (matchText: string) => Promise<void>;
};

export function SaveRuleControl(props: Props) {
  const [matchText, setMatchText] = useState(props.initialMatchText);
  const [saving, setSaving] = useState(false);

  useEffect(() => setMatchText(props.initialMatchText), [props.initialMatchText, props.transactionId]);

  async function save() {
    const normalized = matchText.trim();
    if (!normalized || props.disabled || saving) return;
    setSaving(true);
    try {
      await props.onSave(normalized);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className={props.compact ? "saveRuleControl compact" : "saveRuleControl"}>
      <div>
        <strong>Always categorize similar descriptions</strong>
        <span>Future descriptions containing this text will use {props.typeLabel} / {props.categoryLabel}.</span>
      </div>
      <label>
        Contains
        <input value={matchText} onChange={(event) => setMatchText(event.target.value)} aria-label={`Rule text for ${props.description}`} />
      </label>
      <button type="button" className="secondaryButton compactButton" onClick={() => void save()} disabled={!matchText.trim() || props.disabled || saving}>
        <Sparkles size={14} />{saving ? "Saving…" : "Save rule"}
      </button>
    </div>
  );
}
