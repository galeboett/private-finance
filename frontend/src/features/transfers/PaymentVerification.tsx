import { AlertTriangle, CheckCircle2, CreditCard } from "lucide-react";

export type PaymentWarning = {
  transaction_id: number;
  transaction_date: string;
  amount_cents: number;
  description: string;
  age_days: number;
};

export type PaymentVerificationStatus = {
  account_id: number;
  account_name: string;
  matched_payments: number;
  latest_matched_date: string | null;
  warnings: PaymentWarning[];
};

export function PaymentVerification({ status, formatMoney, onInvestigate }: { status: PaymentVerificationStatus | null; formatMoney: (cents: number) => string; onInvestigate: (warning: PaymentWarning) => void }) {
  if (!status) return null;
  return (
    <section className={status.warnings.length ? "paymentVerification warning" : "paymentVerification"}>
      <div className="paymentVerificationTitle">
        {status.warnings.length ? <AlertTriangle size={17} /> : <CreditCard size={17} />}
        <div>
          <strong>Card payment verification</strong>
          <span>{status.matched_payments} confirmed payment{status.matched_payments === 1 ? "" : "s"}{status.latest_matched_date ? ` · latest ${status.latest_matched_date}` : ""}</span>
        </div>
        {!status.warnings.length ? <CheckCircle2 size={17} className="paymentVerifiedIcon" /> : null}
      </div>
      {status.warnings.map((warning) => (
        <div className="paymentWarningRow" key={warning.transaction_id}>
          <span><strong>{formatMoney(warning.amount_cents)}</strong> {warning.description} · {warning.transaction_date} ({warning.age_days} days ago)</span>
          <button className="ghostButton compactButton" onClick={() => onInvestigate(warning)}>Investigate</button>
        </div>
      ))}
    </section>
  );
}
