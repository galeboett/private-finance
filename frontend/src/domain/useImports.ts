import { useCallback } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useApiQuery } from "../api/hooks";

export function useImports<TInbox>(enabled: boolean) {
  const queryClient = useQueryClient();
  const inbox = useApiQuery<TInbox>(["imports", "inbox"], "/api/imports/inbox", { enabled });
  const invalidate = useCallback(
    () => queryClient.invalidateQueries({ queryKey: ["imports"] }),
    [queryClient],
  );

  return { inbox, invalidate };
}
