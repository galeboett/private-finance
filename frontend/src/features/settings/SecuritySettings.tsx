import { ShieldCheck } from "lucide-react";
import { useState } from "react";
import { api } from "../../api/client";
import { useApiMutation } from "../../api/hooks";
import { PanelTitle } from "../../components/AppPrimitives";

export function SecuritySettings({ csrf, onChanged, onError }: { csrf: string; onChanged: (message: string) => void; onError: (message: string) => void }) {
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const changePassword = useApiMutation(
    () => api<{ ok: boolean }>("/api/password", { method: "POST", headers: { "x-csrf-token": csrf }, body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }) }),
    { onSuccess: () => { setCurrentPassword(""); setNewPassword(""); setConfirmation(""); onChanged("Password changed. Other sessions were signed out."); }, onError: (error) => onError(error.message) },
  );
  const valid = currentPassword.length > 0 && newPassword.length >= 12 && newPassword === confirmation;
  return <section className="settingsPanel settingsSectionPanel"><PanelTitle icon={ShieldCheck} title="Security" subtitle="Protect this local app and retire other signed-in sessions." /><div className="securitySettingsCard"><label>Current password<input type="password" autoComplete="current-password" value={currentPassword} onChange={(event) => setCurrentPassword(event.target.value)} /></label><label>New password<input type="password" autoComplete="new-password" value={newPassword} onChange={(event) => setNewPassword(event.target.value)} /><small>Use at least 12 characters.</small></label><label>Confirm new password<input type="password" autoComplete="new-password" value={confirmation} onChange={(event) => setConfirmation(event.target.value)} /></label>{confirmation && newPassword !== confirmation ? <p className="validationError">The new passwords do not match.</p> : null}<button className="primaryButton" type="button" disabled={!valid || changePassword.isPending} onClick={() => changePassword.mutate()}>{changePassword.isPending ? "Changing…" : "Change password"}</button><p className="emptyText">Changing the password invalidates every other session. This browser stays signed in.</p></div></section>;
}
