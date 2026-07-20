import { ArrowDownToLine, Database, RefreshCw, Trash2 } from "lucide-react";
import { useState } from "react";
import { api, useApiMutation, useApiQuery } from "../../api/hooks";
import { PanelTitle } from "../../components/AppPrimitives";

type Backup = { name: string; size_bytes: number; modified_at: string; encrypted: boolean };
type BackupState = { backup_dir: string; backups: Backup[] };

type Props = {
  csrf: string;
  busy: boolean;
  appImportFile: File | null;
  onChooseImport: (file: File | null) => void;
  onExport: (password: string, passphrase?: string) => void;
  onRestoreExport: (password: string, passphrase?: string) => void;
  onOpenTrash: () => void;
  onChanged: (message: string) => void;
  onError: (message: string) => void;
};

export function DataSettings({ csrf, busy, appImportFile, onChooseImport, onExport, onRestoreExport, onOpenTrash, onChanged, onError }: Props) {
  const [backupName, setBackupName] = useState("");
  const [accountPassword, setAccountPassword] = useState("");
  const [archivePassphrase, setArchivePassphrase] = useState("");
  const backups = useApiQuery<BackupState>(["backups"], "/api/backups");

  async function reauthenticate() {
    if (!accountPassword) throw new Error("Enter your current password.");
    await api("/api/reauthenticate", {
      method: "POST",
      headers: { "x-csrf-token": csrf },
      body: JSON.stringify({ password: accountPassword }),
    });
  }

  const createBackup = useApiMutation(
    async () => {
      await reauthenticate();
      return api<{ path: string }>("/api/backups", {
        method: "POST",
        headers: { "x-csrf-token": csrf },
        body: JSON.stringify({
          destination: backupName.trim() || null,
          passphrase: archivePassphrase || null,
        }),
      });
    },
    {
      onSuccess: (result) => {
        setBackupName("");
        setAccountPassword("");
        setArchivePassphrase("");
        void backups.refetch();
        onChanged(`Database backup created at ${result.path}.`);
      },
      onError: (error) => onError(error.message),
    },
  );

  const restoreBackup = useApiMutation(
    async (backup: Backup) => {
      await reauthenticate();
      return api<{ pre_restore_copy: string }>("/api/backups/restore", {
        method: "POST",
        headers: { "x-csrf-token": csrf },
        body: JSON.stringify({
          source: backup.name,
          passphrase: backup.encrypted ? archivePassphrase || null : null,
        }),
      });
    },
    {
      onSuccess: (result) => {
        setAccountPassword("");
        setArchivePassphrase("");
        void backups.refetch();
        onChanged(`Database restored. A safety copy was created at ${result.pre_restore_copy}. Reload the app before continuing.`);
      },
      onError: (error) => onError(error.message),
    },
  );

  function confirmRestore(backup: Backup) {
    if (window.confirm("Restore this database backup? Current data will be replaced after a safety copy is created.")) restoreBackup.mutate(backup);
  }

  const canAuthorize = accountPassword.length > 0;
  const passphraseValid = archivePassphrase.length === 0 || archivePassphrase.length >= 12;

  return (
    <section className="settingsPanel settingsSectionPanel">
      <PanelTitle icon={Database} title="Data" subtitle="Back up, export, restore, and maintain local financial data." />
      <div className="settingsCard">
        <div><strong>Protect sensitive actions</strong><span>Exports and restores require your current password. Authorization lasts five minutes.</span></div>
        <label>Current password<input type="password" autoComplete="current-password" value={accountPassword} onChange={(event) => setAccountPassword(event.target.value)} /></label>
        <label>Archive passphrase<input type="password" autoComplete="new-password" value={archivePassphrase} onChange={(event) => setArchivePassphrase(event.target.value)} placeholder="Optional, 12+ characters" /><small>When set, backups and portable exports use AES-256-GCM encryption. Store this passphrase in your password manager.</small></label>
      </div>
      <div className="settingsCard">
        <div><strong>Database backup</strong><span>Creates a complete SQLite copy, including Activity history and undo data. A passphrase creates an encrypted .pfbak archive.</span></div>
        <div className="buttonRow">
          <input value={backupName} onChange={(event) => setBackupName(event.target.value)} placeholder={archivePassphrase ? "Optional name.pfbak" : "Optional name.sqlite3"} />
          <button className="primaryButton" type="button" disabled={!canAuthorize || !passphraseValid || createBackup.isPending} onClick={() => createBackup.mutate()}>Create backup</button>
          <button className="secondaryButton" type="button" onClick={() => void backups.refetch()}><RefreshCw size={14} />Refresh</button>
        </div>
        <small>{backups.data?.backup_dir ?? "Loading backup folder…"}</small>
        {backups.data?.backups?.length ? <div className="backupList">{backups.data.backups.map((backup) => <div key={backup.name}><span><strong>{backup.name}</strong><small>{backup.encrypted ? "Encrypted · " : ""}{new Date(backup.modified_at).toLocaleString()} · {(backup.size_bytes / 1024 / 1024).toFixed(1)} MB</small></span><button className="dangerTextButton" type="button" disabled={!canAuthorize || (backup.encrypted && !archivePassphrase) || restoreBackup.isPending} onClick={() => confirmRestore(backup)}>Restore</button></div>)}</div> : <p className="emptyText">No database backups found yet.</p>}
      </div>
      <div className="settingsCard">
        <div><strong>Portable app-data export</strong><span>Use an archive passphrase for an encrypted .pfenc file. Plain JSON remains available when you deliberately leave it blank.</span></div>
        <div className="buttonRow">
          <button className="secondaryButton" type="button" disabled={!canAuthorize || !passphraseValid} onClick={() => { onExport(accountPassword, archivePassphrase || undefined); setAccountPassword(""); }}><ArrowDownToLine size={16} />{archivePassphrase ? "Export encrypted data" : "Export app data"}</button>
          <input type="file" accept="application/json,.json,.pfenc" onChange={(event) => onChooseImport(event.target.files?.[0] ?? null)} />
          <button className="dangerTextButton" type="button" onClick={() => { onRestoreExport(accountPassword, archivePassphrase || undefined); setAccountPassword(""); }} disabled={!appImportFile || !canAuthorize || !passphraseValid || busy}>Import backup</button>
        </div>
      </div>
      <div className="settingsCard"><div><strong>Transaction Trash</strong><span>Deleted transactions stay recoverable until you permanently remove them.</span></div><button className="secondaryButton" type="button" onClick={onOpenTrash}><Trash2 size={15} />Open Trash</button></div>
    </section>
  );
}
