import { FinanceWorkspaceView } from "./app/FinanceWorkspaceView";
import { useFinanceController } from "./app/useFinanceController";

export function App() {
  const controller = useFinanceController();
  return <FinanceWorkspaceView controller={controller} />;
}
