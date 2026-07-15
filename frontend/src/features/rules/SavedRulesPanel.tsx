import { Sparkles } from "lucide-react";

import { PanelTitle } from "../../components/AppPrimitives";
import { transactionTypeUsesCategory } from "../../lib/transactionTypes";

export type SavedRule = { id: number; category_id: number | null; priority: number; field_name: string; match_text: string; suggested_transaction_type: string };
type Category = { id: number; label: string };
type TransactionTypeOption = { value: string; label: string };
type LastSavedRule = { id: number; matchText: string; transactionId: number };

type Props = {
  rules: SavedRule[];
  categories: Category[];
  transactionTypes: TransactionTypeOption[];
  lastSavedRule: LastSavedRule | null;
  editingRule: SavedRule | null;
  feedback: { ruleId: number; message: string } | null;
  focusedTransaction: { id: number; raw_description: string } | null;
  readableType: (value: string) => string;
  onApplyOne: (ruleId: number, transactionId: number) => void;
  onApplySaved: (scope: "unreviewed" | "all") => void;
  onApply: (ruleId: number, scope: "unreviewed" | "all") => void;
  onPreview: (ruleId: number) => void;
  onEdit: (rule: SavedRule | null) => void;
  onSaveEdit: () => void;
  onDelete: (rule: SavedRule) => void;
};

export function SavedRulesPanel(props: Props) {
  return (
    <aside className="toolPanel rulesPanel" id="saved-rules">
      <PanelTitle icon={Sparkles} title="Saved Rules" subtitle="Preview, edit, and apply automatic categorization." />
      {props.lastSavedRule ? <div className="ruleApplyPanel"><div><strong>Rule saved for "{props.lastSavedRule.matchText}"</strong><span>Apply it now to classify and confirm matching transactions.</span></div><div className="buttonRow"><button className="primaryButton" onClick={() => props.onApplyOne(props.lastSavedRule!.id, props.lastSavedRule!.transactionId)}>Apply &amp; confirm this row</button><button className="secondaryButton" onClick={() => props.onApplySaved("unreviewed")}>Apply unreviewed</button><button className="secondaryButton" onClick={() => props.onApplySaved("all")}>Apply previous</button></div></div> : null}
      {props.rules.length ? <div className="savedRulesPanel">{props.rules.map((rule) => {
        const category = props.categories.find((item) => item.id === rule.category_id);
        const matchesFocus = props.focusedTransaction?.raw_description.toUpperCase().includes(rule.match_text.toUpperCase());
        return <div className="savedRuleGroup" key={rule.id}><div className="savedRuleRow"><div><span>{rule.match_text}</span><small>{category?.label ?? "No category"} / {props.readableType(rule.suggested_transaction_type)} / priority {rule.priority}</small></div><div className="savedRuleActions"><button className="secondaryButton" onClick={() => props.onPreview(rule.id)}>Preview</button>{matchesFocus ? <button className="primaryButton" onClick={() => props.onApplyOne(rule.id, props.focusedTransaction!.id)}>Apply &amp; confirm this row</button> : null}<button className="secondaryButton" onClick={() => props.onApply(rule.id, "unreviewed")}>Apply unreviewed</button><button className="secondaryButton" onClick={() => props.onApply(rule.id, "all")}>Apply previous</button><button className="secondaryButton" onClick={() => props.onEdit({ ...rule })}>Edit</button><button className="dangerTextButton" onClick={() => props.onDelete(rule)}>Delete</button></div></div>
          {props.feedback?.ruleId === rule.id ? <div className="ruleInlineFeedback" role="status">{props.feedback.message}</div> : null}
          {props.editingRule?.id === rule.id ? <div className="ruleEditRow"><label>Contains<input value={props.editingRule.match_text} onChange={(event) => props.onEdit({ ...props.editingRule!, match_text: event.target.value })} /></label><label>Category<select value={props.editingRule.category_id ?? ""} disabled={!transactionTypeUsesCategory(props.editingRule.suggested_transaction_type)} onChange={(event) => props.onEdit({ ...props.editingRule!, category_id: event.target.value ? Number(event.target.value) : null })}><option value="">No category</option>{props.categories.map((item) => <option value={item.id} key={item.id}>{item.label}</option>)}</select></label><label>Type<select value={props.editingRule.suggested_transaction_type} onChange={(event) => { const nextType = event.target.value; props.onEdit({ ...props.editingRule!, suggested_transaction_type: nextType, category_id: transactionTypeUsesCategory(nextType) ? props.editingRule!.category_id : null }); }}>{props.transactionTypes.map((item) => <option value={item.value} key={item.value}>{item.label}</option>)}</select></label><label>Priority<input type="number" value={props.editingRule.priority} onChange={(event) => props.onEdit({ ...props.editingRule!, priority: Number(event.target.value) })} /><small>Smaller numbers run first.</small></label><button className="primaryButton" onClick={props.onSaveEdit}>Save</button><button className="ghostButton" onClick={() => props.onEdit(null)}>Cancel</button></div> : null}
        </div>;
      })}</div> : <div className="rulesEmptyState"><strong>No saved rules yet</strong><span>Choose a type and, when needed, a category on an inbox item, then select Save rule.</span></div>}
    </aside>
  );
}
