import { useEffect, useState } from 'react';
import { fetchHealth, HealthStatus } from './api/client';
import { Activity, Database, Server, CheckCircle2, AlertCircle } from 'lucide-react';

export function App() {
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchHealth()
      .then((data) => {
        setHealth(data);
        setLoading(false);
      })
      .catch((err) => {
        setError(err.message);
        setLoading(false);
      });
  }, []);

  return (
    <div className="min-h-screen flex flex-col items-center justify-center p-6 bg-slate-950 text-slate-100">
      <div className="max-w-md w-full bg-slate-900 border border-slate-800 rounded-xl p-6 shadow-2xl space-y-6">
        <div className="flex items-center space-x-3 border-b border-slate-800 pb-4">
          <div className="p-2 bg-indigo-500/10 rounded-lg text-indigo-400">
            <Activity className="w-6 h-6" />
          </div>
          <div>
            <h1 className="text-xl font-bold tracking-tight">ExamOS</h1>
            <p className="text-xs text-slate-400">Milestone 0 Environment Foundation</p>
          </div>
        </div>

        <div className="space-y-4">
          <h2 className="text-sm font-semibold text-slate-300 uppercase tracking-wider">System Readiness</h2>
          
          {loading && (
            <div className="flex items-center space-x-2 text-slate-400 text-sm">
              <span className="animate-spin rounded-full h-4 w-4 border-b-2 border-indigo-500"></span>
              <span>Checking backend & database connectivity...</span>
            </div>
          )}

          {error && (
            <div className="flex items-start space-x-3 p-3 bg-red-500/10 border border-red-500/20 rounded-lg text-red-400 text-sm">
              <AlertCircle className="w-5 h-5 flex-shrink-0 mt-0.5" />
              <div>
                <p className="font-medium">Connection Error</p>
                <p className="text-xs text-red-300 mt-1">{error}</p>
              </div>
            </div>
          )}

          {health && (
            <div className="space-y-3">
              <div className="flex items-center justify-between p-3 bg-slate-800/50 rounded-lg border border-slate-700/50">
                <div className="flex items-center space-x-2.5">
                  <Server className="w-4 h-4 text-emerald-400" />
                  <span className="text-sm text-slate-300">FastAPI Backend</span>
                </div>
                <div className="flex items-center space-x-1.5 text-xs text-emerald-400 font-medium">
                  <CheckCircle2 className="w-3.5 h-3.5" />
                  <span>{health.status.toUpperCase()}</span>
                </div>
              </div>

              <div className="flex items-center justify-between p-3 bg-slate-800/50 rounded-lg border border-slate-700/50">
                <div className="flex items-center space-x-2.5">
                  <Database className="w-4 h-4 text-emerald-400" />
                  <span className="text-sm text-slate-300">PostgreSQL (16-alpine)</span>
                </div>
                <div className="flex items-center space-x-1.5 text-xs text-emerald-400 font-medium">
                  <CheckCircle2 className="w-3.5 h-3.5" />
                  <span>{health.database.toUpperCase()}</span>
                </div>
              </div>

              <div className="text-xs text-slate-500 text-center pt-2">
                Environment: <span className="text-slate-400 font-mono">{health.app_env}</span>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export default App;
