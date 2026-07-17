import { describe, expect, it } from "vitest";
import { settingsTabs } from "./SettingsNavigation";

describe("settings information architecture", () => {
  it("keeps the five planned settings destinations in order", () => {
    expect(settingsTabs.map((tab) => tab.id)).toEqual(["imports", "accounts", "categories", "data", "security"]);
  });
});
