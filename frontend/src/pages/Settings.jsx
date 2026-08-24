import { getClientId } from "../lib/client";

export default function Settings() {
  const cid = getClientId();
  return (
    <div className="max-w-3xl mx-auto px-4 sm:px-6 py-12">
      <div className="mb-8">
        <div className="text-xs tracking-[0.3em] uppercase text-violet-400 mb-2">// Studio Config</div>
        <h1 className="font-display text-5xl tracking-widest uppercase">Settings</h1>
      </div>
      <div className="ink-card p-6 space-y-4">
        <div>
          <div className="text-[10px] tracking-widest uppercase text-violet-400 mb-1">Anonymous Client ID</div>
          <div className="font-mono text-sm break-all text-slate-300" data-testid="settings-client-id">{cid}</div>
          <p className="text-xs text-slate-500 mt-2">Your library is tied to this device. Signup is not required for MVP.</p>
        </div>
        <div>
          <div className="text-[10px] tracking-widest uppercase text-violet-400 mb-1">Text Model</div>
          <div className="text-sm text-slate-300">Claude Sonnet 4.6 <span className="text-slate-500">(primary)</span> · Gemini 3 Flash <span className="text-slate-500">(fallback)</span></div>
        </div>
        <div>
          <div className="text-[10px] tracking-widest uppercase text-violet-400 mb-1">Image Model</div>
          <div className="text-sm text-slate-300">Gemini Nano Banana <span className="text-slate-500">(reference-image editing)</span></div>
        </div>
      </div>
    </div>
  );
}
