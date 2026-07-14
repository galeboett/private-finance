import { CheckCircle2, RefreshCw, WalletCards } from "lucide-react";

export type TransferTransaction = {
  id: number;
  account_id: number;
  raw_description: string;
  amount_cents: number;
  transaction_type: string;
  review_status: string;
  transaction_date: string;
};

export type TransferCandidate = {
  id: number;
  from_transaction: TransferTransaction;
  to_transaction: TransferTransaction;
  match_confidence: number;
  confirmed: boolean;
  suggested_type: string;
};

type Props = {
  candidates: TransferCandidate[];
  accountName: (accountId: number) => string;
  formatDate: (value: string) => string;
  formatMoney: (cents: number) => string;
  typeLabel: (value: string) => string;
  onDetect: () => void;
  onConfirm: (candidateId: number) => void;
  onReject: (candidateId: number) => void;
};

export function TransferReview({ candidates, accountName, formatDate, formatMoney, typeLabel, onDetect, onConfirm, onReject }: Props) {
  return (
    <section className="toolPanel transferReviewPanel" id="transfer-review">
      <div className="panelTitle"><WalletCards size={18} /><div><h3>Transfer Review</h3><p>Find bank transfers and credit card payments so reports do not count them as spending.</p></div></div>
      <div className="transferIntro">
        <div><strong>{candidates.length} open matches</strong><span>Matches use equal-and-opposite amounts across accounts within five days.</span></div>
        <button className="primaryButton" onClick={onDetect}><RefreshCw size={16} />Find transfers/payments</button>
      </div>
      <div className="transferList">
        {candidates.map((candidate) => (
          <article className="transferCard" key={candidate.id}>
            <div className="transferCardTop"><div><strong>{typeLabel(candidate.suggested_type)}</strong><span>{candidate.match_confidence}% confidence</span></div><span className="statusBadge suggested">Suggested</span></div>
            <div className="transferPair">
              <div><small>Money out</small><strong>{accountName(candidate.from_transaction.account_id)}</strong><span>{formatDate(candidate.from_transaction.transaction_date)} / {candidate.from_transaction.raw_description}</span><b>{formatMoney(candidate.from_transaction.amount_cents)}</b></div>
              <div><small>Money in</small><strong>{accountName(candidate.to_transaction.account_id)}</strong><span>{formatDate(candidate.to_transaction.transaction_date)} / {candidate.to_transaction.raw_description}</span><b>{formatMoney(candidate.to_transaction.amount_cents)}</b></div>
            </div>
            <div className="reviewActions"><button className="dangerTextButton" onClick={() => onReject(candidate.id)}>Reject</button><button className="primaryButton" onClick={() => onConfirm(candidate.id)}><CheckCircle2 size={16} />Confirm match</button></div>
          </article>
        ))}
        {candidates.length === 0 ? <p className="emptyText">No transfer suggestions yet. Import the matching bank/card files, then run the finder.</p> : null}
      </div>
    </section>
  );
}
