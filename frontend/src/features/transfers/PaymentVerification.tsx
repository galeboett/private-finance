import { AlertTriangle, CheckCircle2, CreditCard, X } from "lucide-react";
import { ExternalPaymentAction, type ExternalAccountOption } from "../accounts/ExternalPaymentAction";

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
  external_payments: number;
  latest_matched_date: string | null;
  warnings: PaymentWarning[];
};

type Props = {
  status: PaymentVerificationStatus | null;
  formatMoney: (cents: number) => string;
  onInvestigate: (warning: PaymentWarning) => void;
  onDismiss: (warning: PaymentWarning) => void;
  externalAccounts: ExternalAccountOption[];
  csrf: string;
  onExternalSettled: (operationId: string) => Promise<void>;
  onError: (message: string) => void;
};

export function PaymentVerification({ status, formatMoney, onInvestigate, onDismiss, externalAccounts, csrf, onExternalSettled, onError }: Props) {
  if (!status) return null;
  return (
    <section className={status.warnings.length ? "paymentVerification warning" : "paymentVerification"}>
      <div className="paymentVerificationTitle">
        {status.warnings.length ? <AlertTriangle size={17} /> : <CreditCard size={17} />}
        <div>
          <strong>Card payment verification</strong>
          <span>{status.matched_payments} confirmed payment{status.matched_payments === 1 ? "" : "s"}{status.external_payments ? ` · ${status.external_payments} external` : ""}{status.latest_matched_date ? ` · latest ${status.latest_matched_date}` : ""}</span>
        </div>
        {!status.warnings.length ? <CheckCircle2 size={17} className="paymentVerifiedIcon" /> : null}
      </div>
      {status.warnings.map((warning) => (
        <div className="paymentWarningRow" key={warning.transaction_id}>
          <span><strong>{formatMoney(warning.amount_cents)}</strong> {warning.description} · {warning.transaction_date} ({warning.age_days} days ago)</span>
          <div className="paymentWarningActions">
            <button className="ghostButton compactButton" onClick={() => onInvestigate(warning)}>Investigate</button>
            <ExternalPaymentAction transactionId={warning.transaction_id} accounts={externalAccounts} csrf={csrf} onSettled={onExternalSettled} onError={onError} />
            <button className="ghostButton compactButton" onClick={() => onDismiss(warning)} title="Dismiss this warning as not a card payment"><X size={13} />Not a payment</button>
          </div>
        </div>
      ))}
    </section>
  );
}
