import { describe, expect, it } from "vitest";

import { accountCategoryLabel, isFlatAccountGroup } from "./AccountNav";

describe("account navigation grouping", () => {
  it("flattens only institutions with one account", () => {
    const account = { id: 1, display_name: "Checking", account_type: "checking", last_four: "1234", sidebar_balance_cents: 100, sidebar_balance_kind: "anchored_balance" };
    expect(isFlatAccountGroup({ rows: [account] })).toBe(true);
    expect(isFlatAccountGroup({ rows: [account, { ...account, id: 2 }] })).toBe(false);
    expect(isFlatAccountGroup({ rows: [] })).toBe(false);
  });

  it("maps account types into the Figma taxonomy categories", () => {
    expect(accountCategoryLabel("checking")).toBe("Checking & Savings");
    expect(accountCategoryLabel("credit_card")).toBe("Credit Cards");
    expect(accountCategoryLabel("brokerage")).toBe("Investments");
    expect(accountCategoryLabel("loan")).toBe("Other Accounts");
  });
});
