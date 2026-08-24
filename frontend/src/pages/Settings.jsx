import { useEffect, useState } from "react";
import { toast } from "sonner";
import { Cpu, ImageIcon, BookOpen, DollarSign, Loader2, RefreshCw } from "lucide-react";
import { api, getClientId } from "../lib/client";
import { Button } from "../components/ui/button";

function StatTile({ icon: Icon, label, value, hint }) {
  return (
    <div className="ink-card p-5">
      <div className="flex items-center gap-3 mb-3">
        <div className="w-10 h-10 rounded-lg bg-violet-500/15 text-violet-300 flex items-center justify-center">
          <Icon className="w-5 h-5" />
        </div>
        <div className="text-[10px] tracking-widest uppercase text-slate-400">{label}</div>
      </div>
      <div className="font-display text-4xl tracking-wider text-white">{value}</div>
      {hint && <div className="text-xs text-slate-500 mt-1">{hint}</div>}
    </div>
  );
}

export default function Settings() {
  const cid = getClientId();
  const [usage, setUsage] = useState(null);
  const [loading, setLoading] = useState(true);

  const load = async () => {
    setLoading(true);
    try {
      const { data } = await api.get("/usage/summary", { params: { client_id: cid } });
      setUsage(data);
    } catch {
      toast.error("Could not load usage");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); /* eslint-disable-next-line */ }, []);

  return (
    <div className="max-w-4xl mx-auto px-4 sm:px-6 py-12">
      <div className="flex items-end justify-between mb-8 gap-4">
        <div>
          <div className="text-xs tracking-[0.3em] uppercase text-violet-400 mb-2">// Studio Config</div>
          <h1 className="font-display text-5xl tracking-widest uppercase">Settings</h1>
        </div>
        <Button data-testid="usage-refresh" variant="outline" className="border-white/15" onClick={load}>
          {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <><RefreshCw className="w-4 h-4 mr-2" /> Refresh</>}
        </Button>
      </div>

      {/* Usage meter */}
      <section className="mb-10">
        <div className="mb-4">
          <h2 className="font-display text-2xl tracking-widest uppercase">Credit Meter</h2>
          <p className="text-sm text-slate-400 mt-1">Cumulative AI usage across all your mangas on this device.</p>
        </div>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <StatTile icon={Cpu} label="Text Calls" value={usage?.totals?.text_calls ?? 0} hint="Story bibles + scene decomp" />
          <StatTile icon={ImageIcon} label="Image Calls" value={usage?.totals?.image_calls ?? 0} hint="Panels + portraits" />
          <StatTile icon={BookOpen} label="Chapters Done" value={usage?.totals?.chapters_generated ?? 0} hint={`${usage?.totals?.panels_generated ?? 0} panels drawn`} />
          <StatTile
            icon={DollarSign}
            label="Est. Credits"
            value={`$${(usage?.estimated_credits_spent_usd ?? 0).toFixed(2)}`}
            hint="Rough estimate — see provider dashboard"
          />
        </div>
        <div className="mt-6 ink-card p-4 border border-violet-500/20 bg-violet-500/5">
          <p className="text-sm text-slate-300 leading-relaxed">
            <span className="text-violet-300 font-semibold">Guardrail tip:</span> Each manga has a cap for panels-per-chapter (default 8). Adjust it from the manga detail page. Lower caps = smaller bills.
          </p>
        </div>
      </section>

      <section className="space-y-4">
        <h2 className="font-display text-2xl tracking-widest uppercase mb-2">Studio</h2>
        <div className="ink-card p-6 space-y-4">
          <div>
            <div className="text-[10px] tracking-widest uppercase text-violet-400 mb-1">Anonymous Client ID</div>
            <div className="font-mono text-sm break-all text-slate-300" data-testid="settings-client-id">{cid}</div>
            <p className="text-xs text-slate-500 mt-2">Your library is tied to this device. Signup not required for MVP.</p>
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
      </section>
    </div>
  );
}
