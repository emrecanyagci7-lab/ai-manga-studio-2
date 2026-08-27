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
      toast.error("Kullanım verisi yüklenemedi");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); /* eslint-disable-next-line */ }, []);

  return (
    <div className="max-w-4xl mx-auto px-4 sm:px-6 py-12">
      <div className="flex items-end justify-between mb-8 gap-4">
        <div>
          <div className="text-xs tracking-[0.3em] uppercase text-violet-400 mb-2">// Stüdyo Ayarları</div>
          <h1 className="font-display text-5xl tracking-widest uppercase">Ayarlar</h1>
        </div>
        <Button data-testid="usage-refresh" variant="outline" className="border-white/15" onClick={load}>
          {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <><RefreshCw className="w-4 h-4 mr-2" /> Yenile</>}
        </Button>
      </div>

      {/* Usage meter */}
      <section className="mb-10">
        <div className="mb-4">
          <h2 className="font-display text-2xl tracking-widest uppercase">Kredi Sayacı</h2>
          <p className="text-sm text-slate-400 mt-1">Bu cihazdaki tüm mangalarının toplam yapay zekâ kullanımı.</p>
        </div>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <StatTile icon={Cpu} label="Metin Çağrısı" value={usage?.totals?.text_calls ?? 0} hint="Hikâye rehberi + sahne planı" />
          <StatTile icon={ImageIcon} label="Görsel Çağrısı" value={usage?.totals?.image_calls ?? 0} hint="Paneller + portreler" />
          <StatTile icon={BookOpen} label="Biten Bölüm" value={usage?.totals?.chapters_generated ?? 0} hint={`${usage?.totals?.panels_generated ?? 0} panel çizildi`} />
          <StatTile
            icon={DollarSign}
            label="Tahmini Maliyet"
            value={`$${(usage?.estimated_credits_spent_usd ?? 0).toFixed(2)}`}
            hint="Ücretsiz katman — kota limiti içinde 0₺"
          />
        </div>
        <div className="mt-6 ink-card p-4 border border-violet-500/20 bg-violet-500/5">
          <p className="text-sm text-slate-300 leading-relaxed">
            <span className="text-violet-300 font-semibold">Koruma önerisi:</span> Her manga için bölüm başına panel limiti bulunur (varsayılan 8). Bunu manga detay sayfasından değiştirebilirsin. Daha düşük limit = daha az maliyet.
          </p>
        </div>
      </section>

      <section className="space-y-4">
        <h2 className="font-display text-2xl tracking-widest uppercase mb-2">Stüdyo</h2>
        <div className="ink-card p-6 space-y-4">
          <div>
            <div className="text-[10px] tracking-widest uppercase text-violet-400 mb-1">Anonim Kullanıcı Kimliği</div>
            <div className="font-mono text-sm break-all text-slate-300" data-testid="settings-client-id">{cid}</div>
            <p className="text-xs text-slate-500 mt-2">Kütüphanen bu cihaza bağlı. MVP için kayıt gerekmez.</p>
          </div>
          <div>
            <div className="text-[10px] tracking-widest uppercase text-violet-400 mb-1">Metin Modeli</div>
            <div className="text-sm text-slate-300">Google Gemini 2.0 Flash <span className="text-slate-500">(birincil, ücretsiz katman)</span> · Gemini 1.5 Flash <span className="text-slate-500">(yedek)</span></div>
          </div>
          <div>
            <div className="text-[10px] tracking-widest uppercase text-violet-400 mb-1">Görsel Modeli</div>
            <div className="text-sm text-slate-300">Pollinations.ai <span className="text-slate-500">(FLUX tabanlı, anahtarsız ücretsiz)</span></div>
          </div>
        </div>
      </section>
    </div>
  );
}
