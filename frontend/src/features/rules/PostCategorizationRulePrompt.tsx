import { Check, Pencil, Sparkles, X } from "lucide-react";
import { useEffect, useState } from "react";

import { transactionTypeUsesCategory } from "../../lib/transactionTypes";

type Category = { id: number; label: string };
type TransactionTypeOption = { value: string; label: string };
type RulePromptTransaction = {
  id: number;
  raw_description: string;
  transaction_type: string;
  category_id: number | null;
};

export type RuleDraft = {
  matchText: string;
  transactionType: string;
  categoryId: number | null;
};

export type SavedRulePreview = {
  ruleId: number;
  existingMatches: number;
};

type Props = {
  transaction: RulePromptTransaction;
  categories: Category[];
  transactionTypes: TransactionTypeOption[];
  onSave: (draft: RuleDraft) => Promise<SavedRulePreview | null>;
  onApplyExisting: (ruleId: number) => Promise<boolean>;
  onDismiss: () => void;
};

function suggestedRuleText(description: string) {
  const cleaned = description.replace(/[^a-zA-Z0-9\s*&]/g, " ").replace(/\s+/g, " ").trim();
  return cleaned.split(" ").slice(0, 3).join(" ").toUpperCase() || description.slice(0, 40).toUpperCase();
}

export function PostCategorizationRulePrompt(props: Props) {
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [applying, setApplying] = useState(false);
  const [savedRule, setSavedRule] = useState<SavedRulePreview | null>(null);
  const [matchText, setMatchText] = useState(() => suggestedRuleText(props.transaction.raw_description));
  const [transactionType, setTransactionType] = useState(props.transaction.transaction_type);
  const [categoryId, setCategoryId] = useState<number | null>(props.transaction.category_id);

  useEffect(() => {
    setEditing(false);
    setSaving(false);
    setApplying(false);
    setSavedRule(null);
    setMatchText(suggestedRuleText(props.transaction.raw_description));
    setTransactionType(props.transaction.transaction_type);
    setCategoryId(props.transaction.category_id);
  }, [props.transaction.id, props.transaction.raw_description, props.transaction.transaction_type, props.transaction.category_id]);

  const typeLabel = props.transactionTypes.find((type) => type.value === transactionType)?.label ?? transactionType;
  const categoryLabel = transactionTypeUsesCategory(transactionType)
    ? props.categories.find((category) => category.id === categoryId)?.label ?? "No category"
    : "No category needed";
  const invalidCategory = transactionTypeUsesCategory(transactionType) && categoryId === null;

  async function saveRule() {
    if (!matchText.trim() || invalidCategory || saving) return;
    setSaving(true);
    try {
      const result = await props.onSave({ matchText: matchText.trim(), transactionType, categoryId });
      if (result) setSavedRule(result);
    } finally {
      setSaving(false);
    }
  }

  async function applyExisting() {
    if (!savedRule || applying) return;
    setApplying(true);
    try {
      if (await props.onApplyExisting(savedRule.ruleId)) props.onDismiss();
    } finally {
      setApplying(false);
    }
  }

  if (savedRule) {
    return (
      <section className="postCategorizationPrompt confirmation" aria-live="polite">
        <div className="rulePromptIcon"><Check size={17} /></div>
        <div className="rulePromptCopy">
          <strong>Rule saved for future transactions</strong>
          {savedRule.existingMatches > 0 ? (
            <span>{savedRule.existingMatches} existing transaction{savedRule.existingMatches === 1 ? "" : "s"} across all accounts also match. Apply the rule and confirm them?</span>
          ) : (
            <span>No other existing transactions match. New matching transactions will use this rule.</span>
          )}
        </div>
        <div className="rulePromptActions">
          {savedRule.existingMatches > 0 ? <button type="button" className="primaryButton compactButton" onClick={() => void applyExisting()} disabled={applying}>{applying ? "Applying…" : `Apply to ${savedRule.existingMatches}`}</button> : null}
          <button type="button" className="ghostButton compactButton" onClick={props.onDismiss}>{savedRule.existingMatches > 0 ? "Not now" : "Done"}</button>
        </div>
      </section>
    );
  }

  return (
    <section className="postCategorizationPrompt" aria-live="polite">
      <div className="rulePromptIcon"><Sparkles size={17} /></div>
      <div className="rulePromptCopy">
        <strong>Categorized {props.transaction.raw_description}</strong>
        <span>{typeLabel} / {categoryLabel}. Save this decision as a rule for matching transactions across all accounts?</span>
      </div>
      {editing ? (
        <div className="rulePromptEditor">
          <label>Contains<input value={matchText} onChange={(event) => setMatchText(event.target.value)} autoFocus /></label>
          <label>Type<select value={transactionType} onChange={(event) => { const nextType = event.target.value; setTransactionType(nextType); if (!transactionTypeUsesCategory(nextType)) setCategoryId(null); }}>{props.transactionTypes.map((type) => <option key={type.value} value={type.value}>{type.label}</option>)}</select></label>
          <label>Category<select value={categoryId ?? ""} disabled={!transactionTypeUsesCategory(transactionType)} onChange={(event) => setCategoryId(event.target.value ? Number(event.target.value) : null)}><option value="">No category</option>{props.categories.map((category) => <option key={category.id} value={category.id}>{category.label}</option>)}</select></label>
          <small>Scope: all accounts</small>
        </div>
      ) : null}
      <div className="rulePromptActions">
        <button type="button" className="primaryButton compactButton" onClick={() => void saveRule()} disabled={!matchText.trim() || invalidCategory || saving}>{saving ? "Saving…" : "Save rule"}</button>
        <button type="button" className="secondaryButton compactButton" onClick={() => setEditing((current) => !current)}><Pencil size={14} />{editing ? "Close editor" : "Edit rule"}</button>
        <button type="button" className="ghostButton compactButton" onClick={props.onDismiss}><X size={14} />Dismiss</button>
      </div>
    </section>
  );
}
