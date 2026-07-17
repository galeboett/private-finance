import { ArrowDownToLine, Database, RefreshCw, Trash2 } from "lucide-react";
import { useState, type ReactNode } from "react";
import { api } from "../../api/client";
import { useApiMutation, useApiQuery } from "../../api/hooks";
import { PanelTitle } from "../../components/AppPrimitives";

type BackupState = { backup_dir: string; backups: Array<{ name: string; size_bytes: number; modified_at: string }> };

type Props = {
  csrf: string;
  busy: boolean;
  appImportFile: File | null;
  onChooseImport: (file: File | null) => void;
  onExport: () => void;
  onRestoreExport: () => void;
  onOpenTrash: () => void;
  onChanged: (message: string) => void;
  onError: (message: string) => void;
  maintenance?: ReactNode;
};

export function DataSettings({ csrf, busy, appImportFile, onChooseImport, onExport, onRestoreExport, onOpenTrash, onChanged, onError, maintenance }: Props) {
  const [backupName, setBackupName] = useState("");
  const backups = useApiQuery<BackupState>(["backups"], "/api/backups");
  const createBackup = useApiMutation(
    () => api<{ path: string }>(`/api/backups${backupName.trim() ? `?destination=${encodeURIComponent(backupName.trim())}` : ""}`, { method: "POST", headers: { "x-csrf-token": csrf } }),
    { onSuccess: (result) => { setBackupName(""); void backups.refetch(); onChanged(`Database backup created at ${result.path}.`); }, onError: (error) => onError(error.message) },
  );
  const restoreBackup = useApiMutation(
    (source: string) => api<{ pre_restore_copy: string }>(`/api/backups/restore?source=${encodeURIComponent(source)}`, { method: "POST", headers: { "x-csrf-token": csrf } }),
    { onSuccess: (result) => { void backups.refetch(); onChanged(`Database restored. A safety copy was created at ${result.pre_restore_copy}. Reload the app before continuing.`); }, onError: (error) => onError(error.message) },
  );
  function confirmRestore(path: string) {
    if (window.confirm("Restore this database backup? Current data will be replaced after a safety copy is created.")) restoreBackup.mutate(path);
  }
  return (
    <section className="settingsPanel settingsSectionPanel">
      <PanelTitle icon={Database} title="Data" subtitle="Back up, export, restore, and maintain local financial data." />
      <div className="settingsCard">
        <div><strong>Database backup</strong><span>Creates a complete SQLite copy, including Activity history and undo data.</span></div>
        <div className="buttonRow"><input value={backupName} onChange={(event) => setBackupName(event.target.value)} placeholder="Optional backup name.sqlite3" /><button className="primaryButton" type="button" disabled={createBackup.isPending} onClick={() => createBackup.mutate()}>Create backup</button><button className="secondaryButton" type="button" onClick={() => void backups.refetch()}><RefreshCw size={14} />Refresh</button></div>
        <small>{backups.data?.backup_dir ?? "Loading backup folder…"}</small>
        {backups.data?.backups?.length ? <div className="backupList">{backups.data.backups.map((backup) => <div key={backup.name}><span><strong>{backup.name}</strong><small>{new Date(backup.modified_at).toLocaleString()} · {(backup.size_bytes / 1024 / 1024).toFixed(1)} MB</small></span><button className="dangerTextButton" type="button" disabled={restoreBackup.isPending} onClick={() => confirmRestore(backup.name)}>Restore</button></div>)}</div> : <p className="emptyText">No database backups found yet.</p>}
      </div>
      <div className="settingsCard">
        <div><strong>Portable app-data export</strong><span>JSON is useful for moving data between compatible app installs. A database backup is the safer full-fidelity recovery copy.</span></div>
        <div className="buttonRow"><button className="secondaryButton" type="button" onClick={onExport}><ArrowDownToLine size={16} />Export app data</button><input type="file" accept="application/json,.json" onChange={(event) => onChooseImport(event.target.files?.[0] ?? null)} /><button className="dangerTextButton" type="button" onClick={onRestoreExport} disabled={!appImportFile || busy}>Import JSON backup</button></div>
      </div>
      <div className="settingsCard"><div><strong>Transaction Trash</strong><span>Deleted transactions stay recoverable until you permanently remove them.</span></div><button className="secondaryButton" type="button" onClick={onOpenTrash}><Trash2 size={15} />Open Trash</button></div>
      <details className="maintenanceSettings"><summary><span><strong>Maintenance</strong><small>One-time repair and cleanup tools. You rarely need these.</small></span></summary>{maintenance ?? <p className="emptyText">No maintenance action currently needs attention.</p>}</details>
    </section>
  );
}
