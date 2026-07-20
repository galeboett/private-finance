import { useCallback } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useApiQuery } from "../api/hooks";

export function useReviewQueue<TTransfer, TRefund, TDuplicate, TReconciliation, TPayment>(enabled: boolean) {
  const queryClient = useQueryClient();
  const transfers = useApiQuery<TTransfer[]>(["transfers", "unconfirmed"], "/api/transfers/unconfirmed", { enabled });
  const refunds = useApiQuery<TRefund[]>(["refunds", "suggestions"], "/api/refunds/suggestions", { enabled });
  const duplicates = useApiQuery<TDuplicate[]>(["duplicates", "pending"], "/api/duplicates/pending", { enabled });
  const reconciliation = useApiQuery<TReconciliation[]>(["reconciliation", "status"], "/api/reconciliation", { enabled });
  const payments = useApiQuery<TPayment[]>(["transfers", "payments"], "/api/transfers/payments", { enabled });
  const invalidate = useCallback(
    () => Promise.all([
      queryClient.invalidateQueries({ queryKey: ["transfers"] }),
      queryClient.invalidateQueries({ queryKey: ["refunds"] }),
      queryClient.invalidateQueries({ queryKey: ["duplicates"] }),
      queryClient.invalidateQueries({ queryKey: ["reconciliation"] }),
    ]),
    [queryClient],
  );

  return { transfers, refunds, duplicates, reconciliation, payments, invalidate };
}
